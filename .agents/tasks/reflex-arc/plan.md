# Implementation Plan — Reflex Arc (`#guardrails`)

The approved design is `.agents/tasks/reflex-arc/design.md`; this plan turns it into build order.
Do not re-decide architecture. Every item leaves the repo buildable. All paths are relative to the
workspace root `/Users/madhumithaa/Downloads/Strands_hackathon`. Use the venv interpreter
`.venv/bin/python` and the kit commands (`./kit test`, `./kit run`, `./kit bench`, `./kit check`,
`./kit status`). Keep the credit line "Built with the AWS User Group Madurai Strands Decider
hackathon kit" in every generated file. Never commit `.env`.

Decisions already fixed by the design and honoured here (not re-opened): hosted ugmdu decider via
`decider_kit.Decider`; LLM = Amazon Bedrock Nova Pro via `decider_kit.llm.agent_model()`+Strands
`Agent` only (the `tests/test_llm_providers.py::test_no_direct_bedrock_runtime_calls` test must stay
green); one `Decider.ask` with five typed questions; two seams (before-action InterventionHandler +
mid-generation stream driver); `score_reflex` is the single pure verdict function reused by both
seams; `VERDICT_ACTION` is the single reflex-word→Strands-action map; severity normalized in exactly
one place.

Where the 6 review findings land (each is a hard acceptance criterion):
- MEDIUM-1 → item 3 (decision.py docstring: `REUSABLE DECISION PATTERN:` + the four grepped headings).
- MEDIUM-2 → item 3 (`SEVERITY_LEVELS` + one-line severity normalization) and item 10 (unit test).
- NIT-3 → item 4 (ReflexArc per-turn state attributes) and item 5 (driver assigns `last_result`).
- NIT-4 → item 4 (`_task_for` concrete; `(task not identified)` literal).
- NIT-5 → item 8 (demo beats: decisive verdict in first two decider calls).
- NIT-6 → item 7 (eval invariant: ≥24 rows, ≥12 test, yes&no in test split for all four nouls).

---

- [ ] 1. Create the fixed URL-shortener spec canon and machine-readable tasks under `agent/data/`.
      `requirements.md` (EARS: create short code, redirect, reject invalid/oversized, list links; NO
      caching/analytics/auth beyond one API key — stated explicitly). `design.md` with the ALLOWED
      API surface between literal markers `<!-- API-SURFACE-START -->` and `<!-- API-SURFACE-END -->`
      exactly as design §9 lists (files app.py/store.py/validate.py/config.py; `store.save/get/list_for`;
      `validate.is_valid_url/make_code`; endpoints `POST /shorten`,`GET /{code}`,`GET /links`;
      `config.BASE_URL/MAX_URL_LEN=2048/API_KEY`; explicit NON-features). `tasks.md` Kiro-style
      checkboxes. `tasks.json` = the 7-task list (T1..T7 with `id,title,spec_part,rig`) verbatim from
      design §9 so `decider_kit.data.load("tasks")` returns it. Delete the kit example data files
      (`agent/data/orders.json` and any other kit-example data) so only the new canon remains. Keep
      `agent/data/images/SOURCES.md` if present (unrelated). These files are deterministic/offline.
      Files: agent/data/spec/requirements.md, agent/data/spec/design.md, agent/data/spec/tasks.md,
      agent/data/tasks.json (and remove agent/data/orders.json)
      Verify: `.venv/bin/python -c "from decider_kit.data import load; t=load('tasks'); assert len(t)==7 and t[0]['id']=='T1', t; print('tasks ok')"`
      and `.venv/bin/python -c "import pathlib,re; d=pathlib.Path('agent/data/spec/design.md').read_text(); assert '<!-- API-SURFACE-START -->' in d and '<!-- API-SURFACE-END -->' in d; print('markers ok')"`.

- [ ] 2. Replace `agent/tools.py` with Strands `@tool` functions over a MOCKED in-memory filesystem
      and a MOCKED command runner — nothing ever touches the real FS or shell. Define a module-level
      `DATA = decider_kit.config.ROOT / "agent" / "data"` and a cached `read_spec(part)` using
      `Path.read_text()` (NOT `data.load`, which only reads .json/.csv — MEDIUM-2 of the first review
      round). Seed an in-memory dict FS with empty `app.py/store.py/validate.py/config.py`. Tools:
      `read_spec(part)` (ungated read-only `@tool`), `list_files()`, `read_file(path)`,
      `write_file(path, content)` (cap `MAX_FILE=20_000`), `edit_file(path, patch)`,
      `run_command(cmd)`, `delete_path(path)`. `run_command`/`delete_path` PARSE the command, record
      the intended effect, and return a simulated result; they contain a trivial inert safety net
      (never execute; a stray `rm -rf`/`/prod`/`push --force` is flagged in the mock return) but the
      BLOCKING decision is the reflex's, never a regex `if` here. Export `TOOLS = [...]`. Keep a
      one-line docstring on each tool.
      Files: agent/tools.py
      Verify: `.venv/bin/python -c "from agent.tools import TOOLS, read_spec; assert len(TOOLS)>=6; assert 'app.py' in read_spec('design'); print('tools ok')"`
      (no network, no real FS writes).

- [ ] 3. Replace `agent/decision.py` with the labelled pattern module: the top docstring, the
      constants, the five `QUESTIONS`, the state builder and the pure verdict function. This item
      implements MEDIUM-1 and MEDIUM-2.
      - Docstring MUST start with the literal `REUSABLE DECISION PATTERN:` and contain the four
        substrings `scripts/check_submission.py::check_pattern` greps case-insensitively:
        `What it does`, `Typed questions`, `Wiring`, and a reuse note containing `reuse` (use the kit
        example's docstring structure as the template; §3.4/§5). Record the final tuned threshold
        values here per design Part 12 (after item 11 tunes them, update this docstring).
      - `PATTERN_TAG = "#guardrails"`. NO `IS_KIT_EXAMPLE` anywhere. Exactly one `PATTERN_TAG`.
      - `SEVERITY_LEVELS = ['fine','drifting','off_the_rails']` defined ONCE (MEDIUM-2).
      - `QUESTIONS` = the five typed questions with the exact option descriptions in design §3.4
        (`grounded`,`looping`,`in_scope`,`safe` as `Decider.noul`; `severity` as
        `Decider.score(..., SEVERITY_LEVELS)`).
      - `VERDICT_ACTION = {"proceed": Proceed, "steer": Guide, "cut": Deny, "freeze": Confirm}` — the
        single reflex-word→Strands-action map (§3.3, NIT-2).
      - Thresholds as module constants: `YES=0.5, DANGER=0.5, UNSURE_LO=0.50, UNSURE_HI=0.70,
        CHECKPOINT_CHARS=240, MAX_CHECKS_PER_TURN=4, MIN_CHARS_BEFORE_FIRST=40, STATE_CODE_TAIL=1200`.
      - `reflex_state(spec_excerpt, current_task, boundaries, *, proposed_action=None, partial=None)`:
        builds the §3.2 layout byte-for-byte (fixed header; `--- SPEC EXCERPT ---`,
        `--- CURRENT TASK ---`, `--- USER BOUNDARIES ---` with `(none)` when empty,
        `--- WHAT THE AGENT IS DOING ---` with exactly one of `proposed action: <tool> arguments: <json>`
        or `partial code so far:\n<tail>`; partial truncated to `STATE_CODE_TAIL`). Current task
        renders the literal `(task not identified)` when none (NIT-4, co-ordinated with item 4).
      - `score_reflex(ans) -> (record, verdict, kind)`: a PURE function (no decider call, no logging)
        implementing the §3.5 threshold chain exactly, including: `severity` read via `.label`/`.score`
        only (never `.p_yes`); `severity = round(ans['severity'].score / (len(SEVERITY_LEVELS)-1), 3)`
        so it is always in [0,1] (MEDIUM-2 single site); the record built in the §3.3 KEY ORDER with
        the first three in-[0,1] floats being exactly `grounded, safe, severity` (MEDIUM-5), then
        `looping, in_scope, confidence`, then non-float metadata `severity_label, tool, interrupted,
        decider_ms`; `_broken`, `_any_broken` (four nouls only — severity excluded, MEDIUM-D),
        `_driving_question`/`_driving_conf` (return a noul's `.confidence` only), `_one_line_fix`,
        `_action_kwargs`. Decision order per §3.5 rules 1–5 (first match wins).
      Files: agent/decision.py
      Verify: `.venv/bin/python -c "import ast; d=ast.get_docstring(ast.parse(open('agent/decision.py').read())); assert d.startswith('REUSABLE DECISION PATTERN:'); [None for s in ('what it does','typed questions','wiring','reuse') if s in d.lower()]; assert all(s in d.lower() for s in ('what it does','typed questions','wiring','reuse')); print('docstring ok')"`
      and `.venv/bin/python -c "from agent.decision import QUESTIONS, PATTERN_TAG, SEVERITY_LEVELS, VERDICT_ACTION; assert PATTERN_TAG=='#guardrails'; assert set(QUESTIONS)=={'grounded','looping','in_scope','safe','severity'}; assert SEVERITY_LEVELS==['fine','drifting','off_the_rails']; print('consts ok')"`
      and `.venv/bin/python scripts/check_submission.py --only pattern` reports PASS for pattern
      labelled / the four section notes / PATTERN_TAG / one pattern / QUESTIONS defined / "your own
      agent" (no IS_KIT_EXAMPLE).

- [ ] 4. Add the `ReflexArc(InterventionHandler)` class and its per-turn state to `agent/decision.py`
      (seam #1 + the shared scorer entry points). This implements NIT-3 (state enumeration) and NIT-4.
      - `name = "reflex-arc"`; `GUARDED_TOOLS = {"write_file","edit_file","run_command","delete_path"}`;
        read-only tools (`read_spec`,`read_file`,`list_files`) → `Proceed`.
      - Per-turn state attributes, enumerated and each with its setter (NIT-3): `_guided: set[str]`,
        `_scored: dict[str,str]` (sig→verdict), `_checks_used: int`, `turn_started: float`,
        `last_result` (final agent result, set by the driver — item 5), `last_generation_note`
        (set by `reflex_on_partial` on cut/freeze). `begin_turn(boundaries, task)` resets `_guided`,
        `_scored`, `_checks_used=0`, sets `turn_started=time.time()`, stores `boundaries` and `task`,
        clears `last_result`/`last_generation_note`.
      - `_task_for(message)` CONCRETE (NIT-4): prefer a task id carried on the message/turn if present;
        else keyword-match `message` against `tasks.json` titles; else the first incomplete task; if
        none identified, return a sentinel that makes `reflex_state` render `(task not identified)`.
      - `spec_excerpt_for(task)`: returns the marker-delimited API-surface slice of design.md for a
        design-part task, or the relevant requirements block for a requirements-part task (loaded once,
        cached). Deterministic and byte-identical to the eval-case excerpts.
      - `before_invocation(event)`: clears per-turn state via `begin_turn`; optional input check OFF by
        default (`check_inputs=False`); when on, 2-question injection/scope call logging `seam="input"`,
        returns `Deny` on confident injection/off-task else `Proceed` (NEVER `Confirm` — SDK type;
        MEDIUM-3).
      - `before_tool_call(event)`: non-guarded → `Proceed`; `_checks_used >= MAX_CHECKS_PER_TURN` →
        `Proceed` (logged skip); build `reflex_state(..., proposed_action=...)`; dedup by
        `sig=f"{name}:{json.dumps(args,sort_keys=True)}"` against `_scored` (reuse prior verdict, no new
        decider call); else one `decider.ask`, `_checks_used+=1`, `_scored[sig]=verdict`; map via
        `score_reflex`+`VERDICT_ACTION`; append one log record (`seam="action"`, `tool=name`);
        convergence (FR7): `sig in _guided` → `Deny("Already steered on this; cutting.")`, else on a
        `steer` add `sig` to `_guided`.
      - `reflex_on_partial(text) -> verdict`: build `reflex_state(..., partial=text)`, one
        `decider.ask`, `_checks_used+=1`, run `score_reflex`, append log record (`seam="generation"`),
        set `last_generation_note` on cut/freeze (cut vs held wording per §4.2 step 3), handle
        mid-stream steer escalation via `_guided` over the drifting chunk hash. Returns the verdict word.
      - `at_generation_checkpoint(text) -> bool`: the §4.2 step 2 boundary rule gated by
        `_checks_used < MAX_CHECKS_PER_TURN` and `MIN_CHARS_BEFORE_FIRST`.
      - Fail-safe (design Part 10): wrap each seam's decider call; on `DeciderError` log a
        `{"verdict":"freeze","error":"decider_unavailable","decider_ms":...}` record and fail safe
        (action seam → `Confirm`; generation seam → held note; input seam → `Deny`). Retry transient
        503s with short backoff (a couple of attempts) before giving up — do not crash the turn on a
        transient hosted 503.
      Files: agent/decision.py
      Verify: `.venv/bin/python -c "from agent.decision import ReflexArc, GUARDED_TOOLS; from tests.fakes import FakeDecider; g=ReflexArc(FakeDecider()); assert 'run_command' in GUARDED_TOOLS and hasattr(g,'before_tool_call') and hasattr(g,'reflex_on_partial') and hasattr(g,'at_generation_checkpoint'); print('ReflexArc ok')"`
      (run from repo root so `tests` is importable, or use the full test in item 10).

- [ ] 5. Replace `agent/agent.py` with the streaming `HackathonAgent` that wires both seams and keeps
      every contract (§3.1, §3.1.1, §4.2). This implements the NIT-3 driver assignment of `last_result`.
      - `NAME` (str), `SYSTEM_PROMPT`, `EAGER_PROMPT` (eager tempts the mistakes the demo needs).
      - Module-level `_run_sync(coro)` bridge exactly as §3.1.1 (`get_running_loop` → `asyncio.run`,
        else a one-shot worker-thread loop).
      - `__init__(self, decider=None, model_id=None, eager=None, *, _model_factory=agent_model)`:
        three public params unchanged; `_model_factory` keyword-only test seam defaulted to
        `agent_model`. `eager` honoured via `DEMO_EAGER`. `model_id` defaults to `default_model_id()`.
      - `_session(session_id) -> (Agent, ReflexArc, AgentCoreMemoryStore)`: builds
        `model = self._model_factory(self.model_id)` (NEVER `agent_model(...)` directly — NIT-F),
        `Agent(model=model, tools=TOOLS, system_prompt=..., interventions=[guard], callback_handler=None)`
        (the `interventions=[guard]` is what activates seam #1 — MEDIUM-B; NO `invocation_state` reflex
        key), and an `AgentCoreMemoryStore(actor_id=..., session_id=session_id, name="reflexboundaries")`.
        Cache guard/store per session.
      - `chat(self, message, session_id="default", images=None) -> dict`: tolerant `images=None`,
        IGNORED (Reflex Arc is text-only — MEDIUM-C); empty message → a prompt reply, no decider call;
        otherwise `return _run_sync(self._chat_async(message, session_id))`.
      - `_chat_async(message, session_id)`: get `(agent, guard, store)`; `guard.begin_turn(
        boundaries=store.candidates(message), task=guard._task_for(message))`; if the message states a
        boundary, `store.save(text, role="USER")`; create `cancel = threading.Event()`; iterate
        `agent.stream_async(message, cancel_signal=cancel)`; accumulate `event["data"]` deltas; at
        `guard.at_generation_checkpoint(text)` call `guard.reflex_on_partial(text)` and on
        `cut`/`freeze` set `cancel`, `agent.cancel()`, `interrupted=True`, break; when the loop
        completes without interrupt, assign `guard.last_result` from the completed stream result
        (NIT-3); return `self._finish(agent, guard, partial, interrupted)`.
      - `_finish(agent, guard, partial, interrupted)` exactly per §4.2 (MEDIUM-E): if `interrupted`,
        `reply = guard.last_generation_note` (never through `strip_thinking`); else
        `reply = strip_thinking(str(guard.last_result or ""))` (turns an action-seam `DENIED: x` into
        `x`). Return the six-key dict `{reply, decisions=list(guard.log), model_id, latency_ms=round(
        (time.time()-guard.turn_started)*1000), agent=NAME, eager=self.eager}`.
      - `REFLEX_MIDGEN = os.environ.get("REFLEX_MIDGEN","1")` kill-switch: when "0", `_chat_async`
        falls back to a blocking `agent(message)` call (seam #1 only) — NFR2. Mark here that this is
        where the §4.3 documented degradation (post-chunk abandonment) is dropped in if the online
        smoke test (item 13) shows mid-stream cancellation does not stop Nova promptly; document that
        choice in AGENT.md if taken.
      - Keep the `if __name__ == "__main__":` CLI so `./kit run` works.
      Files: agent/agent.py
      Verify: `.venv/bin/python scripts/check_submission.py --only agent` reports PASS for "LLM through
      Strands Agents", "Strands Decider in the agent's path"; and
      `.venv/bin/python -m pytest -q tests/test_agent_contract.py` passes.

- [ ] 6. Replace `agent/features.yaml` for AgentCore Memory ON, Gateway OFF, matching
      `decider_kit/agentcore.py` + `scripts/deploy.py` schema. `memory.enabled: true`,
      `name: reflexboundaries` (→ `MEMORY_REFLEXBOUNDARIES_ID`), `strategies: [USER_PREFERENCE, SEMANTIC]`,
      `expiry_days: 30`; `gateway.enabled: false`, `name: tools`, `authorizer: AWS_IAM`, `targets: []`.
      Keep the credit/explanatory comments.
      Files: agent/features.yaml
      Verify: `.venv/bin/python -c "import yaml; f=yaml.safe_load(open('agent/features.yaml')); assert f['memory']['enabled'] is True and f['memory']['name']=='reflexboundaries' and f['gateway']['enabled'] is False; print('features ok')"`
      and `.venv/bin/python -c "from decider_kit.agentcore import AgentCoreMemoryStore; s=AgentCoreMemoryStore(name='reflexboundaries'); s.save('never edit /prod'); assert 'never edit /prod' in s.candidates('prod'); print('memory store ok')"`.

- [ ] 7. Replace `agent/eval_cases.jsonl` with ≥26 cases whose `state` is built by the SAME
      `reflex_state` layout (§3.2) the wiring sends at runtime, covering the §6 coverage matrix and
      near-misses. Each line: `{"state","expected":{grounded,looping,in_scope,safe,severity},"split"}`
      with noul labels `"yes"/"no"` and severity one of `fine|drifting|off_the_rails`. Include the
      per-branch rows design §3.5/§6 enumerate, both `proposed action:` and `partial code so far:`
      variants, the safe near-miss `# TODO: should we rm -rf old builds?` (`safe:no`), a GOOD on-spec
      case that must NOT interrupt, a question-about-deletion case (`safe:no`), the boundary-memory
      pair, and the lone-severity row (all four nouls healthy + `severity:drifting` → proceed).
      Generate states programmatically by importing `reflex_state` so they are byte-identical to
      runtime (a small throwaway generator script is fine; do not leave it in `agent/`).
      HARD INVARIANT (NIT-6, enforced by `scripts/check_submission.py`): ≥24 rows, ≥12 `split:"test"`,
      and for EACH of the four nouls (`grounded,looping,in_scope,safe`) both `"yes"` and `"no"` appear
      among the `test`-split rows. Tune only on `tune`; report `test`.
      Files: agent/eval_cases.jsonl
      Verify: run this script (real newlines, via a heredoc or a temp file) and expect
      `eval invariant ok ...`:
      ```python
      import json
      rows = [json.loads(l) for l in open('agent/eval_cases.jsonl') if l.strip()]
      t = [r for r in rows if r.get('split', 'test') == 'test']
      assert len(rows) >= 24 and len(t) >= 12, (len(rows), len(t))
      for q in ('grounded', 'looping', 'in_scope', 'safe'):
          vals = {r['expected'].get(q) for r in t if q in r['expected']}
          assert 'yes' in vals and 'no' in vals, (q, vals)
      print('eval invariant ok', len(rows), len(t))
      ```
      then `.venv/bin/python -m pytest -q tests/test_agent_contract.py::test_eval_cases_match_questions`
      passes.

- [ ] 8. Replace `agent/demo_script.yaml` with the six beats (§7), matching `scripts/make_video.py`
      schema (`title, pitch, features[], eager: true, intro, intro_normal, turns[]{say,narrate}, outro`).
      Beats: (1) hallucination → CUT, (2) `rm -rf /prod` → FREEZE/ASK (driven as a `run_command` tool
      call so the action seam's real `Confirm` fires), (3) infinite loop → CUT, (4) scope drift →
      STEER, (5) honest GOOD non-event → no interrupt, (6) remembered-boundary catch via Memory (two
      `turns[]`: set boundary, then violate). NIT-5: author each beat so the DECISIVE reflex verdict
      is among the FIRST TWO decider calls of that turn (make_video narrates `decisions[:2]`). No
      numbers in `intro/intro_normal/outro/pitch`; no measurements in any `narrate` (make_video
      `sys.exit`s otherwise). Whole video < 3 min. Keep narration neutral.
      Files: agent/demo_script.yaml
      Verify: run this script (real newlines) and expect `demo script ok`; then the deeper proof is
      that `./kit video` does not `sys.exit` on the number/measurement guards (checked online at the
      video stage):
      ```python
      import re, yaml
      s = yaml.safe_load(open('agent/demo_script.yaml'))
      assert s['eager'] is True
      assert len(s['turns']) >= 6
      for k in ('intro', 'intro_normal', 'outro', 'pitch'):
          assert not re.search(r'\d', str(s.get(k) or '')), k
      for t in s['turns']:
          assert not re.search(r'\d+\s*(s|ms|seconds|%|percent)\b', str(t.get('narrate', ''))), 'measure'
      print('demo script ok')
      ```

- [ ] 9. Replace `agent/AGENT.md` with the reflex-first, in-flight framing in plain words: what Reflex
      Arc is (a coding agent with a nervous system; Bedrock Nova Pro writes, Strands Decider 2B is the
      fast in-flight reflex), who it is for (developers handing an AI a spec), the features, the ONE
      decision (`#guardrails`), that it is text-only and ignores any attached images (MEDIUM-C), and
      that Memory stores user boundaries. Keep the kit credit line. If item 5's online smoke test
      forces the §4.3 post-chunk degradation, note the exact honest wording here.
      Files: agent/AGENT.md
      Verify: `.venv/bin/python -c "t=open('agent/AGENT.md').read(); assert 'AWS User Group Madurai' in t and 'reflex' in t.lower(); print('AGENT.md ok')"`.

- [ ] 10. Create `tests/test_reflex_arc.py` — offline wiring tests with `FakeDecider` and a correct
      `StubModel`. Covers the review findings' unit assertions (MEDIUM-2, NIT-3 behaviour) and design
      Part 11. The `StubModel` MUST subclass `strands.models.model.Model`, implement all four abstract
      methods (`update_config`, `get_config`, `structured_output`, `stream`), and have `stream` yield
      real `StreamEvent` chunks (`messageStart` → one `contentBlockDelta{delta:{text}}` per chunk →
      `contentBlockStop` → `messageStop{stopReason}` → `metadata{usage,metrics}`) while honouring
      `cancel_signal` between chunks (design §4.3.1 / HIGH-A verbatim; the installed SDK confirmed the
      four abstract methods and these event types). Inject it via the `_model_factory` seam. Tests:
      - `score_reflex` truth table: one assertion per §3.5 branch (confident-danger→freeze;
        borderline-danger conf 0.55→freeze; borderline-grounded conf 0.60→freeze;
        grounded-broken+off_the_rails→cut; in_scope-broken+off_the_rails→cut; drifting+looping→steer;
        drifting+grounded→steer; all-green-fine→proceed; all-four-nouls-healthy+severity=drifting→proceed).
      - MEDIUM-2 asserts: for every built record `0.0 <= record['severity'] <= 1.0` AND all five
        probability fields (`grounded,safe,severity,looping,in_scope`) are within [0,1].
      - MEDIUM-5 record key order: first three in-[0,1] float fields are exactly
        `("grounded","safe","severity")`.
      - severity-label validity: every record's `severity_label` ∈ SEVERITY_LEVELS.
      - `reflex_state` layout byte-equals a known `eval_cases.jsonl` line (incl. a `safe` near-miss).
      - `before_tool_call`: guarded vs read-only; convergence (steer→Deny on unchanged retry);
        shared `_scored`/`_checks_used` cap (same sig not re-asked; the 5th distinct check Proceeds).
      - danger→Confirm; invent→Guide then Deny; clean→Proceed (assert on Strands action TYPES).
      - generation seam offline (`REFLEX_MIDGEN=1`): FakeDecider scripted to `cut` after the "redis"
        chunk ⇒ a `seam="generation"` record with `verdict=="cut"` and `interrupted==True`, the stream
        cut early (not all chunks consumed), and `chat()` returns the six-key dict with `reply` = the
        cut note. Twin all-green test: clean full generation, NO `seam="generation"` cut record,
        `interrupted` absent/False (AC6).
      - `chat("hi")` under the stub returns `{reply,decisions,model_id,latency_ms,agent,eager}` and
        each decision has the five probabilities + `verdict` + `seam` + `decider_ms`.
      Files: tests/test_reflex_arc.py
      Verify: `.venv/bin/python -m pytest -q tests/test_reflex_arc.py` — all pass offline (no network).

- [ ] 11. Edit `demo/static/index.html` (in-scope bug fix only, HIGH-3): add three CSS rules so the
      reflex verdict badges are coloured like the existing palette — `.steer{color:var(--amber);
      border-color:var(--amber);}`, `.cut{color:var(--red);border-color:var(--red);}`,
      `.freeze{color:var(--blue);border-color:var(--blue);}` next to the existing `.proceed/.guide/...`
      rules (lines 28–29). Change nothing else; keep the credit line.
      Files: demo/static/index.html
      Verify: `.venv/bin/python -c "t=open('demo/static/index.html').read(); assert '.steer{' in t.replace(' ','') or '.steer {' in t; assert '.cut{' in t.replace(' ','') or '.cut {' in t; assert '.freeze{' in t.replace(' ','') or '.freeze {' in t; assert 'AWS User Group Madurai' in t; print('css ok')"`.

- [ ] 12. Run the full offline test suite and a scripted conversation. All of items 1–11 must be in
      place. This is the no-direct-Bedrock gate and the whole-contract gate.
      Files: (none — verification step)
      Verify: `./kit test` is green (includes `tests/test_llm_providers.py::test_no_direct_bedrock_runtime_calls`,
      the contract tests, and `tests/test_reflex_arc.py`); then `REFLEX_MIDGEN=1 ./kit run "Implement the shorten endpoint."`
      prints a `chat()` dict in which the reflex visibly fires on the rigged turn (a decision record
      with a non-`proceed` `verdict`). If `./kit run` cannot reach the hosted decider (transient 503),
      re-run after the short backoff; a hard decider outage must surface as the documented fail-safe
      record, not a crash.

- [ ] 13. (Online, needs AWS + hosted decider) Record the real decider numbers and prove the
      mid-generation seam against live Nova. Run `./kit bench --split tune` first (diagnose misses,
      sharpen option descriptions / thresholds only against `tune`, and write the final tuned
      threshold values into `agent/decision.py`'s docstring per Part 12), THEN `./kit bench --split
      test` to produce the reported numbers in `submission/bench/`. Run the one online smoke test
      (`REFLEX_MIDGEN=1` against real Nova) that asserts a `seam="generation"` record appears and, when
      cancellation works, `interrupted=True`; if mid-stream cancellation does not stop Nova promptly,
      flip `_chat_async` to the §4.3 post-chunk abandonment variant and document it in `AGENT.md`
      (item 5 marks this fallback point). Numbers in the article/README/video must all come from these
      real runs.
      Files: submission/bench/results.json (generated), agent/decision.py (final thresholds in docstring),
      possibly agent/agent.py + agent/AGENT.md (only if the degradation fallback is taken)
      Verify: `./kit bench --split test` writes `submission/bench/results.json` with real
      `summary.decider` and `summary.llm` entries; `./kit test` still green after any threshold/doc edit.

- [ ] 14. Run the submission checks and status. `./kit check` must no longer FAIL on "kit example
      still present" (pattern checks PASS, QUESTIONS defined, LLM-through-Strands PASS, labelled eval
      cases PASS). `./kit status` reflects the new agent. Remaining WARN/FAIL items tied to later
      workflow stages (deploy, video, article, publish) are expected and handled downstream — this
      item only requires that the agent/pattern/eval/agent-wiring checks pass.
      Files: (none — verification step)
      Verify: `./kit check` shows PASS for pattern labelled, the four pattern-note sections, PATTERN_TAG,
      one decision pattern, QUESTIONS defined, "your own agent" (kit example removed), LLM through
      Strands Agents, Strands Decider in the agent's path, and labelled eval cases; `./kit status` runs
      clean.

---

## Notes / assumptions (made to avoid stalling)

- The eval-case states are generated by importing `reflex_state` so they stay byte-identical to the
  runtime layout; the generator is a throwaway (do not commit it under `agent/`). This is the only
  reliable way to satisfy both `test_eval_cases_match_questions` and the `reflex_state`-layout unit
  test.
- `./kit run` reaches the hosted ugmdu decider (the user set `DECIDER_MODE=ugmdu` and a key in `.env`).
  Item 12's offline `./kit test` uses `FakeDecider`+`StubModel` only, so it never needs the network;
  item 13 is the only step that touches live Nova and the hosted decider for reported numbers.
- The single genuinely unmeasurable item (design Part 12 #1) — whether Nova streams `data` deltas
  finely enough for a dramatic mid-sentence cut — is resolved at item 13 by the online smoke test and
  the documented `REFLEX_MIDGEN` kill-switch + post-chunk degradation; all FRs hold either way, and
  seam #1 (before-action) never regresses.

Built with the AWS User Group Madurai Strands Decider hackathon kit.
