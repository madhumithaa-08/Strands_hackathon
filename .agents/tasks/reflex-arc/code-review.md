# Reflex Arc — code review (loop verdict gate)

Reflex Arc replaces the kit example with a `#guardrails` coding agent: Amazon Bedrock Nova Pro writes
code against a fixed URL-shortener spec, and one Strands Decider 2B call per check (five typed
questions over one shared state) acts as an in-flight reflex at two seams — a before-action
`InterventionHandler` and a mid-generation stream monitor that cancels Nova when a draft goes off the
rails. This review checks the implementation against the approved design (`design.md`), the six
design-review findings (`design-review.json`), and the coder's recorded evidence
(`verification.md`). I read the changed `agent/` files and `agent/data/`, and ran three narrow
spot-checks (kit-example/boto3 grep + decider_kit git state; eval counts/balance; demo-script
guards + spec markers). I did not re-run the suite or `./kit bench` — the evidence records `59
passed` and the live runs, and nothing in it left an articulable doubt.

Watch for: nothing blocking. One honest caveat, already flagged by the coder and deferred to the
online bench step, is a tuning-stage false-positive freeze on short early partials (confirmed in
verification.md, not a build defect). The before-action seam catches everything regardless, so
seam #1 never regresses.

**Verdict**: APPROVED

## High-level view

The decision pattern is clean and correctly labelled. `agent/decision.py` carries a
`REUSABLE DECISION PATTERN:` docstring with all four grepped headings, exactly one
`PATTERN_TAG = "#guardrails"`, no `IS_KIT_EXAMPLE`, and the five typed `QUESTIONS` at module level.
The verdict logic lives in one pure `score_reflex`, and the reflex-word→Strands-action map
(`VERDICT_ACTION`) is a single source of truth, so both seams and the convergence guard stay
consistent.

Severity normalization (MEDIUM-2) is pinned to one site — `round(ans['severity'].score /
(len(SEVERITY_LEVELS)-1), 3)` — with `SEVERITY_LEVELS` defined once, and the record is built in the
load-bearing key order so `grounded, safe, severity` are the first three in-range floats the video
narrates. A unit test asserts all five probabilities and severity sit in `[0,1]`, and a second
asserts the first-three-floats order, so a future reorder can't silently push the danger signal off
camera.

The two seams share `reflex_state`, the five `QUESTIONS`, and `score_reflex`, so the eval cases
measure the same thing the runtime sends. The contract surface on `chat()` is intact: the six-key
dict, decisions carrying the five probabilities plus `verdict`/`seam`/`decider_ms`, a constructor
taking `eager: bool | None`, and a tolerant ignored `images=None`. Every LLM path goes through
`decider_kit.llm` + a Strands `Agent`; every decision through `decider_kit.Decider`; `decider_kit/`
is untouched; dangerous tool actions are simulated; the kit credit line is kept; no `.env` is
committed (there is no git repo yet, and `.env` is git-ignored).

The offline test file subclasses the Strands `Model` ABC with a `StubModel` that yields real
`StreamEvent` chunks and honours `cancel_signal`, exercising the mid-generation cut without a
network. The no-direct-Bedrock contract test is left in place and recorded green.

<details>
<summary>Issues (1)</summary>

1. **Early-partial false-positive freeze (tuning, non-blocking)** — on short early partials the
   hosted decider can read borderline-`grounded` (~0.44, conf ~0.55) and the unsure band turns it
   into a freeze on a clean turn; deferred to the online bench step (raise
   `MIN_CHARS_BEFORE_FIRST` / sharpen `grounded` descriptions, tune on the tune split only). Does
   not affect the offline tests or seam #1.

</details>

<details>
<summary>Details</summary>

## Finding MEDIUM-1 — pattern label and docstring headings

`agent/decision.py`'s module docstring starts with the literal `REUSABLE DECISION PATTERN:` and
contains all four substrings the checker greps case-insensitively: `What it does`, `Typed questions`,
`Wiring`, and a reuse note (`How to reuse it`, containing `reuse`). `PATTERN_TAG = "#guardrails"` is
the only pattern tag (grep shows one definition; the other `PATTERN_TAG` references are record
fields). There is no `IS_KIT_EXAMPLE` anywhere in `agent/`. `QUESTIONS` is a module-level dict of the
five typed questions, and every `eval_cases.jsonl` `expected` key is a subset of `QUESTIONS` (checked:
no stray keys). This finding is implemented.

## Finding MEDIUM-2 — severity normalization and the unit range test

`SEVERITY_LEVELS = ["fine","drifting","off_the_rails"]` is defined once. The only severity
computation is `severity = round((ans["severity"].score or 0.0) / (len(SEVERITY_LEVELS) - 1), 3)`
inside `score_reflex`, read via `.label`/`.score` for the verdict — never via a non-existent
`.p_yes` on a score answer. `test_record_probabilities_and_severity_in_unit_range` iterates a sample
set and asserts `grounded, safe, severity, looping, in_scope` are each in `[0,1]` for every built
record; `test_record_key_order_first_three_floats` asserts the first three in-range floats are
exactly `("grounded","safe","severity")`. Both the normalization pin and the test are present.

## Findings NIT-3/4/5/6 — state, task resolution, demo beats, eval invariant

Per-turn state is enumerated on `ReflexArc` (`_guided`, `_scored`, `_checks_used`, `turn_started`,
`last_result`, `last_generation_note`, plus `_boundaries`/`_task`) and reset in `begin_turn`. The
driver in `_chat_async` assigns `guard.last_result` from the stream's `result` event, and `_finish`
reads it only when not interrupted. `_task_for` is concrete (keyword-match against `tasks.json`
titles, else the first task, else `None`), and `reflex_state` renders the literal
`(task not identified)` for the `None` case (NIT-4). Demo beats are authored so the decisive verdict
lands early (the rigged turns drive a single decisive check), satisfying NIT-5's "first two decider
calls" narration constraint. The eval invariant (NIT-6) is met: 28 rows, 16 `test`, and for each of
`grounded/looping/in_scope/safe` both `yes` and `no` appear in the test split (spot-checked
directly).

## chat() contract and the sync→async bridge

`chat(self, message, session_id="default", images=None)` returns `{reply, decisions, model_id,
latency_ms, agent, eager}`. Each decision record carries the five probability fields plus `verdict`,
`seam`, and `decider_ms` (`test_chat_shape_under_stub` asserts this). The constructor is
`__init__(self, decider=None, model_id=None, eager=None, *, _model_factory=agent_model)` — `eager:
bool | None` honoured via `DEMO_EAGER`, and `_model_factory` is the keyword-only test seam. `images`
is kept and explicitly ignored (text-only), so the deploy entrypoint's `chat(prompt, session,
images=images)` and the demo's signature probe keep working. The empty-message branch short-circuits
to the six-key dict with `decisions == []`. `_run_sync` guards the single sync/async crossing.

## The two seams and convergence

Seam #1 is wired by `Agent(..., interventions=[guard])`. `before_tool_call` proceeds on read-only
tools, scores guarded tools with one `decider.ask`, dedups by signature, respects
`MAX_CHECKS_PER_TURN`, and enforces FR7 convergence: a `steer` adds the signature to `_guided`, and
the same signature again returns `Deny`. Seam #2 drives `agent.stream_async` with a
`threading.Event` cancel signal, accumulates `event["data"]` deltas, runs `reflex_on_partial` at
checkpoints, and on `cut`/`freeze` sets the cancel signal, calls `agent.cancel()`, and breaks. The
stream is closed in a `finally` so telemetry unwinds in-context. Both seams build state through the
one `reflex_state` and run the one `score_reflex`.

## Decider-availability fail-safe

`_ask` retries transient 503s with short backoff and, on hard failure, returns `None`; the action
seam then fails safe to `Confirm`, the generation seam to a held note, each logging a
`decider_unavailable` record rather than crashing the turn. This matches design Part 10.

## No direct Bedrock, mocked danger, credit, secrets

Grep over `agent/` finds no `boto3`, `converse`, or `invoke_model`; the model is built via
`agent_model` (through the `_model_factory` seam) and called through a Strands `Agent`, and every
decision goes through `decider_kit.Decider`. `decider_kit/` shows no local modifications.
`run_command` and `delete_path` are simulated only — they record intent and flag danger hints as
inert defense-in-depth, never executing. The kit credit line is present in `decision.py`, `agent.py`,
`tools.py`, `features.yaml`, `demo_script.yaml`, and `AGENT.md`. There is no git repository yet, so
nothing is committed; `.env` is git-ignored. `features.yaml` has `memory.enabled: true`
(`reflexboundaries`) and `gateway.enabled: false`, matching the AgentCore schema.

## Tests and the offline mid-generation seam

`tests/test_reflex_arc.py` imports `StubModel(Model)` implementing all four abstract methods and a
`stream` that yields `messageStart` → `contentBlockDelta` per chunk → `contentBlockStop` →
`messageStop` → `metadata`, honouring `cancel_signal` between chunks. `test_generation_seam_cuts_
midstream` asserts a `seam="generation"` `cut` record with `interrupted` and that the stream was cut
early; `test_generation_seam_clean_runs_to_completion` asserts a clean run consumes all chunks with
no cut. The `score_reflex` truth table covers every §3.5 branch including the lone-severity PROCEED
(MEDIUM-D). The no-direct-Bedrock contract test was not weakened (recorded green in verification.md,
`test_llm_providers.py` → 10 passed).

</details>

<details>
<summary>File map</summary>

- `agent/decision.py` — labelled `#guardrails` pattern: docstring, `QUESTIONS`, `SEVERITY_LEVELS`,
  `VERDICT_ACTION`, pure `score_reflex`, `reflex_state`, `ReflexArc` handler with both seams.
- `agent/agent.py` — `HackathonAgent` with the streaming driver, both seams wired, six-key dict,
  `_run_sync` bridge, tolerant ignored `images`.
- `agent/tools.py` — seven Strands tools over a mocked in-memory FS + simulated command runner.
- `agent/eval_cases.jsonl` — 28 rows (16 test), states byte-identical to `reflex_state`.
- `agent/features.yaml` — AgentCore Memory on, Gateway off.
- `agent/demo_script.yaml` — six beats (7 turns), `eager: true`, no digits/measurements in guarded fields.
- `agent/AGENT.md` — reflex-first framing, text-only note, credit line.
- `agent/data/spec/{requirements,design,tasks}.md`, `agent/data/tasks.json` — fixed canon with API-surface markers; kit `orders.json` removed.
- `tests/test_reflex_arc.py` — offline wiring tests (FakeDecider + StubModel subclassing the Strands Model ABC).
- `demo/static/index.html` — added `.steer/.cut/.freeze` badge CSS.

Contract documents: `design.md`, `design-review.json`, `plan.md`, `verification.md` (the recorded evidence).

</details>
