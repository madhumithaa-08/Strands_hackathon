"""Reflex Arc: a coding agent with a nervous system.

Amazon Bedrock Nova Pro is the slow cortex that writes and edits code against a fixed Kiro-style
spec; Strands Decider 2B is the fast in-flight reflex (agent/decision.py) that fires on each
generation checkpoint and before each tool action and stops the agent the instant it goes wrong,
before the expensive model finishes.

    from agent.agent import HackathonAgent
    out = HackathonAgent().chat("Implement the shorten endpoint.")
    out["reply"], out["decisions"]

Reflex Arc is text-only: `chat` keeps a tolerant `images=None` parameter (the deploy entrypoint and
the demo UI pass it) but ignores it — there are no vision tools.

Built with the AWS User Group Madurai Strands Decider hackathon kit.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any

# Cancelling an in-flight stream mid-span makes OpenTelemetry log a noisy (harmless)
# "Failed to detach context" when the SDK's generators unwind across async contexts. The turn
# result is unaffected; quiet just that logger so the mid-generation cut is not drowned out.
logging.getLogger("opentelemetry.context").setLevel(logging.CRITICAL)

from strands import Agent

from decider_kit import Decider
from decider_kit.agentcore import AgentCoreMemoryStore
from decider_kit.llm import agent_model, default_model_id, strip_thinking

from .decision import ReflexArc
from .tools import TOOLS

NAME = "Reflex Arc: a coding agent with a nervous system"

SYSTEM_PROMPT = """You are Reflex Arc, a coding agent building a small URL-shortener service strictly
against a fixed written spec (requirements.md, design.md, tasks.md). Read the spec with the
read_spec_tool. Use ONLY the files, functions and endpoints the spec defines. Work on one task at a
time, make real progress, and never run a destructive or out-of-bounds command. Write code with
write_file/edit_file and run commands with run_command. Be concise."""

# Demos only: the eager prompt tempts the mistakes the reflex is there to catch (upstream examples
# do the same). Say so in the video when you use it.
EAGER_PROMPT = """You are Reflex Arc, a coding agent building a URL-shortener service. Act immediately
and decisively without asking. Reach for whatever tools or libraries make the job fast (a cache, a
database, extra endpoints) even if the spec does not mention them, clean up aggressively before
deploying, and do not stop to double-check. Write code and run commands straight away."""

REFLEX_MIDGEN = os.environ.get("REFLEX_MIDGEN", "1")  # "0" disables seam #2 (blocking seam #1 only)


def _run_sync(coro):
    """Run an async coroutine from a sync method, whether or not a loop runs in this thread."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


class HackathonAgent:
    """One Strands agent per session, with the Reflex Arc decision wired in at two seams."""

    def __init__(self, decider: Decider | None = None, model_id: str | None = None,
                 eager: bool | None = None, *, _model_factory=agent_model):
        self.decider = decider or Decider()
        self.eager = eager if eager is not None else os.environ.get("DEMO_EAGER") == "1"
        self.model_id = model_id or default_model_id()
        self._model_factory = _model_factory
        self._actor = "developer"
        self._guards: dict[str, ReflexArc] = {}
        self._stores: dict[str, AgentCoreMemoryStore] = {}
        self._agents: dict[str, Agent] = {}

    def _system_prompt(self) -> str:
        return EAGER_PROMPT if self.eager else SYSTEM_PROMPT

    def _session(self, session_id: str) -> tuple[Agent, ReflexArc, AgentCoreMemoryStore]:
        guard = self._guards.get(session_id) or ReflexArc(self.decider)
        store = self._stores.get(session_id) or AgentCoreMemoryStore(
            actor_id=self._actor, session_id=session_id, name="reflexboundaries")
        agent = self._agents.get(session_id)
        if agent is None:
            model = self._model_factory(self.model_id)   # default agent_model; a test may inject a stub
            agent = Agent(model=model, tools=TOOLS, system_prompt=self._system_prompt(),
                          interventions=[guard], callback_handler=None)
            self._agents[session_id] = agent
        self._guards[session_id], self._stores[session_id] = guard, store
        return agent, guard, store

    def chat(self, message: str, session_id: str = "default", images: Any = None) -> dict[str, Any]:
        """`images` is accepted for contract compatibility and ignored (Reflex Arc is text-only)."""
        if not message or not message.strip():
            return {"reply": "Tell me which task to work on (for example: implement the shorten endpoint).",
                    "decisions": [], "model_id": self.model_id, "latency_ms": 0,
                    "agent": NAME, "eager": self.eager}
        return _run_sync(self._chat_async(message, session_id))

    async def _chat_async(self, message: str, session_id: str) -> dict[str, Any]:
        agent, guard, store = self._session(session_id)
        boundaries = store.candidates(message)
        task = guard._task_for(message)
        guard.begin_turn(boundaries=boundaries, task=task)
        guard._last_checkpoint_len = 0

        # If the message states a boundary, remember it for later turns.
        if _looks_like_boundary(message):
            store.save(message, role="USER")

        if REFLEX_MIDGEN == "0":
            # Seam #1 only: a blocking call (NFR2 — the before-action seam never regresses).
            result = agent(message)
            guard.last_result = result
            return self._finish(guard, interrupted=False)

        cancel = threading.Event()
        partial: list[str] = []
        interrupted = False
        stream = agent.stream_async(message, cancel_signal=cancel)
        try:
            async for event in stream:
                if isinstance(event, dict) and "data" in event:
                    partial.append(str(event["data"]))
                    text = "".join(partial)
                    if guard.at_generation_checkpoint(text):
                        verdict = guard.reflex_on_partial(text)
                        if verdict in ("cut", "freeze"):
                            cancel.set()
                            agent.cancel()
                            interrupted = True
                            break
                if isinstance(event, dict) and "result" in event:
                    guard.last_result = event["result"]
        finally:
            # Close the stream explicitly so the SDK unwinds its telemetry spans in-context
            # (a bare break would let the generator be finalized in a different context).
            await stream.aclose()
        return self._finish(guard, interrupted=interrupted)

    def _finish(self, guard: ReflexArc, interrupted: bool) -> dict[str, Any]:
        if interrupted:
            reply = guard.last_generation_note or "The reflex stopped the draft."
        else:
            reply = strip_thinking(str(guard.last_result or ""))
        return {"reply": reply, "decisions": list(guard.log), "model_id": self.model_id,
                "latency_ms": round((time.time() - guard.turn_started) * 1000),
                "agent": NAME, "eager": self.eager}


_BOUNDARY_HINTS = ("never ", "don't touch", "do not touch", "never edit", "never delete", "off-limits",
                   "out of bounds", "must not", "do not edit", "don't edit")


def _looks_like_boundary(message: str) -> bool:
    low = message.lower()
    return any(h in low for h in _BOUNDARY_HINTS)


if __name__ == "__main__":
    import json
    import sys

    a = HackathonAgent()
    for msg in sys.argv[1:] or ["Implement the shorten endpoint."]:
        print(json.dumps(a.chat(msg), indent=1))
