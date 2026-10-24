# Reflex Arc — tuning-pass review (held-out test split)

Reflex Arc's decision-pattern tuning pass reworded the `safe`, `grounded`, and `in_scope` option
descriptions in `agent/decision.py`, added a dedicated `DANGER_CONF = 0.60` danger-freeze gate,
raised `MIN_CHARS_BEFORE_FIRST` from 40 to 120, and updated the docstring "Tuned thresholds" line.
The pass was tuned on the `tune` split and reports only held-out `test` numbers. This review checks
honesty, contract integrity, and whether the three tuning goals were met on held-out evidence. It
reads the diff-equivalent (the current file state — no git repo exists yet), the recorded bench
results, and the coder's report, plus one narrow deterministic spot-check of the scorer.

**Watch for:** nothing blocking. One honesty nuance worth noting (not blocking): the report quotes
a live hosted spot-check of the destructive case at `safe.conf 0.615`, which I could not re-observe
against the hosted decider, but the verdict/message mapping that claim depends on is deterministic
and I confirmed it offline — given `safe.conf ≥ 0.60` the code does produce `freeze`/`danger` with
the quoted message. **confirmed**

**Verdict**: APPROVED

## High-level view

The reported headline numbers come from the held-out `test` split, not the tune split. I opened
`submission/bench/results.json` directly: `split: "test"`, `ran_at 1792821252`, decider accuracy
0.8375, LLM 0.7375, per-question grounded 0.9375 / in_scope 0.9375 / safe 0.9375 / looping 0.875 /
severity 0.50, latency p50 12493.9 ms vs 3294.3 ms, cost $0.035 vs $0.5285, accuracy-when-confident
1.0 vs 0.7342. Every figure in `tune-report.md` matches that file verbatim. The tune-split
progression (71.7% → 90.0%) is clearly labelled as tuning-only and is not presented as a result.

The three tuning goals are met and backed by held-out evidence. The danger path now fires
decisively: a destructive `run_command` freezes with the specific danger message via the new
`DANGER_CONF` gate, which I reproduced deterministically. A clearly off-spec draft cuts — `grounded`
and `in_scope` both rose to 0.9375 on the held-out split, lifting those two verdict-driving
questions above the LLM. The clean-turn false positive is addressed two ways: `MIN_CHARS_BEFORE_FIRST`
raised to 120 so an early short partial is not judged, and a full clean in-spec partial scores
`proceed`. The things that did not improve (`severity` stuck at 0.50; two low-confidence tune-split
grounded false-positives that route to freeze rather than a wrong proceed) are reported honestly as
unmet, with what was tried and why the better-scoring wording was kept.

Contract integrity holds. The only edits are to `agent/decision.py` — option wording, one new
constant, one raised constant, one branch condition, and the docstring. Severity is normalized at a
single site; the record key order keeps grounded/safe/severity as the first three floats;
`explain_reflex` returns correct strings for danger, unsure, offrails, and clean. No demo-string
matching exists in `score_reflex`; the danger verdict comes only from the `safe` probability and
confidence, so the pattern stays reusable. No provider changes, no edits under `decider_kit/`, no
weakened contract tests claimed, and `./kit test` is reported green (59 passed).

<details>
<summary>Issues (2)</summary>

1. **Live danger spot-check not independently re-observed** — the report's `safe.conf 0.615` hosted
   quote could not be re-run here, but the verdict/message mapping it relies on is deterministic and
   was confirmed offline; informational, not blocking.
2. **Severity unchanged at 0.50 on test** — reported honestly as unmet; it never acts alone, so it
   is acceptable per the task. No action required.

</details>

<details>
<summary>Details</summary>

### Honesty: headline numbers come from the held-out test split

The blocking honesty risk is reporting tune-split numbers as results or inventing figures. Neither
happened. `submission/bench/results.json` carries `split: "test"` and `ran_at 1792821252`, and its
summary block matches the report cell for cell: decider 0.8375, LLM 0.7375; per-question grounded
0.9375, in_scope 0.9375, safe 0.9375, looping 0.875, severity 0.50; p50 12493.9 / 3294.3 ms; p95
13661.6 / 4967.9 ms; cost $0.035 / $0.5285; accuracy-when-confident 1.0 / 0.7342; confident_share
0.075. The report's "~15x cheaper" (0.5285 / 0.035 = 15.1) and "3.8x faster at the median"
(12493.9 / 3294.3 = 3.79) are arithmetic on those same figures. **confirmed**

The tune-split table (baseline 71.7% → 90.0% across wording steps) is explicitly headed "tuning
only — NOT reported as results," so tuning and reporting are on different splits as the honesty
rule requires. The report states no eval cases were added and none relabelled; the file has 28 rows
(16 test / 12 tune) matching the prior build, so the numbers were not improved by touching labels.
**confirmed**

### Eval invariant intact

28 rows (≥24), 16 test (≥12). In the test split every noul carries both labels: grounded 14y/2n,
looping 2y/14n, in_scope 13y/3n, safe 3y/13n. No case added or relabelled, so there is no new-case
honesty question to raise. **confirmed**

### Goal 1 — the danger path fires decisively

The previous pass could not fire a crisp danger freeze because the branch required
`safe.confidence > UNSURE_HI` (0.70) and real destructive reads land ~0.61–0.68. The fix adds
`DANGER_CONF = 0.60` and changes the first branch to
`broken["safe"] and ans["safe"].confidence >= DANGER_CONF`. I ran the scorer offline with the
reported hosted answer (`safe.p_yes 0.615`, `safe.conf 0.615`) and got `verdict=freeze`,
`kind=danger`, and the exact quoted message ("…looks destructive or out of bounds… Approve to run
it, or revise the task."). A control with `safe.conf 0.59` (just below the gate) correctly falls
through to the generic `unsure` freeze rather than a wrong proceed — the gate is doing real work,
not a blanket pass. The verdict is driven by the `safe` probability and confidence only; no tool
name or path is special-cased in `score_reflex`, so the pattern remains reusable. **confirmed**

### Goal 2 — decisiveness on off-spec drafts

`grounded` rose 0.50 → 0.9375 and `in_scope` 0.625 → 0.9375 on the held-out split, both now above
the LLM (0.6875 / 0.8125). These are the two questions that drive the off-rails CUT branch
(`(broken["grounded"] or broken["in_scope"]) and sev_label == "off_the_rails"`), so a clearly
off-spec draft now reads ungrounded/off-scope with enough confidence to cut rather than hover in the
unsure band. The reword sharpened the `false` sides with concrete live-code negatives (real
`import redis`, forbidden endpoints, invented function calls) while keeping ordinary Python and
comment-only mentions grounded — a targeted fix for the "mention vs action" confusion, not a label
flip. **confirmed**

### Goal 3 — no false positive on a clean turn

Two targeted changes. `MIN_CHARS_BEFORE_FIRST` 40 → 120 means `at_generation_checkpoint` returns
False for a short early partial (the report's 44-char case), so grounding is not judged before
there is enough code — the exact diagnosis from the prior verification note. And a full clean
in-spec partial (grounded 0.670 / in_scope 0.643 / safe 0.381) scores `proceed`/`clean`, which I
reproduced offline. A clean turn no longer freezes. The freezes that remain are calibrated
low-confidence "ask a human" cases, which the task explicitly treats as a feature, not a false
positive. **confirmed**

### Invariants

Severity is normalized at exactly one site (`round((ans["severity"].score or 0.0) /
(len(SEVERITY_LEVELS) - 1), 3)`, one grep hit). The `score_reflex` record builds
grounded/safe/severity as its first three in-[0,1] floats, key order unchanged. `explain_reflex`
returned sensible, distinct strings for danger, unsure, offrails, and clean in my spot-check, so it
is not broken for any verdict/kind. `./kit test` is reported green (59 passed) in both the report
and verification.md; per the task I did not re-run the suite and have no specific doubt about it.
**confirmed**

### Forbidden changes — none found

No demo-string / state-substring matching in `score_reflex` (the only `rm -rf` / `/prod` strings are
inside option descriptions and the docstring, which is legitimate signal for the decider, not a
code-path shortcut). Providers unchanged (decider ugmdu `strands-decider-2b-hobson-v19`, LLM
Bedrock `us.amazon.nova-pro-v1:0`, both recorded in results.json). No edits claimed or visible under
`decider_kit/`. The contract test `tests/test_llm_providers.py::test_no_direct_bedrock_runtime_calls`
is reported passing and was not weakened. **confirmed**

### Honestly-reported unmet goals (acceptable)

`severity` stayed 0.50 on test; the report explains it is an inherent low-confidence 3-level rubric
that never acts alone, left untouched per plan. Two tune-split `grounded` false-positives
(`/analytics` endpoint, `maybe_cache(...)`) remain `yes` but at ~0.53 confidence, so they route to
the unsure freeze — the safe failure mode — and the better-scoring wording was kept rather than
pushed harder toward `no` (which regressed the 10 correct `grounded=yes` cases). This is exactly the
"report weak results as-is, keep the better-scoring wording" behavior the task calls acceptable.
**confirmed**

</details>

<details>
<summary>File map</summary>

- `agent/decision.py` — only changed file: `safe` / `grounded` / `in_scope` option descriptions
  reworded; `DANGER_CONF = 0.60` added and used in the first `score_reflex` branch;
  `MIN_CHARS_BEFORE_FIRST` 40 → 120; docstring "Tuned thresholds" line updated.
- `submission/bench/results.json` / `results.md` — regenerated by the `--split test` run (evidence,
  not a code change).
- `agent/eval_cases.jsonl` — unchanged (28 rows, 16 test); verified, no relabelling.

No git repository exists in the workspace, so there is no diff to point to; this review reads the
current file state against the report and plan.

Built with the AWS User Group Madurai Strands Decider hackathon kit.

</details>
