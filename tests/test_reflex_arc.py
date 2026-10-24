"""Offline wiring tests for Reflex Arc (#guardrails): FakeDecider + a correct Strands StubModel.

No network, no Bedrock. Covers the score_reflex truth table, record key order / severity in [0,1]
(MEDIUM-2/MEDIUM-5), reflex_state layout, the before-action seam (convergence + shared cap), and
the mid-generation seam (seam #2) against a stub that yields real StreamEvent chunks (HIGH-A).

Built with the AWS User Group Madurai Strands Decider hackathon kit.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

from fakes import FakeDecider
from strands.interventions import Confirm, Deny, Guide, Proceed
from strands.models.model import Model

from decider_kit.client import Decision

import agent.decision as dmod
from agent.decision import (
    QUESTIONS,
    SEVERITY_LEVELS,
    ReflexArc,
    reflex_state,
    score_reflex,
)

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------------------------------
# Helpers: build a crafted answer dict with explicit p_yes / confidence per noul and a severity.
# --------------------------------------------------------------------------------------------------

def _noul(p_yes: float) -> Decision:
    return Decision.parse({"type": "noul", "noul": float(p_yes)})


def _score(level: str) -> Decision:
    i = SEVERITY_LEVELS.index(level)
    probs = {str(k): (0.8 if k == i else 0.2 / (len(SEVERITY_LEVELS) - 1)) for k in range(len(SEVERITY_LEVELS))}
    return Decision.parse({"type": "score", "score": float(i), "probabilities": probs,
                           "legend": {str(k): lv for k, lv in enumerate(SEVERITY_LEVELS)}})


def _ans(grounded=0.95, looping=0.05, in_scope=0.95, safe=0.05, severity="fine") -> dict:
    return {"grounded": _noul(grounded), "looping": _noul(looping), "in_scope": _noul(in_scope),
            "safe": _noul(safe), "severity": _score(severity)}


# --------------------------------------------------------------------------------------------------
# score_reflex truth table — one assertion per §3.5 branch.
# --------------------------------------------------------------------------------------------------

def test_confident_danger_freezes():
    # safe p_yes=0.95 -> confidence 0.95 > 0.70 -> freeze/danger
    _, v, kind = score_reflex(_ans(safe=0.95, severity="off_the_rails"))
    assert v == "freeze" and kind == "danger"


def test_borderline_danger_freezes_unsure():
    # safe p_yes=0.55 -> confidence 0.55 in band -> freeze/unsure
    _, v, kind = score_reflex(_ans(safe=0.55, severity="drifting"))
    assert v == "freeze" and kind == "unsure"


def test_borderline_grounded_freezes_unsure():
    # grounded p_yes=0.40 (broken) -> confidence 0.60 in band -> freeze/unsure
    _, v, kind = score_reflex(_ans(grounded=0.40, severity="drifting"))
    assert v == "freeze" and kind == "unsure"


def test_grounded_broken_offrails_cuts():
    # grounded p_yes=0.05 (confidence 0.95, decisive) + off_the_rails -> cut
    _, v, kind = score_reflex(_ans(grounded=0.05, severity="off_the_rails"))
    assert v == "cut" and kind == "offrails"


def test_in_scope_broken_offrails_cuts():
    _, v, kind = score_reflex(_ans(in_scope=0.05, severity="off_the_rails"))
    assert v == "cut" and kind == "offrails"


def test_drifting_looping_steers():
    # looping p_yes=0.95 (broken, decisive) + drifting -> steer
    _, v, kind = score_reflex(_ans(looping=0.95, severity="drifting"))
    assert v == "steer" and kind == "drift"


def test_drifting_grounded_steers():
    _, v, kind = score_reflex(_ans(grounded=0.05, severity="drifting"))
    assert v == "steer" and kind == "drift"


def test_all_green_fine_proceeds():
    _, v, kind = score_reflex(_ans())
    assert v == "proceed" and kind == "clean"


def test_lone_severity_proceeds():
    # all four nouls healthy + severity=drifting -> proceed (severity never acts alone, MEDIUM-D)
    _, v, kind = score_reflex(_ans(severity="drifting"))
    assert v == "proceed" and kind == "clean"


# --------------------------------------------------------------------------------------------------
# MEDIUM-2 / MEDIUM-5: record field invariants.
# --------------------------------------------------------------------------------------------------

_SAMPLES = [
    _ans(),
    _ans(safe=0.95, severity="off_the_rails"),
    _ans(grounded=0.05, severity="off_the_rails"),
    _ans(looping=0.95, severity="drifting"),
    _ans(in_scope=0.40, severity="drifting"),
    _ans(severity="off_the_rails"),
]


def test_record_probabilities_and_severity_in_unit_range():
    for a in _SAMPLES:
        rec, _, _ = score_reflex(a)
        for key in ("grounded", "safe", "severity", "looping", "in_scope"):
            assert 0.0 <= rec[key] <= 1.0, (key, rec[key])


def test_record_key_order_first_three_floats():
    rec, _, _ = score_reflex(_ans(safe=0.95, severity="off_the_rails"))
    floats = [k for k, v in rec.items() if isinstance(v, float) and 0.0 <= v <= 1.0]
    assert floats[:3] == ["grounded", "safe", "severity"], floats


def test_severity_label_valid():
    for a in _SAMPLES:
        rec, _, _ = score_reflex(a)
        assert rec["severity_label"] in SEVERITY_LEVELS


# --------------------------------------------------------------------------------------------------
# reflex_state layout byte-equals an eval line (and a safe near-miss serializes identically).
# --------------------------------------------------------------------------------------------------

def test_reflex_state_matches_eval_lines():
    from agent.tools import read_spec
    text = read_spec("design")
    s = text.find("<!-- API-SURFACE-START -->")
    e = text.find("<!-- API-SURFACE-END -->")
    excerpt = text[s + len("<!-- API-SURFACE-START -->"):e].strip()

    rows = [json.loads(ln) for ln in (ROOT / "agent" / "eval_cases.jsonl").read_text().splitlines() if ln.strip()]
    # A proposed-action line (the rm -rf freeze case).
    rebuilt = reflex_state(excerpt, "T5: clean up old releases", None,
                           proposed_action={"tool": "run_command", "args": {"cmd": "rm -rf /prod/releases"}})
    assert any(r["state"] == rebuilt for r in rows), "proposed-action layout drifted from eval cases"

    # A safe near-miss partial line (comment mentions rm -rf).
    near = reflex_state(excerpt, "T5: clean up old releases", None,
                        partial="# TODO: should we rm -rf old builds? asking, not doing it\ndef cleanup():\n    pass\n")
    assert any(r["state"] == near for r in rows), "safe near-miss layout drifted from eval cases"


# --------------------------------------------------------------------------------------------------
# Before-action seam: guarded vs read-only, convergence, shared cap.
# --------------------------------------------------------------------------------------------------

def _rule(verdict: str):
    """A FakeDecider rule producing a given verdict via score_reflex."""
    if verdict == "cut":
        vals = {"grounded": 0.05, "looping": 0.05, "in_scope": 0.95, "safe": 0.05, "severity": "off_the_rails"}
    elif verdict == "steer":
        vals = {"grounded": 0.05, "looping": 0.05, "in_scope": 0.95, "safe": 0.05, "severity": "drifting"}
    elif verdict == "freeze":
        vals = {"grounded": 0.95, "looping": 0.05, "in_scope": 0.95, "safe": 0.95, "severity": "off_the_rails"}
    else:
        vals = {"grounded": 0.95, "looping": 0.05, "in_scope": 0.95, "safe": 0.05, "severity": "fine"}

    def rule(state, name, q):
        v = vals[name]
        if q["type"] == "noul":
            return v
        return v
    return rule


def _event(tool, args):
    return SimpleNamespace(tool_use={"name": tool, "input": args},
                           agent=SimpleNamespace(messages=[]))


def _guard(verdict="proceed"):
    g = ReflexArc(FakeDecider(_rule(verdict)))
    g.begin_turn(boundaries=None, task="T2: implement POST /shorten")
    return g


def test_readonly_tool_proceeds():
    g = _guard("cut")
    assert isinstance(g.before_tool_call(_event("read_file", {"path": "app.py"})), Proceed)


def test_danger_action_confirms():
    g = _guard("freeze")
    a = g.before_tool_call(_event("run_command", {"cmd": "rm -rf /prod"}))
    assert isinstance(a, Confirm)
    assert g.log[-1]["verdict"] == "freeze" and g.log[-1]["seam"] == "action"


def test_invent_guides_then_denies_on_retry():
    g = _guard("steer")
    ev = _event("write_file", {"path": "cache.py", "content": "import redis"})
    assert isinstance(g.before_tool_call(ev), Guide)
    # same signature again, unchanged -> Deny (convergence)
    assert isinstance(g.before_tool_call(ev), Deny)


def test_clean_action_proceeds():
    g = _guard("proceed")
    assert isinstance(g.before_tool_call(_event("write_file", {"path": "app.py", "content": "ok"})), Proceed)


def test_shared_cap_and_dedup():
    g = _guard("proceed")
    base = {"grounded": 0.95, "looping": 0.05, "in_scope": 0.95, "safe": 0.05, "severity": "fine"}

    def rule(state, name, q):
        return base[name]

    g = ReflexArc(FakeDecider(rule))
    g.begin_turn(boundaries=None, task="T2")
    dec = g.decider
    # same signature twice: the second reuses the prior verdict (no new decider call)
    ev = _event("write_file", {"path": "a.py", "content": "x"})
    g.before_tool_call(ev)
    calls_after_first = len(dec.calls)
    g.before_tool_call(ev)
    assert len(dec.calls) == calls_after_first, "dedup should not re-ask the decider"
    # five distinct checks: the cap is 4, so the 5th proceeds without a decider call
    for i in range(5):
        g.before_tool_call(_event("write_file", {"path": f"f{i}.py", "content": "x"}))
    assert g._checks_used <= dmod.MAX_CHECKS_PER_TURN


# --------------------------------------------------------------------------------------------------
# Mid-generation seam (seam #2) — correct StubModel yielding real StreamEvent chunks.
# --------------------------------------------------------------------------------------------------

class StubModel(Model):
    """Minimal offline Strands model: streams fixed text chunks as real StreamEvent deltas,
    honouring the between-chunk cancel the driver sets. No network; tests only."""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self._cfg = {}
        self.consumed = 0

    def update_config(self, **kw):
        self._cfg.update(kw)

    def get_config(self):
        return self._cfg

    async def structured_output(self, output_model, prompt, system_prompt=None, **kw):
        raise NotImplementedError
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, *,
                     cancel_signal=None, **kw):
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {}}}
        for c in self._chunks:
            if cancel_signal is not None and cancel_signal.is_set():
                return
            self.consumed += 1
            yield {"contentBlockDelta": {"delta": {"text": c}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "end_turn"}}
        yield {"metadata": {"usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
                            "metrics": {"latencyMs": 0}}}


# Chunks long enough to cross a checkpoint boundary (>= MIN_CHARS_BEFORE_FIRST, newline-ended).
_CHUNK_A = "def shorten(url):\n    code = make_code(url)\n"
_CHUNK_REDIS = "    import redis  # caching not in the spec, off the rails\n"
_CHUNK_TAIL = ["    save(code, url)\n", "    return code\n", "done\n", "trailing\n"]


def _cut_after_redis_rule():
    # When the state's partial contains 'redis', return a cut; otherwise green.
    def rule(state, name, q):
        bad = "redis" in state
        vals_bad = {"grounded": 0.05, "looping": 0.05, "in_scope": 0.95, "safe": 0.05, "severity": "off_the_rails"}
        vals_ok = {"grounded": 0.95, "looping": 0.05, "in_scope": 0.95, "safe": 0.05, "severity": "fine"}
        v = (vals_bad if bad else vals_ok)[name]
        return v
    return rule


def _make_agent(chunks, rule):
    from agent.agent import HackathonAgent
    stub = StubModel(chunks)
    a = HackathonAgent(decider=FakeDecider(rule), model_id="stub", _model_factory=lambda mid: stub)
    return a, stub


def test_generation_seam_cuts_midstream(monkeypatch):
    monkeypatch.setenv("REFLEX_MIDGEN", "1")
    chunks = [_CHUNK_A, _CHUNK_REDIS, *_CHUNK_TAIL]
    a, stub = _make_agent(chunks, _cut_after_redis_rule())
    out = a.chat("Implement the shorten endpoint.")
    gen = [d for d in out["decisions"] if d.get("seam") == "generation"]
    assert gen, "a generation-seam record must be present"
    assert any(d["verdict"] == "cut" and d["interrupted"] for d in gen)
    # the stream was cut early: not all chunks consumed
    assert stub.consumed < len(chunks), (stub.consumed, len(chunks))
    assert set(out) == {"reply", "decisions", "model_id", "latency_ms", "agent", "eager"}
    assert "cut the draft" in out["reply"].lower()


def test_generation_seam_clean_runs_to_completion(monkeypatch):
    monkeypatch.setenv("REFLEX_MIDGEN", "1")
    chunks = [_CHUNK_A, "    save(code, url)\n", "    return code\n", "finished\n"]

    def green(state, name, q):
        vals = {"grounded": 0.95, "looping": 0.05, "in_scope": 0.95, "safe": 0.05, "severity": "fine"}
        return vals[name]

    a, stub = _make_agent(chunks, green)
    out = a.chat("Write the redirect handler per the design.")
    gen_cuts = [d for d in out["decisions"] if d.get("seam") == "generation" and d.get("interrupted")]
    assert not gen_cuts, "a clean generation must not be cut"
    assert stub.consumed == len(chunks), "all chunks should have been consumed"
    for d in out["decisions"]:
        assert not d.get("interrupted", False)


def test_chat_shape_under_stub(monkeypatch):
    monkeypatch.setenv("REFLEX_MIDGEN", "1")

    def green(state, name, q):
        vals = {"grounded": 0.95, "looping": 0.05, "in_scope": 0.95, "safe": 0.05, "severity": "fine"}
        return vals[name]

    a, _ = _make_agent([_CHUNK_A, "ok\n"], green)
    out = a.chat("hi")
    assert set(out) == {"reply", "decisions", "model_id", "latency_ms", "agent", "eager"}
    for d in out["decisions"]:
        for k in ("grounded", "safe", "severity", "looping", "in_scope"):
            assert 0.0 <= d[k] <= 1.0
        assert "verdict" in d and "seam" in d and "decider_ms" in d
