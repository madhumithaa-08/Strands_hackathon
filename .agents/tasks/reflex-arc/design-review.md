# Design review — Reflex Arc (`#guardrails`)

Reviewer: fresh design-review pass (no prior-authoring context). Scope: judge whether
`/.agents/tasks/reflex-arc/design.md` is ready to implement against the AWS User Group Madurai
Strands Decider kit contracts. I read the design in full and verified its load-bearing claims
against the actual source in the repo and the installed Strands SDK. I did not run builds or tests.

## Summary

This is a strong, unusually rigorous design that has already survived two prior review rounds. The
hard contracts it depends on are, in almost every case, verified correct against real source:

- the decider answer-object facts (`.p_yes`, `.yes`, `.confidence == max(p,1-p)`, score has **no**
  `.p_yes`, score read via `.label`/`.score`) — correct against `decider_kit/client.py`;
- the Strands intervention return types (`before_invocation` = `Proceed|Deny|Guide|Transform`, no
  `Confirm`; `before_tool_call` adds `Confirm`) — correct against the installed SDK;
- the streaming API (`Agent.stream_async(..., cancel_signal=...)`, `data` text-delta events,
  `Agent.cancel()` → `stop_reason="cancelled"`) and the `Model` ABC (exactly four abstract methods
  `update_config`/`get_config`/`structured_output`/`stream`, and the `StreamEvent` chunk shapes) —
  all correct;
- the consumer contracts (`deploy/app/agent/main.py` calling `chat(..., images=...)`,
  `demo/server.py`'s `inspect.signature` probe and sync route, `make_video.facts_for` first-three
  floats + `verdict` + `decider_ms`, `strip_thinking` stripping `DENIED:`, `AgentCoreMemoryStore`
  API, `data.load` reading only json/csv) — all correct;
- the submission checks (`check_submission.check_pattern`/`check_agent`, `inspect_agent`) — mostly
  satisfied, with ONE gap flagged below.

The findings below are few and specific. They are blocking because the design's own acceptance
criteria (AC2: "`./kit check` PASSES") and contract claims depend on them, and because two eval/data
points are under-specified in a way that would let an implementer diverge silently.

Verdict: **CHANGES_REQUESTED** (2 MEDIUM, several NITs; no HIGH).

---

## Findings

### 1. MEDIUM — `decision.py` docstring section headers are a hard `./kit check` requirement the design never pins

`scripts/check_submission.py::check_pattern` does more than require the docstring to **start** with
`REUSABLE DECISION PATTERN:`. It also fails if the docstring does not contain each of these
section markers (case-insensitive substring match, line 38–40):

```python
for sec in ("What it does", "Typed questions", "Wiring", "reuse"):
    if sec.lower() not in doc.lower():
        res("FAIL", f"pattern note: '{sec}' section", ...)
```

The design's AC1/AC2 claim `./kit check` PASSES the pattern checks, and §5 describes the docstring
only as "`REUSABLE DECISION PATTERN:` docstring". It never states that the rewritten docstring MUST
keep the four section headers. An implementer who writes a fresh Reflex-Arc docstring without the
literal words "What it does", "Typed questions", "Wiring", and "reuse" (or "how to reuse") will make
`./kit check` FAIL the pattern gate, contradicting AC2.

**Fix:** add an explicit contract line to §3.4/§5: the `decision.py` module docstring MUST start
with `REUSABLE DECISION PATTERN:` AND contain the four section headings the kit checker greps for —
`What it does`, `Typed questions` (and options), `Wiring`, and a reuse note (the substring `reuse`).
Spell them out so the implementer cannot drop one. (The current kit example's docstring is a valid
template; the rewrite must preserve these four headings.)

### 2. MEDIUM — `severity` normalization to `[0,1]` is asserted but the construction is not pinned, and a 3-level score makes `severity=1.0` a boundary value make_video includes

§3.3 says `"severity": float  # 0..1 = score/2`. With the three levels
`["fine","drifting","off_the_rails"]`, `.score` is the expected level in `0..n-1 = 0..2`, so
`score/2 ∈ [0,1]`. That is correct *only* if `severity` is always computed as `ans["severity"].score / 2`
and the question always has exactly three levels. The design states the value but never names the
single place that computes it, and §3.5 reads severity via `.label`/`.score` for the verdict while
§3.3 stores a *different* derived float — leaving room for an implementer to store
`.score` (0..2, out of `[0,1]`) or `max(probabilities)` (a confidence, not a severity) by mistake.
Either mistake silently breaks two contracts at once: the "all five probabilities in 0..1" claim
(AC3) and the `make_video` narration (a value >1 is filtered out of the first-three floats, so the
FREEZE beat could again omit the severity signal that MEDIUM-5 was meant to guarantee).

**Fix:** pin it in one place. In §3.3 state: `severity = round(ans["severity"].score / (len(SEVERITY_LEVELS) - 1), 3)`
with `SEVERITY_LEVELS = ["fine","drifting","off_the_rails"]` defined once in `decision.py`, and add
a unit assertion that `0.0 <= record["severity"] <= 1.0` for every built record (the §11
"record key order" test already inspects the first three floats; extend it to assert the range). If
the level count ever changes, the divisor follows automatically.

### 3. NIT — `_finish` depends on new guard attributes (`last_result`, `last_generation_note`, `turn_started`, `begin_turn`) that are referenced but never listed as part of the `ReflexArc` contract

§4.2 `_finish` reads `guard.last_result`, `guard.last_generation_note`, `guard.turn_started`, and
`guard.log`, and the driver calls `guard.begin_turn(...)`, `guard.at_generation_checkpoint(...)`,
`guard.reflex_on_partial(...)`. These are coherent and internally consistent, but they are
introduced inline rather than enumerated, so an implementer could miss initializing one (e.g.
`turn_started` must be set in `begin_turn`, and `last_result` must be assigned by the driver after
the stream loop when not interrupted — `_finish` reads it but the driver snippet shows no
`guard.last_result = <result>` assignment).

**Fix:** add a short "`ReflexArc` per-turn state" list to §3.5/§4.1 enumerating every attribute and
who sets it: `_guided`, `_scored`, `_checks_used`, `turn_started`, `last_result`,
`last_generation_note`, and the methods `begin_turn`, `before_invocation`, `before_tool_call`,
`at_generation_checkpoint`, `reflex_on_partial`, `score_reflex`. Explicitly note that the driver
assigns `guard.last_result` from the completed `stream_async` result when `interrupted` is False.

### 4. NIT — the design does not state how the agent knows "the CURRENT TASK" at runtime for a free-form `chat()` message

§3.2's state has a mandatory `--- CURRENT TASK ---` section, and §4.2 calls
`guard.begin_turn(..., task=self._task_for(message))` and §4.1 references
`spec_excerpt_for(task)` / `current_task`. But `_task_for(message)` is never defined. In the demo
each beat maps to a rigged task (`tasks.json`), yet a real user message ("Implement the shorten
endpoint") has no task id attached. If `_task_for` guesses wrong, the `grounded`/`in_scope`
questions compare against the wrong spec slice and the decision is garbage — a correctness gap, not
just cosmetics.

**Fix:** specify `_task_for(message)` concretely: e.g. default to the first incomplete task in
`tasks.json`, or match the message against task titles with a simple keyword/substring heuristic,
or (cleanest for the demo) carry the task id in the demo turns and default to `T?`/"(unspecified
task)" otherwise — and when the task is unknown, put a literal `(task not identified)` in the
`--- CURRENT TASK ---` section so the layout stays stable and the decider is not misled. State
which rule is chosen.

### 5. NIT — `make_video.facts_for` only narrates the first **two** decisions per turn; a turn with 3–4 reflex checks will not narrate all of them

Verified at `scripts/make_video.py:89` (`for d in ds[:2]`). The design fires up to
`MAX_CHECKS_PER_TURN = 4` reflex checks in a turn and surfaces them all in `decisions`. That is
fine for the UI and the log, but the video narration will only mention the first two. For the demo
beats this is acceptable (each beat is built so the decisive verdict is among the first checks), but
the design should acknowledge it so beats are authored with the decisive check first.

**Fix:** add a one-line note to §7: each demo beat must be constructed so the decisive reflex
verdict (CUT/FREEZE/STEER) is among the first two decider calls of the turn, since `make_video`
narrates only `decisions[:2]`.

### 6. NIT — eval-case count PASS bar vs. the design's "≥24 / ≥12" wording

`check_submission` reports PASS only when `n >= 24 and nt >= 12`, else WARN (not FAIL). The design
targets "≥24 (≥12 test)" and the coverage matrix sums to "≥26, ~13 test", which clears the PASS
bar — good. No change strictly required, but the matrix minimums should be counted explicitly:
the listed buckets (4+2+3+3+4+3+2+4+2+1 = 28 cases) must each hit their stated minimum AND the
`split` assignment must put ≥12 in `test` with balanced labels per question. 

**Fix:** add a one-line invariant to §6: "the generated file MUST contain ≥24 rows with ≥12
`split:"test"`, and for each of the four nouls both `yes` and `no` appear in the test split" so a
thin or label-skewed generation is caught before `./kit bench`.

---

## Verified assumptions (checked against real source)

1. **Decider answer-object facts (§3.5).** `decider_kit/client.py::Decision`: noul has `p_yes`,
   `yes = p_yes>=0.5`, `confidence = max(p,1-p)`; score has NO `p_yes`, only `score`, `label`,
   `probabilities`, `confidence = max(probabilities.values())`. The design's "read score via
   `.label`/`.score`, never `.p_yes`; confidence is `answer.confidence`" is exactly right.
2. **Intervention return types (§4.1, MEDIUM-3).** `strands/interventions/handler.py`:
   `before_invocation -> Proceed|Deny|Guide|Transform` (no `Confirm`); `before_tool_call` adds
   `Confirm`. The design's input-seam `Deny`/`Proceed`-only handling is correct.
3. **Streaming + cancel (§4.2).** `strands/agent/agent.py`: `stream_async(prompt, *, invocation_state,
   cancel_signal: threading.Event|None, ...)`; `cancel()` returns `stop_reason="cancelled"`; the
   `if "data" in event` idiom is the docstring example (lines 1361–1363), and `data` is the real
   contract — `TextStreamEvent` (`strands/types/_events.py:154`) emits `{"data": text, "delta": ...}`.
   NIT-1's correction is accurate.
4. **`Model` ABC + StreamEvent shapes (§4.3.1, HIGH-A).** `strands/models/model.py`: exactly four
   abstract methods (`update_config`, `get_config`, `structured_output`, `stream`); `stream`
   signature matches the stub (`messages, tool_specs=None, system_prompt=None, *, tool_choice,
   system_prompt_content, invocation_state, cancel_signal, agent_metadata, **kwargs`).
   `strands/types/streaming.py` confirms `MessageStartEvent{role}`,
   `ContentBlockDeltaEvent{delta:{text}}`, `ContentBlockStopEvent`, `MessageStopEvent{stopReason}`,
   `MetadataEvent{usage,metrics}`. `event_loop/streaming.py::process_stream` dispatches on those
   chunk keys, re-checks `cancel_signal` between chunks (lines 463, 502), and
   `handle_content_block_delta` produces the `data` text event. The corrected StubModel is
   implementable as written; an empty `contentBlockStart{start:{}}` is tolerated
   (`handle_content_block_start` returns `{}` when no `toolUse`).
5. **Deploy entrypoint (§3.1, MEDIUM-C).** `deploy/app/agent/main.py` calls
   `_agent.chat(prompt, session, images=images) if images else _agent.chat(prompt, session)` and
   adds `served_by`. Keeping a tolerant `images=None` that is ignored is correct and necessary.
6. **Demo server (§3.1.1).** `demo/server.py` `@app.post("/api/chat")` is a sync `def` (threadpool,
   no running loop — the `_run_sync` `asyncio.run` normal path holds); it probes
   `inspect.signature(a.chat)` for `images` and otherwise calls `a.chat(message, session_id)`. May
   add `served_by`.
7. **make_video (§3.3, MEDIUM-5).** `facts_for` takes the first three `isinstance(float) and 0<=v<=1`
   fields by insertion order, plus `verdict` and `decider_ms`. With the blessed key order
   `grounded, safe, severity` first (and `interrupted` being a `bool`, which is NOT caught by
   `isinstance(v, float)`), the safe/severity signal is narrated. Correct. Number/measurement guards
   at lines 235–241 match §7's rules.
8. **strip_thinking (§4.2).** `decider_kit/llm.py:170` strips `<thinking>/<think>` and
   `re.sub(r"^DENIED:\s*", "", text)` — the `_finish` claim about turning an action `Deny` into a
   clean reply is correct, and routing a generation note around `strip_thinking` is the right call.
9. **features.yaml schema (§8).** `agent/features.yaml` + `decider_kit/agentcore.py`:
   `memory.{enabled,name,strategies,expiry_days}`, `gateway.{enabled,name,authorizer,targets}`.
   `AgentCoreMemoryStore(actor_id, session_id, name)` with `candidates(query)`, `save(text, role)`
   and a `self.local` fallback. The design's §8 matches, and `reflexboundaries` → `MEMORY_REFLEXBOUNDARIES_ID`
   is token-safe.
10. **data.load (§9, MEDIUM-2).** `decider_kit/data.py::load` reads only `agent/data/<name>.json|.csv`.
    Markdown via a cached `read_text()` helper is required and correct.
11. **Submission checks (§1.4).** `check_pattern` enforces `PATTERN_TAG ∈ TAGS`
    (`#guardrails` ∈ set), single `PATTERN_TAG`, `QUESTIONS` defined, no `IS_KIT_EXAMPLE`;
    `check_agent` requires the literal tokens `agent_model`, `Decider`, `decision` in `agent.py`
    (all present via imports/usage). `inspect_agent` requires `PATTERN_TAG` and `QUESTIONS` at
    **module level** as literals — the design places them there. (The ONE gap is the docstring
    section headers — Finding 1.)
12. **Demo UI badge (HIGH-3/NIT-G).** `demo/static/index.html` defines
    `.proceed/.guide/.review/.deny/.block/.confirm` but not `.steer/.cut/.freeze`, and renders
    `class="tag ${verdict}"`. The CSS vars `--amber/--red/--blue/--green` exist. "Uncoloured (base
    `.tag` grey pill still applies)" is the accurate description; the three proposed rules are valid.
13. **Single pattern / tags.** `PATTERN_TAG = "#guardrails"` only; Memory is used as a supporting
    boundary store and the guardrail judgement stays with the decider, so NOT claiming
    `#context-memory` is correct and consistent with the one-pattern rule.
14. **Decider & LLM routing.** All decisions via `decider_kit.Decider.ask`; the model via
    `decider_kit.llm.agent_model()` through a Strands `Agent`; no boto3 `converse`/`invoke_model` or
    provider SDK anywhere in the design. Dangerous actions are mocked (no real FS/shell). Credit
    line retained in generated files. All consistent with the kit rules.

## Unverified / wrong assumptions

1. **Nova Pro stream granularity (design's own open item #1).** Whether Bedrock Nova Pro yields
   `data` deltas finely enough for a *dramatic* mid-sentence cut is NOT verifiable without a live
   run, which this review does not perform. The design honestly flags this, provides an offline
   proof of the seam **logic** (corrected StubModel + FakeDecider), a post-chunk degradation path,
   and a `REFLEX_MIDGEN` kill-switch that keeps every FR satisfied. This is handled responsibly and
   is not a blocking finding — it is correctly scoped as a build-time smoke test.
2. **`_task_for(message)` behavior (Finding 4).** Not defined in the design and not verifiable; the
   runtime mapping from a free-form message to a spec slice is the one place the state could be
   built against the wrong task. Flagged as NIT with a concrete fix.
3. **`last_result` assignment in the driver (Finding 3).** `_finish` reads `guard.last_result` but
   the §4.2 driver snippet never shows it being assigned; consistency depends on the implementer
   wiring it. Flagged as NIT.

---

Built with the AWS User Group Madurai Strands Decider hackathon kit.
