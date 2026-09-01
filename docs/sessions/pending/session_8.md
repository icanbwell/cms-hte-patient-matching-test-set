# Session 8 — Legacy Comparison Harness: Precision/Recall, Disagreement Buckets, Explanations

**Status:** pending
**Thread:** Evaluation & Statistical Rigor Framework
**Estimated size:** L — a new cross-repo comparison harness, a disagreement-bucketing
classifier, and a first-class explanation-output formatter; larger than a typical M/L session.

> This session doc originated in the patient-matching repo. Read [conventions.md](https://github.com/icanbwell/patient-matching/blob/main/docs/sessions/conventions.md) there first (this repo does not carry its own copy).

## Outcome purpose

`docs/handoff/README.md` §4.5 ("How to test Line B — this is the crux of 'going live'") and
§4.6 ("Expected impact of Line B") require, before prod cutover: documented precision/recall/
FPR **against the current algorithm's baseline**, and §4.5/§2.4's "shadow validation" —
comparing the new engine's decisions against the current (legacy) engine's decisions on real
traffic before cutover. `conventions.md`'s statistical-rigor gate names full real-population
precision/recall/FPR as **Tier 3** ("explicitly not a near-term blocker... track as a
pre-production-cutover milestone, not a gate on any session in this backlog") — session 3's own
"Out of scope" section defers exactly this to "session 4 (Tier 2) and, at population scale,
Tier 3." This session is that Tier 3 work: it does not gate sessions 1-7, but it is the
artifact that lets the lead engineer and the repo maintainer actually decide go/no-go on cutover,
per handoff §4.6's "Success criteria for go-live."

This session builds the harness and produces the comparison; it does **not** perform the
cutover itself (see "Out of scope").

**Design update, 2026-08-13 (the lead engineer, internal chat):** rather than (or in addition to
— see below) comparing the two engines' outputs against *each other* as this doc originally
scoped, the lead engineer's current thinking is a labeled test set — columns `Outside Record`,
`Internal Record`, `IsMatch [0,1]` — with both engines scored independently against the same
labels. Starting point: the straightforward ONC matching approach (session 3's
`evaluation/onc_baseline.py` data/pairing pattern) plus **simple-negative mining** to generate
the non-match rows, rather than random negatives. This sidesteps the "is legacy ground truth?"
problem this doc's Scope item 2 and Open Questions wrestle with — a real `IsMatch` label makes
both engines' precision/recall directly computable and comparable, not just their agreement with
each other. **The lead engineer said they'd discuss the test-data simulation methodology with the
repo maintainer the same day (2026-08-13) — "multiple approaches" are still on the table, so
treat the labeled-set *shape* (the three columns above) as settled, but the *simulation method*
as not yet finalized.** Confirm with the lead engineer before executing whether this replaces
Scope item 1-2's legacy-vs-new comparison outright,

**Update, 2026-08-14 (resolved — see `session_9.md`):** the chat conversation with the repo
maintainer happened 2026-08-14 (one day later than expected above), and the simulation
methodology is now resolved: true-match rows come from single-edit-distance mutations of a real
record (matching the CMS spec's own fuzzy-tolerance definition); true-non-match rows come from
mining real, distinct-record pairs that collide on several fields — not from asserting a mutation
is "a different person," which would only test the algorithm's own tolerance rather than reality.
This is now built as **session_9** (`docs/sessions/in_review/session_9.md`,
`evaluation/mutations.py` + `evaluation/hard_negatives.py` + `evaluation/labeled_pairs.py`),
authored as an upstream dependency of this session rather than folded into it, since this
session's own scope (cross-repo legacy comparison, adjudication, disagreement bucketing) is
already large. **This does not yet resolve whether the labeled-set approach replaces or runs
alongside Scope items 1-2 below — that decision is still open, now tracked in "Open questions."**
or runs alongside it — this doc has not been restructured around it pending that confirmation,
only annotated at each place it's relevant.

## Upstream sessions (must be completed first)

- **Session 3** (ONC baseline, `completed/`) — this session reuses `evaluation/rule_eval.py`'s
  `LabeledPair`/`compare()`/`ComparisonReport` machinery directly, the same way session 4 did,
  rather than inventing new comparison plumbing.
- **Session 4** (real-world FHIR data source) — **hard code dependency, NOT yet satisfied as of
  this doc's authoring (2026-08-11).** Session 4's PR (#22) is open and green but **not yet
  merged into `main`** — it is in `docs/sessions/in_review/`, not `completed/`. Per
  `conventions.md`'s dependency rule, branching from `main` today would not have session 4's
  `notebooks/fhir_match_data_source.py` (the real-batch query/join/transform this session reuses
  for its "select a batch of real user records" step). **Do not start execution until session 4
  is confirmed in `completed/`** — if told to start this session before then, stop and tell the
  lead engineer, per the "start the next session" protocol's step 3, rather than re-deriving the
  query logic independently.
- **Session 6** (Table 2 v3.3 expansion) — **soft/quality dependency, not a hard code
  dependency.** This session's harness-building tasks (1-4 below) can be built and tested against
  whatever rule set currently exists in `patient_matching/matching/table2_rules.py` (today: the
  26-rule v3.2.2 set, since session 6 hasn't started — see index.md's Suggested Next Session).
  But the comparison numbers this session produces are only meaningful as a **go-live** artifact
  once session 6 (and any addenda-driven follow-up sessions — see the open `NEEDS HUMAN DECISION`
  on rules 34/35/37 and the v3.3.1-3.3.6 addenda, flagged by the lead engineer 2026-08-04 but not
  yet landed in this repo) is in `completed/`. This session's own Definition of Done therefore
  includes an explicit call-out (see Validation) distinguishing "harness works, produces a
  report" (achievable now) from "report reflects the final rule set" (blocked on session 6 +
  addenda resolution).

## Downstream sessions (unblocked by this one)

None yet authored. This session's output (the comparison report + disagreement buckets) is the
evidence base for the **not-yet-scoped Phase 2 work** — porting the engine into the legacy
production matching engine's codebase, the production matching service's response adapter,
shadow-mode infrastructure, and the two-repo release sequence — but authoring those session-style
docs is explicitly out of scope here (see "Out of scope").

## Upstream data/system dependencies

- **Real FHIR Patient + Person-Patient match-link batch.** Reuses session 4's
  `notebooks/fhir_match_data_source.py` query pattern (`bronze.fhir_lake.patient_4_0_0` joined to
  `silver.fhir_lite.person_patient`) once session 4 is `completed/`. The meeting-notes plan calls
  for a sample "biased toward hard cases rather than pure random" — per the PHI guardrail
  (`conventions.md`), that biasing must happen entirely inside the `spark.sql` predicate (e.g.
  favoring `person_uuid`s with >1 linked `patient_uuid`, or Patient rows with multiple historical
  `name`/`identifier` entries), never by pulling a random sample and inspecting real values
  in this repo to decide what's "hard." **Recommended default (author's call, not a
  `NEEDS HUMAN DECISION`):** implement hardness as SQL-expressible predicates only (multi-link
  count, multi-valued name/identifier count) — document the exact predicates used in *Execution
  notes* so the bias is reproducible and auditable, not ad hoc.
- **Legacy engine output, for comparison.** The current production algorithm lives in this
  organization's legacy production matching engine (a separate internal package: scoring in
  `logics/score_calculator.py`, entry rule set `logics/rule_library.py`) — a different repo than
  `patient-matching`. No prior session in this repo has taken a runtime dependency on another
  internal repo's package (session 3 only copied static, public ONC data and matched column
  semantics by inspection). **`NEEDS HUMAN DECISION — lead engineer`:** is it acceptable for
  `patient-matching` to add the legacy engine as a dev/evaluation-only dependency (e.g. an
  optional `[dependency-groups] eval` extra, matching how `evaluation/`'s numpy/pandas/scipy are
  already handled per `conventions.md`'s testing-structure section) so this session can call the
  legacy scorer in-process, or is there a reason to keep the two repos fully decoupled (e.g. a
  pinned/frozen legacy version requirement, or a policy against cross-repo runtime deps)?
  **Recommended default if genuinely stuck:** add it as an eval-only extra, pinned to whatever
  version of the legacy engine is actually live in prod at the time this session executes (check
  the production matching service's deployed dependency pin, not just the package index's latest)
  — evaluation on a version that isn't the one in production would misrepresent the comparison.

## Downstream data/system dependencies

None new — like session 4, this session's only output is a report artifact (a `ComparisonReport`
plus a disagreement-bucket table), never committed data or query output, per the PHI guardrail.

## Scope

### In scope

1. **Comparison harness.** New module `evaluation/legacy_comparison.py`, following
   `evaluation/onc_baseline.py`'s shape:
   - Load a real batch via session 4's notebook query pattern (parameterized, PHI-guardrail
     compliant — table/predicate names only, no hardcoded real values).
   - Score each record pair with **both** engines: this repo's
     `MatchingEngine.evaluate_pair()` (session 3's pairwise API) for the new engine, and the
     legacy production matching engine's scorer (once the dependency question above is resolved)
     for the baseline.
   - Store both engines' outputs keyed by a stable pair/record identifier so every pair is
     joinable (mirrors the meeting notes' Step 2) — in memory for the run, never persisted as
     raw PHI-bearing output to this repo (matches session 4's "no query output committed"
     pattern).
   - Emit a diff table: agreements, new-engine-only matches (candidate false positives),
     legacy-only matches (candidate false negatives).
2. **Precision/recall via `rule_eval.compare()`, framed as agreement, not ground truth** —
   *see the 2026-08-13 design update above first: the lead engineer's labeled-test-set direction
   (`Outside Record`/`Internal Record`/`IsMatch`) would give real precision/recall per engine
   directly, which may supersede this item's "framed as agreement, not ground truth" hedge
   rather than needing it alongside it. Confirm with the lead engineer which one this session
   actually delivers before building both.* Call
   `evaluation/rule_eval.py`'s existing `compare()`/`format_report()` with
   `baseline_name="legacy engine"` and `candidate_name="CMS v3.3 engine"` — this
   is exactly the tool session 3 built for baseline-vs-candidate comparison, reused rather than
   reinvented. Per the meeting notes' Step 3, the report's own text must state explicitly that
   these are **agreement-rate** metrics against a non-ground-truth baseline, not true precision/
   recall — `rule_eval.py`'s existing `ComparisonReport` formatting already carries a
   `NEEDS MORE DATA`-style verdict mechanism (see session 3's baseline run); extend its header
   text to say so plainly when `baseline_name` is a live system rather than a labeled dataset.
3. **Hand-adjudication sample.** Emit a small (author's call on size — recommend 25-50, large
   enough to characterize disagreement patterns without becoming a second full validation pass)
   CSV-shaped sample of disagreeing pairs' *rule outcomes and bucket labels* (see Task 4) for a
   human to adjudicate — **never the underlying PHI values themselves**, consistent with the PHI
   guardrail. **`NEEDS HUMAN DECISION — lead engineer`:** who actually adjudicates this sample
   (the lead engineer, or the reviewing team) — they need advance notice per the meeting notes'
   own gap list. Default if unanswered at session-start: flag to the lead engineer as a blocking
   question before this task executes, since the sample can't be scored without an adjudicator
   identified.
4. **Disagreement bucketing.** New function(s) in `evaluation/legacy_comparison.py` (or a
   sibling module if it grows large) that classify each disagreeing pair into exactly one of:
   nickname/diminutive, typo/transposition, name-order or compound/hyphenated surname, missing
   or conflicting DOB, address/contact-field difference, duplicate source records — built as
   pure functions over each pair's already-extracted `PatientFields` diff (never raw values
   logged), each with a count and a recommended call (tune / acceptable / legacy-was-wrong) per
   bucket, matching the meeting notes' Step 4 exactly.
5. **Explanation output.** Per candidate pair: contributing fields, each field's outcome
   (exact/fuzzy/missing/no_match — this is **already produced** by `MatchingEngine._evaluate_rule`'s
   existing `RuleEvaluation.field_outcomes`/`fuzzy_fields`, per session 1's audit-record work),
   the matched rule's `p_collision_exact`/`_fuzzy` as the "score," and the 2e-12 threshold it was
   measured against. This is mostly a **formatter** over data the engine already computes, not
   new scoring logic — write it as a `format_explanation(evaluation: RuleEvaluation) -> str`
   (or structured dict) function, reusable by whatever surfaces it to a reviewer later (explicitly
   out of scope to build that reviewer UI here — see below).

### Out of scope

- **Deployment** (meeting notes' Step 6: scheduling the job, staging pass, prod rollout with
  batch-volume/match-rate/score-distribution monitoring). `patient-matching` has no deploy target
  and "no deploy ceremony" by design (every session ends in a PR merged to `main`, per
  `conventions.md`) — deployment is Phase 2, production-facing work that belongs in the production
  matching service's feature-flag/shadow-mode infrastructure (handoff §4.4 item 6-7), which has no
  session-doc convention of its own yet. Track as its own, not-yet-authored planning effort, not a
  task here.
- **The final written analysis for the lead engineer and repo maintainer** (meeting notes' Step
  7). This session's report + Execution notes are the raw material; the polished writeup is a
  human deliverable, not gated by this session's Definition of Done.
- **Setting the numeric agreement/precision/recall acceptance threshold.** Explicitly unresolved
  per the meeting notes' own gap list. `NEEDS HUMAN DECISION — lead engineer`: no threshold
  exists yet; this session reports the numbers, it does not decide what counts as "good enough."
- **Whether legacy is "ground truth" or merely "baseline"** for the purposes of the *external*
  writeup's framing. `NEEDS HUMAN DECISION — lead engineer`: affects how results get presented
  externally, not how this session computes them (this session always frames results as
  agreement-rate, per Step 3's own reasoning, regardless of how that question is later answered).
- Resolving the session 6 / v3.3.1-3.3.6 addenda re-scope question, or building session 6 itself
  — separate, already-flagged gap (see "Upstream sessions").
- Any change to Table 2 rules, P(collision) values, or `MatchingEngine.match()`/`evaluate_pair()`
  — this session evaluates the engine as-is, same principle as session 3.
- Fixing `InMemoryBackend.search()`'s scaling behavior — not invoked here; this session, like
  session 3, drives `evaluate_pair()` directly on precomputed pairs.

## Tasks

1. **Resolve both `NEEDS HUMAN DECISION` items in "Upstream data/system dependencies" and
   Task 3's adjudicator question with the lead engineer** before writing comparison code, per
   `conventions.md`'s protocol step 4. Record answers in *Execution notes*.
2. **Confirm session 4 is in `completed/`** (not just `in_review/`) before branching. If it
   isn't yet, stop per the "start the next session" protocol rather than re-implementing its
   query logic here.
3. **Add the legacy dependency** (per Task 1's resolution) and write
   `evaluation/legacy_comparison.py`'s batch-loading + dual-scoring + diff-table logic (Scope
   item 1).
4. **Wire `rule_eval.compare()`** with the legacy engine as baseline (Scope item 2), extending
   `format_report()`'s header text to flag non-ground-truth baselines explicitly.
5. **Build the disagreement bucketer** (Scope item 4) as pure, unit-testable functions over
   `PatientFields` diffs.
6. **Build the hand-adjudication sample emitter** (Scope item 3), gated on the adjudicator
   question being resolved.
7. **Build the explanation formatter** (Scope item 5) over existing `RuleEvaluation` data.

## Unit tests required

File: `evaluation/test_legacy_comparison.py` (new, sibling to `evaluation/test_onc_baseline.py`).
Real Databricks/legacy-service access can't be unit-tested locally — test the pure logic:

```python
import pytest

class TestDisagreementBucketing:
    """One behavior, one test body, many named cases - pytest.mark.parametrize, per
    conventions.md's testing-structure section."""

    @pytest.mark.parametrize(
        "query_first_names,candidate_first_names,expected_bucket",
        [
            ({"robert"}, {"bob"}, "nickname_diminutive"),
            ({"katherine"}, {"kate"}, "nickname_diminutive"),
            ({"jon"}, {"john"}, "typo_transposition"),
        ],
    )
    def test_bucket_classification(self, query_first_names, candidate_first_names, expected_bucket):
        # Exact function signature depends on Task 5's PatientFields-diff shape, resolved at
        # implementation time - this table of cases is the contract, not the call signature.
        ...

    def test_missing_dob_buckets_as_dob_conflict_not_typo(self):
        ...

    def test_every_disagreement_gets_exactly_one_bucket(self):
        """No pair should be unclassified or double-counted across buckets."""
        ...


class TestExplanationFormatter:
    def test_format_explanation_includes_threshold_and_contributing_fields(self):
        ...

    def test_format_explanation_never_includes_raw_phi_values(self):
        """Only field names/outcomes/scores - never the actual name/DOB/etc. values,
        per the PHI guardrail."""
        ...


class TestComparisonReportFraming:
    def test_report_header_flags_non_ground_truth_baseline(self):
        """When baseline_name references a live system (not a labeled dataset), the
        formatted report text must say so explicitly - Step 3's agreement-vs-precision
        distinction."""
        ...
```

## Validation (definition of "resolved")

- [ ] Both `NEEDS HUMAN DECISION` items (legacy-dependency mechanism, adjudicator identity) are
      resolved and recorded in *Execution notes* before any comparison code runs against real
      data.
- [ ] Session 4 is confirmed `completed/` before this session's harness code depends on its
      notebook.
- [ ] `evaluation/legacy_comparison.py` produces a diff table (agreements / new-only /
      legacy-only) from a real batch, with no raw PHI values committed anywhere in this repo.
- [ ] The `ComparisonReport` this session produces explicitly labels its metrics as
      agreement-rate against a non-ground-truth baseline, not precision/recall in the Tier-1
      sense.
- [ ] Every disagreement in the sample is classified into exactly one of the six buckets, each
      with a count and a tune/acceptable/legacy-wrong call.
- [ ] The explanation formatter's output never includes raw field values (name/DOB/etc.), only
      field names, outcomes, scores, and the threshold — verified by
      `test_format_explanation_never_includes_raw_phi_values`.
- [ ] **Two distinct completion states, don't conflate them:** (a) the harness itself works end
      to end against whatever rule set currently exists — achievable regardless of session 6 —
      and (b) the comparison numbers are being treated as the go-live evidence, which requires
      session 6 (+ any addenda follow-up) to also be `completed/` first. This session can reach
      `completed/` on (a) alone; *Execution notes* must state plainly which state was reached and
      not imply (b) if only (a) is true.
- [ ] `make tests` is green; the new tests specifically pass via
      `uv run pytest evaluation/test_legacy_comparison.py -v`.
- [ ] `make run-pre-commit` is clean; `ruff check evaluation/` and `mypy evaluation/` run
      manually and pass (excluded from the automated pre-commit gate, not exempt from the
      standard — per `conventions.md`).

## Open questions

- **`NEEDS HUMAN DECISION — lead engineer`** (stated above): whether `patient-matching` may take
  an eval-only dependency on the legacy production matching engine to produce legacy comparison
  output in-process. Recommended default: yes, as a pinned eval-only extra matching whatever
  version is actually live in prod at execution time.
- **`NEEDS HUMAN DECISION — lead engineer`**: who adjudicates the hand-adjudication sample (the
  lead engineer or the reviewing team) — they need advance notice.
- **`NEEDS HUMAN DECISION — lead engineer`**: the numeric agreement/precision/recall acceptance
  threshold for go-live. No recommended default given — this is a business/clinical-risk call,
  not one the session author should guess at.
- **`NEEDS HUMAN DECISION — lead engineer`**: whether to frame legacy as "ground truth" or
  "baseline" in the eventual external writeup. Recommended default for *this session's own*
  internal reporting regardless: always "baseline"/"agreement rate" language, per Step 3's own
  reasoning — never overclaim precision/recall against a non-ground-truth system. (The lead
  engineer's 2026-08-13 labeled-set direction below may make this moot for the internal report —
  worth re-asking once that's settled.)
- **`NEEDS HUMAN DECISION — lead engineer`** (updated 2026-08-14, was new 2026-08-13): does the
  labeled test-set approach (`Outside Record`/`Internal Record`/`IsMatch`, scoring both engines
  independently against it) replace Scope items 1-2's legacy-vs-new comparison, or run alongside
  it? **The simulation-methodology half of this question is now resolved — see session_9 and the
  2026-08-14 update above. The replace-vs-alongside half is still open.**

## Upstream sessions (must be completed first) — addendum, 2026-08-14

- **Session 9** (`docs/sessions/in_review/session_9.md`) — supplies the test-data simulation
  methodology this session's Task 3/4 were waiting on (`evaluation/mutations.py`,
  `evaluation/hard_negatives.py`, `evaluation/labeled_pairs.py`). Do not start Task 3/4 until
  session 9 is `completed/` and the replace-vs-alongside question above is resolved with the
  lead engineer.

## Execution notes

_(empty at authoring time; filled in by whoever executes the session)_
