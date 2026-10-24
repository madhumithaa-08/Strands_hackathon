# Tasks: Reflex Arc

Ordered implementation list derived from the design's "files to create / replace". Everything is
under `agent/` (replacing the kit example) unless noted; nothing in `decider_kit/` changes. Each task
names the files it touches and the design sections it must satisfy.

- [ ] 1. **Fixed spec canon + machine-readable tasks** — create the data the reflex judges against.
  - `agent/data/spec/requirements.md`: EARS-style URL-shortener requirements (create short code,
    redirect, reject invalid/oversized URLs, list links; explicit NON-features).
  - `agent/data/spec/design.md`: the ALLOWED API surface (files `app.py`/`store.py`/`validate.py`/
    `config.py`, the functions, endpoints `POST /shorten` / `GET /{code}` / `GET /links`, config,
    NON-features) delimited by `<!-- API-SURFACE-START -->` / `<!-- API-SURFACE-END -->`.
  - `agent/data/spec/tasks.md`: Kiro-style checkbox tasks (some rigged).
  - `agent/data/tasks.json`: the seven task dicts with `id`/`title`/`spec_part`/`rig`.
  - Satisfies FR11 data, review MEDIUM-2 loading rule.

- [ ] 2. **Tools over a mocked sandbox** (`agent/tools.py`).
  - Strands `@tool`s: `read_spec(part)`, `list_files()`, `read_file(path)`, `write_file(path,
    content)`, `edit_file(path, patch)`, `run_command(cmd)`, `delete_path(path)`.
  - Mocked in-memory FS + command runner; dangerous ops simulated, never executed (defense-in-depth
    safety net, but the decider makes the block decision — no regex `if rm -rf`).
  - `read_spec(part)` cached `Path.read_text()` helper (markdown); `tasks.json` via
    `decider_kit.data.load("tasks")`. `write_file` content capped at `MAX_FILE = 20_000`.
  - Satisfies FR11, review MEDIUM-2.

- [ ] 3. **The reusable decision pattern** (`agent/decision.py`).
  - `REUSABLE DECISION PATTERN:` docstring that ALSO contains the four checker headings — `What it
    does`, `Typed questions` (and options), `Wiring`, and a reuse note (substring `reuse`).
    `PATTERN_TAG = "#guardrails"`. NO `IS_KIT_EXAMPLE`. (AC1/AC2, review finding 1.)
  - The five `QUESTIONS` (grounded, looping, in_scope, safe, severity) with exact option
    descriptions and the deliberate `safe`/`looping` inverted polarity.
  - `SEVERITY_LEVELS = ["fine","drifting","off_the_rails"]`; `VERDICT_ACTION` map (single source of
    the reflex-word → Strands-action mapping).
  - `reflex_state(...)` builder producing the fixed state layout (shared by both seams and every
    eval case; `STATE_CODE_TAIL = 1200`).
  - `score_reflex(answers) -> (record, verdict, action)` pure function with the threshold logic
    (`_broken`, `_any_broken`, `_driving_question`, `_driving_conf`, `_one_line_fix`,
    `_action_kwargs`) and the pinned severity computation / record key order.
  - `class ReflexArc(InterventionHandler)`: `before_invocation` (no `Confirm`), `before_tool_call`
    (`GUARDED_TOOLS`, dedup `_scored`, shared `_checks_used` cap, convergence `_guided`), the per-turn
    state (`begin_turn`, `turn_started`, `last_result`, `last_generation_note`, `log`), and the
    generation helpers `at_generation_checkpoint` / `reflex_on_partial`.
  - Satisfies FR3–FR8, FR10, review findings 1/2/3/5, MEDIUM-1/-4/-D, NIT-2.

- [ ] 4. **The agent: Bedrock cortex + both seams** (`agent/agent.py`).
  - `NAME`, `SYSTEM_PROMPT`, `EAGER_PROMPT`; `HackathonAgent.__init__(self, decider=None,
    model_id=None, eager=None, *, _model_factory=agent_model)`.
  - `_run_sync(coro)` bridge; `chat(self, message, session_id="default", images=None)` →
    `_run_sync(self._chat_async(...))`, tolerating and ignoring `images`.
  - `_session(session_id)` builds `Agent(model=self._model_factory(self.model_id), tools=TOOLS,
    interventions=[guard], callback_handler=None)` + `AgentCoreMemoryStore`.
  - `_task_for(message)`, `_chat_async` streaming driver (seam #2), `_finish(...)` reply resolution,
    boundary recall/store.
  - `REFLEX_MIDGEN` kill-switch (blocking fallback = seam #1 only).
  - The returned dict matches the six-key `chat()` contract.
  - Satisfies FR1, FR2, FR6, FR9, NFR2, review MEDIUM-B/-C/-E, NIT-F.

- [ ] 5. **Labelled eval cases** (`agent/eval_cases.jsonl`).
  - ≥24 rows (≥12 `test`) in the fixed state layout, covering every mode and near-miss per the
    coverage matrix (invent, grounded near-miss, looping, drift, danger, safe near-miss,
    boundary-memory, clean/false-positive, low-confidence, lone-severity).
  - Both `proposed action:` and `partial code so far:` variants present.
  - Invariant: for each of the four nouls both `yes` and `no` appear in the test split.
  - Satisfies FR12, AC7, review finding 6.

- [ ] 6. **Demo script** (`agent/demo_script.yaml`).
  - Six beats, `eager: true`, make_video-valid `intro`/`intro_normal`/`outro`/`pitch` (no numbers)
    and `narrate` lines (no measurements).
  - Each beat authored so the decisive verdict is among the first two decider calls of the turn.
  - Satisfies AC9, review finding 5.

- [ ] 7. **Deploy features** (`agent/features.yaml`).
  - `memory.enabled: true` (name `reflexboundaries`, strategies, expiry), `gateway.enabled: false`.
  - Loadable by `decider_kit/agentcore.py`.
  - Satisfies FR13, AC8.

- [ ] 8. **Pitch doc** (`agent/AGENT.md`).
  - Reflex-first pitch, who it's for, features, the one `#guardrails` decision, Bedrock Nova Pro,
    Memory for boundaries; states plainly that Reflex Arc is text-only and ignores any attached
    images. If the mid-gen seam degrades to post-chunk, document it here.
  - Satisfies NFR1/NFR4, review MEDIUM-C.

- [ ] 9. **Tests** (`tests/test_reflex_arc.py`, create) + kit-UI bug fix (`demo/static/index.html`,
  edit).
  - `FakeDecider` + `StubModel(Model)` (all four abstract methods, real `StreamEvent` chunks,
    honours `cancel_signal`), injected via `_model_factory`.
  - Unit: `score_reflex` truth table (one assertion per branch, incl. lone-severity→proceed);
    record key order + `0 <= severity <= 1`; severity-label validity; `reflex_state` byte-equals a
    known eval line (incl. a `safe` near-miss); `before_tool_call` guarded/read-only, convergence,
    shared `_scored`/`_checks_used` cap; generation-seam offline cut (`seam="generation"`,
    `verdict="cut"`, `interrupted=True`, stream cut early) + twin clean-generation no-cut;
    `chat("hi")` six-key shape.
  - Integration (opt-in): `REFLEX_MIDGEN=1` smoke test against real Nova asserting a
    `seam="generation"` record (and `interrupted=True` when cancellation works).
  - `demo/static/index.html`: add `.steer`/`.cut`/`.freeze` CSS rules (amber/red/blue) so the reflex
    verdict badges are coloured; keep the credit line and everything else.
  - Satisfies AC1/AC3/AC6/AC10, review HIGH-1/-2/-3, HIGH-A.

- [ ] 10. **Verify green, offline** — `./kit test` and `./kit run` pass with no network, no
  `boto3.converse`/`invoke_model`/provider SDK calls; `./kit check` passes `PATTERN_TAG`,
  single-pattern, `QUESTIONS defined`, labelled eval cases. Then `./kit bench --split test` for the
  reported accuracy/latency numbers. Satisfies AC10 and the kit no-direct-SDK test.

---

Built with the AWS User Group Madurai Strands Decider hackathon kit.
