# Requirements: Reflex Arc

A coding agent with a nervous system. Amazon Bedrock (Nova Pro) is the slow cortex that writes and
edits code against a fixed Kiro-style spec; Strands Decider 2B is the fast spinal reflex that fires
**in-flight** — on each generation checkpoint and before each tool action — and stops the agent the
instant it starts to go wrong, before the expensive model finishes.

- **Pattern (hard, exactly one):** `PATTERN_TAG = "#guardrails"`. Submission tags:
  `#strands-decider-2b` + `#guardrails`.
- **LLM:** Amazon Bedrock, Nova Pro (`BEDROCK_MODEL_ID`, default `us.amazon.nova-pro-v1:0`),
  built only through `decider_kit.llm.agent_model()` and a Strands `Agent`.
- **Decider:** hosted (UG Madurai), `DECIDER_MODE=ugmdu`, through `decider_kit.Decider` only.
- **AgentCore features:** Memory ENABLED (stores user boundaries across sessions), Gateway OFF.
  Memory is a *supporting* feature only; the guardrail decision is still made by the decider, so
  the pattern stays `#guardrails` (we do **not** claim `#context-memory`).

## Summary

Reflex Arc is a coding agent for developers who have handed an AI a spec and want it to stay on the
rails. Given a fixed spec (a URL-shortener service: `requirements.md` / `design.md` / `tasks.md`,
Kiro-style, shipped as the agent's canon under `agent/data/`), the agent picks a coding task and
asks Bedrock to produce code or a shell command. A single Strands Decider 2B call — the *reflex* —
reads the spec excerpt + the task + the partial output/action-so-far + any stored user boundaries,
and the agent's own code maps the decider's typed answers to one of four reflex verdicts:

- **LET IT RUN** (`Proceed`) — all green.
- **STEER** (`Guide`) — a soft flag; one-line correction; must converge (same guided action again,
  unchanged → escalate to `Deny`).
- **CUT** (`Deny`) — grounding/scope broken and overall off the rails.
- **FREEZE/ASK** (`Confirm`) — a destructive/boundary-violating action, or any decisive call the
  decider is only ~0.5–0.7 confident about → hand to the human.

The reflex fires at **two seams**:

1. **Before-action reflex (guaranteed core):** a Strands `InterventionHandler` (`before_tool_call`
   for proposed tool actions, `before_invocation` for the incoming request). This alone makes the
   demo stand on its own.
2. **Mid-generation reflex (the wow, layered on top):** the decider fires at generation
   **checkpoints** (line/paragraph boundaries) on the partial text as Nova streams, and cancels the
   in-flight generation on CUT/FREEZE — before Bedrock finishes the expensive response.

## Functional requirements

- **FR1** — The agent SHALL expose `NAME` and `class HackathonAgent` with
  `chat(message, session_id="default") -> dict` returning the exact dict shape in the design (§3.1).
- **FR2** — The agent's generative work (writing/editing code, composing commands, explaining)
  SHALL run on Amazon Bedrock Nova Pro, built via `decider_kit.llm.agent_model()` and called through
  a Strands `Agent`. No boto3 `converse`/`invoke_model` and no provider SDK anywhere.
- **FR3** — Every reflex decision SHALL be made by **one** `Decider.ask(state, QUESTIONS)` call
  (one state, five typed questions). Thresholds/mapping to verdicts SHALL be ordinary `if`
  statements in the agent's own code.
- **FR4 (before-action seam)** — Before any **guarded** tool runs, the agent SHALL build the reflex
  state from {spec excerpt, current task, proposed tool call, stored boundaries}, ask the decider
  once, and return `Proceed`/`Guide`/`Deny`/`Confirm`. Read-only/safe tools pass untouched.
- **FR5 (input seam)** — Before the agent starts on a user message, `before_invocation` SHALL run a
  lightweight check (injection / off-task request) and clear per-message convergence state.
- **FR6 (mid-generation seam)** — While Nova streams a reply, the agent SHALL accumulate text and,
  at each checkpoint boundary, run the reflex on the partial text. On CUT or FREEZE it SHALL stop
  consuming the stream and cancel the in-flight generation (`cancel_signal` / `Agent.cancel()`), so
  the expensive model does not finish.
- **FR7 (Guide convergence)** — A guided tool call retried unchanged SHALL be denied (Strands
  requires `Guide` to converge). A guided *generation* that drifts the same way again SHALL escalate
  to CUT.
- **FR8 (low confidence)** — On the **action** and **generation** seams, when a broken question's
  driving confidence is in the unsure band (0.50–0.70) OR the `safe` question is broken, the verdict
  SHALL be FREEZE/ASK (`Confirm` on the action seam; a held reply on the generation seam), never a
  silent `Proceed`. The **input** seam (`before_invocation`) CANNOT return `Confirm` (the installed
  SDK types `before_invocation` as `Proceed | Deny | Guide | Transform` only), so there FR8 is
  satisfied by `Deny` on a confident injection/off-task read and `Proceed` otherwise — the
  action/generation seams catch any risky follow-through. FR8 does NOT apply to the input seam's
  low-confidence case.
- **FR9 (boundaries/memory)** — The agent SHALL remember user boundaries ("never edit /prod",
  "don't touch the deploy script") stated in earlier turns, via AgentCore Memory when deployed
  (in-process fallback locally), and include them in the reflex state so the `safe` question can
  catch a later violation.
- **FR10 (decision log)** — Each decider call SHALL append exactly one record to a log, surfaced in
  `chat()`'s `decisions`, with the five probabilities in 0..1, a `verdict`, a `seam`, and
  `decider_ms`. One decider call = one record.
- **FR11 (sandbox)** — Tools SHALL operate on a mocked in-memory filesystem and a mocked command
  runner. Dangerous actions (`rm -rf`, writing under `/prod`) SHALL be simulated, never executed.
- **FR12 (eval)** — `agent/eval_cases.jsonl` SHALL hold ≥24 cases (≥12 `test`), state in the exact
  runtime layout, covering every mode and near-miss.
- **FR13 (deploy)** — `agent/features.yaml` SHALL enable AgentCore Memory, Gateway off, matching the
  schema `decider_kit/agentcore.py` + deploy expect.

## Non-functional requirements

- **NFR1 (honesty)** — The hosted decider is ~1–2 s/call. The design fires ~1–4 reflex checks per
  turn, NOT "every 200 ms". No narration or doc claims sub-second-interval monitoring.
- **NFR2 (seam #1 never regresses)** — The mid-generation seam is additive. If it is disabled or
  degraded, the before-action seam still catches every pre-action case.
- **NFR3 (determinism/offline)** — Spec, tasks and tools are deterministic and offline;
  `./kit test` runs with `FakeDecider` and a mocked Bedrock model, no network.
- **NFR4 (credit)** — Keep "Built with the AWS User Group Madurai Strands Decider hackathon kit" in
  all generated files; `decider_kit/` is the kit's.

## Acceptance criteria (numbered, testable)

1. `tests/test_agent_contract.py` passes unchanged: `decision.py` docstring starts
   `REUSABLE DECISION PATTERN:`, `PATTERN_TAG` ∈ the five tags, `QUESTIONS` typed, every
   `eval_cases.jsonl` `expected` key ⊆ `QUESTIONS`, `HackathonAgent(...).chat` callable.
2. `agent/decision.py` has NO `IS_KIT_EXAMPLE`; `./kit check` PASSES `PATTERN_TAG`, single-pattern,
   and `QUESTIONS defined`. The `decision.py` docstring MUST start with `REUSABLE DECISION PATTERN:`
   AND contain the four headings the checker greps for — `What it does`, `Typed questions` (and
   options), `Wiring`, and a reuse note (substring `reuse`). (Resolves review finding 1.)
3. `chat()` returns a dict with at least `reply, decisions, model_id, latency_ms, agent, eager`;
   every item in `decisions` has the five probabilities (0..1 floats), `verdict`, `seam`,
   `decider_ms`.
4. Given a proposed `run_command("rm -rf /prod")`, the before-action reflex returns `Confirm`
   (FREEZE/ASK), and a corresponding log record has `verdict == "freeze"`.
5. Given a proposed `write_file` that invents a function/endpoint not in the spec, the reflex returns
   `Guide` first, then `Deny` on an unchanged retry (`test` asserts `Guide` then `Deny`).
6. A clean, on-spec generation runs to completion with **no** interrupt and verdict `proceed`
   (false-positive guard).
7. `agent/eval_cases.jsonl` has ≥24 cases, ≥12 `test`; `./kit check` reports "labelled eval cases"
   PASS.
8. `agent/features.yaml` parses with `memory.enabled: true`, `gateway.enabled: false`, loadable by
   `decider_kit/agentcore.py` (`AgentCoreMemoryStore`).
9. `agent/demo_script.yaml` has the six beats, `eager: true`, narrate lines with no numbers
   (make_video.py rejects numbers in `intro/outro/pitch` and measurements in `narrate`).
10. `./kit test` and `./kit run` are green offline; no `boto3.converse`/`invoke_model` / provider
    SDK calls (kit test enforces this).

## Out of scope

- Real filesystem writes or real shell execution (mocked only).
- Executing against a real cloud/prod environment.
- Claiming `#context-memory`; Gateway; vision/images.
- Per-token (every-200ms) monitoring; multi-file real refactors; Git operations.

---

Built with the AWS User Group Madurai Strands Decider hackathon kit.
