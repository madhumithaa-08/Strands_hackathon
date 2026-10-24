# Reflex Arc — a coding agent with a nervous system

## The idea

Give a coding agent a reflex. Most AI coding agents are one big, slow brain: once they start a
long generation or a tool call, they are committed, and there is no cheap way to ask "wait, should
I stop?" mid-stream. An LLM watching another LLM would cost more than the thing it is watching.

Reflex Arc splits the job. **Amazon Bedrock Nova Pro** is the slow cortex that writes and edits
code against a fixed written spec. **Strands Decider 2B** is the fast spinal reflex: a small,
cheap, confidence-aware decision model that fires *in-flight* — on each generation checkpoint and
before each tool action — and stops the agent the moment it starts to go wrong, before the
expensive model finishes.

## Who it is for

Developers who hand an AI a spec (requirements, design, tasks — the way Kiro works) and want it to
stay on the rails: no inventing libraries the spec never mentions, no quietly building a feature
nobody asked for, no looping on the same failing edit, and no destructive command against a path
they said never to touch.

## What it does

- Writes and edits code in a sandbox against a fixed URL-shortener spec (`agent/data/spec/`).
- **Catches hallucinated dependencies** — reaches for Redis the spec never defines → the reflex
  cuts it.
- **Freezes destructive commands** — `rm -rf /prod/releases` → the reflex hands it to a human
  instead of running it.
- **Ends loops** — the same failing step retried with no progress → the reflex cuts it.
- **Steers scope drift** — wanders into an analytics dashboard → the reflex steers it back on task.
- **Remembers boundaries** — "never edit /prod" set earlier is recalled from AgentCore Memory and
  enforced on a later turn.
- **Stays quiet when the work is correct** — an on-spec change runs to completion with no interrupt.

## The one decision (`#guardrails`)

Every reflex check is a single Strands Decider 2B call over one shared state (spec excerpt +
current task + user boundaries + what the agent is doing right now) answering five typed questions
— `grounded`, `looping`, `in_scope`, `safe`, `severity`. The agent's own code maps the typed
answers to one of four verdicts: **proceed**, **steer** (Guide), **cut** (Deny), **freeze**
(Confirm / held). Low-confidence decisive calls freeze for a human instead of guessing. The
reusable pattern lives in `agent/decision.py`.

The pattern is `#guardrails`: the decider makes the guardrail call. AgentCore Memory is a
supporting feature only — it stores the user's boundaries so they can be put into the reflex state;
it does not make the decision, so we do not claim `#context-memory`.

## Text-only

Reflex Arc has no vision tools. `chat(message, session_id, images=None)` keeps the `images`
parameter for contract compatibility (the deployed runtime and the demo UI pass it), but it is
ignored — attached photos are not placed in the reflex state or the model call.

## The two seams

1. **Before-action reflex (the guaranteed core).** A Strands `InterventionHandler`
   (`before_tool_call`) scores every guarded tool call and returns Proceed / Guide / Deny /
   Confirm. This alone makes the demo stand on its own.
2. **Mid-generation reflex (the wow).** While Nova streams, the driver in `agent/agent.py` runs
   the same reflex at generation checkpoints on the partial text and cancels the in-flight
   generation on cut/freeze (`cancel_signal` + `agent.cancel()`), so the expensive model does not
   finish.

### Honesty about the mid-generation seam

The hosted decider takes about one to two seconds per call, so the reflex fires roughly one to
four checks per turn — not "every 200 ms". The default path attempts a true mid-stream cancel; the
offline test proves the seam logic with a stub Strands model and a fake decider (no network). If a
live smoke test shows Nova's Bedrock stream does not stop promptly, the documented fallback is to
let the current chunk finish and abandon the draft at the checkpoint before the next step
(`REFLEX_MIDGEN=0` disables seam #2 entirely, leaving the before-action seam as the hard backstop).
Whichever path is live, the before-action seam never regresses. The video and article state only
what the real run showed.

---

Built with the AWS User Group Madurai Strands Decider hackathon kit.
