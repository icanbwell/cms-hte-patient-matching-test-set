# icanbwell - AI Agent Instructions

> **Scope:** Organization-wide baseline. Applies to all repositories in the icanbwell GitHub organization.
> **Owner:** Enterprise Architecture (@icanbwell/enterprise-architecture)
> **Precedence:** This file sets the floor. Repo-level instruction files (copilot-instructions.md, CLAUDE.md) may add stricter requirements or repo-specific context but must not weaken or contradict these directives. If there is a conflict, this baseline wins. Repo-level overrides may only tighten rules, never loosen them. Any true exception requires EA approval with documented rationale, scope, owner, JIRA ticket, and expiry date.
>
> **Context-budget note:** This file loads in full on every session, in every repo. Keep it to hard, always-applicable constraints. File-type-specific detail (OOAD/SOLID, testing, event contracts, operational patterns) lives in `.claude/rules/*.md` and loads only when Claude touches a matching file. Vendor/pattern-specific guidance lives in `.claude/skills/*` and loads only when invoked. Don't re-add prose here that a rule or skill already covers.

---

## Platform Identity

b.well is a cloud-native, multi-tenant, microservice-based, event-driven healthcare data platform under HIPAA, FHIR-native, exposed via a federated GraphQL gateway. Services are independently deployable, communicate asynchronously by default, and own their private datastores. The FHIR server is the system-of-record, accessed only via approved APIs and contracts. Cross-service workflows use sagas and event choreography, never distributed transactions or synchronous orchestration chains.

Code that violates tenant isolation, leaks PHI, bypasses the gateway, introduces unapproved technology, or creates tight coupling between services is incorrect regardless of whether it compiles and passes tests.

---

## Design-Time Quality Kit & Knowledge Substrate

The worst failures happen at **design time**, before code review can catch them. b.well maintains a tool-neutral **knowledge substrate** — the single source of truth for rules, patterns, and gradeable review rubrics — and a design-time kit that uses it. Reach for these instead of re-deriving (or reinventing) an approach:

- **Authoring a design?** Use the **`tech-design`** skill — it walks you through the rubric so the design passes EA review the first time.
- **Reviewing a design?** Use **`/tech-design-review`** — it grades a TDD/FDR against the rubric and returns concrete, cited gaps.
- **Rubrics** (`rubrics/`) — what "good" means, gradeably: `tech-design-rubric.md`, `fhir-feasibility-rubric.md` (conformance + IG conformance + resource-explosion feasibility), `api-design-rubric.md`.
- **Patterns** (`patterns/`) — named, blessed shapes to appeal to by name, not reinvent: `orchestrated-long-running-work`, `temporal-coalescing`, `event-key-and-partition-design`.
- **Decision guides** (`decision-guides/`) — e.g. `datastore-selection.md` (including *do not put run/FSM state on a FHIR `Task`*).
- **Standards** (`standards/`) — canonical rules, e.g. `events.md` (Kafka/event conventions; supersedes the inline `patient.updated`-style examples elsewhere in this file).
- **Reference architectures** (`reference-architectures/`) — annotated real exemplars (the DEQM orchestrator; a good API/SDK).

Overview + the stable-anchor citation convention: `docs/knowledge-substrate.md`. Cite substrate content by anchor (e.g. `standards/events.md#std-events-partition-key`), never by line number.

---

## Hard Non-Negotiables

- **Event-driven first.** Default to async via Kafka + CloudEvents. A sync service-to-service call needs a documented reason (immediate response required, data can't be pre-materialized). See the `sync-to-async` skill.
- **Choreography over orchestration.** Services react to events; no cross-domain god orchestrator, no request-reply chains disguised as async. Saga detail (compensation, idempotency, ordering): `.claude/rules/event-contracts.md`.
- **Service data ownership.** Never read from or write to another service's private datastore. Consume owned data via events or the owning service's public API.
- **Tenant isolation.** Mandatory on every persistence model and query path — correctness, not best-effort. If you can't confirm tenant filtering on a new data access path, flag it.
- **FHIR-native modeling.** Use standard FHIR resources before inventing schemas. New resource usage or structural changes need an FDR. Extensions are a last resort requiring review. See the `fhir-design` skill.
- **Federated gateway only.** Client-facing capabilities go through the federated graph — no point-to-point service APIs bypassing it. Public API/schema changes are additive-only and need a Tech Design Review. See the `api-design-guardian` skill.
- **No unapproved technology.** Check `policies/approved-tech.yaml` before adding any datastore, cache, queue, search engine, observability sink, vendor, or significant library. Not listed → Tech Design Review. Infra changes go through Terraform PRs, never manual console steps.
- **Eventually consistent by default.** Don't design cross-service reads/UX assuming immediate consistency. Strong consistency belongs inside a single bounded context.

Detailed Kafka usage patterns, schema evolution rules, and forward-compatibility requirements: `.claude/rules/event-contracts.md`.

---

## Code & Design Conventions

OOAD, SOLID, hexagonal-boundary, DRY/idempotency/minimal-diff, and modern-idiom (Java/Python/TypeScript) conventions apply to source files and load automatically via `.claude/rules/ooad-solid.md`.

Testing discipline (parameterized tests, AAA, mock-only-at-boundaries, contract tests, tenant-isolation-in-integration-tests) loads automatically for test files via `.claude/rules/testing.md`.

Timeouts/retries, circuit breakers, N+1/full-scan awareness, and observability requirements load automatically for service source files via `.claude/rules/operational.md`.

Follow whatever linter/formatter/static-analysis config exists in the repo — these rules cover architectural judgment linters can't catch, not style.

---

## Security

**PHI/PII:** Never in logs, test fixtures, example payloads, comments, commit messages, PR descriptions, or screenshots. Use synthetic/redacted data.

**Auth:** OAuth/OIDC only. No custom auth schemes, no hardcoded credentials, tokens, or secrets anywhere.

---

## Governing Processes

- **New technology, vendor, or pattern; public API changes; cross-team impact:** Tech Design Review with EA (JIRA ticket, type "Tech Design Review", linked design doc).
- **FHIR data modeling decisions:** FDR process — FDR Confluence page + FHIR SME approval.
- **Non-trivial repo-local implementation decisions** (library choice, caching strategy, new pattern in the repo): ADR in the repo's `adrs/` directory, MADR format (https://adr.github.io/madr/). Show the options considered, not just the conclusion.

Unsure if a change needs review? "Is it NEW?" — new technology, new vendor, or a pattern not previously used in this codebase → needs EA review.

---

## Agent Behavior

- **Plan before acting.** Before non-trivial changes, restate which constraints apply (tenancy, PHI, contracts, dependencies) and flag if it touches tenant isolation, PHI, public contracts, event schemas, or a new dependency.
- **Diagnose before escalating.** Read logs and check the obvious (right token/var, remote configured, did it actually fail vs. warn) before concluding something needs org-admin intervention or new infrastructure.
- **Respect system constraints.** If branch protection blocks a merge, CI is failing, or a process needs approval, don't repeatedly offer workarounds. If told an action is blocked, don't re-propose it with different wording.
- **Don't guess commands.** Use the repo's actual build/test/lint commands (Makefile, package.json, build.gradle, Pipfile). Say so if unclear.
- **Don't introduce dependencies casually.** Check `approved-tech.yaml` first; popularity isn't approval.
- **Reference governing artifacts.** Cite the Tech Design Doc/FDR/ADR/AsyncAPI spec in the PR when a change touches a public API, event contract, or cross-service behavior.
- **Flag what looks wrong.** Missing tenant filtering, PHI in fixtures, a vendor name baked into business logic, a sync call where an event belongs — flag it, don't silently work around it.
- **Code ownership.** No "Co-Authored-By", "Generated by", or other AI attribution in commits, PRs, or comments. The author on the commit is the owner.

---

## Branch Naming

Format: `XX-PROJ-123` (initials-JIRA project-ticket number), e.g. `WF-EA-2136`. No `feature/`, `fix/`, `bugfix/`, `hotfix/` prefixes — the JIRA key carries the context.

## Commit Messages

Every commit starts with a JIRA issue key, no conventional-commit prefixes: `EA-789 add FHIR resource validation`. Exceptions: automated dependency bumps (`Bump version`, `build(deps): ...`) and git operations (`Merge`, `Revert`, `Reapply`). Commits are validated automatically. No ticket for your work? Create one before committing.

---

## icanbwell Infrastructure

Atlassian: https://icanbwell.atlassian.net/ · Slack workspace: icanbwell · Common JIRA projects: EA, HP, PAY, RNGR.

Use the `atlassian:*` skills (ticket creation/triage, status reports, Confluence search) and `slack:*` skills (search, digests, announcements) for these operations rather than calling MCP tools ad hoc — they already encode the correct cloudId lookup, project conventions, and troubleshooting steps.

---

## Code Style

Follow whatever linter, formatter, and static analysis configuration exists in the repo. Don't duplicate what automated tooling already enforces — these instructions are for architectural and design decisions linters can't catch.
---
<!-- SYNC:PRESERVE-BELOW (do not edit this line -- content below survives the AGENTS.md sync) -->

## Repo-Specific: cms-hte-patient-matching-test-set

<!-- Migrated from this repo CLAUDE.md by the EA instruction sync. -->


This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

This repo produces a portable, algorithm-agnostic **test dataset** for validating patient-matching
algorithms against the CMS HTE Patient Matching Specification. It was split out of a private
reference matching implementation and, as of session 13, has **no runtime dependency on that or
any matching engine** — it only generates and exports test data. Everything in `evaluation/`
produces FHIR `Patient` JSON and JSON Lines manifests; nothing here scores a matching algorithm
itself.

Read `evaluation/DESIGN.md` and `evaluation/SYNTHETIC_DATA_SETUP.md` first for the full picture;
`evaluation/cases/README.md` explains how a consumer (any org, any language) uses the generated
files.

## Commands

```
uv sync              # setup (make setup)
make tests            # uv run pytest . — this is CI's actual gate (build_and_test.yml)
make lint             # uv run ruff check .
make typecheck        # uv run mypy evaluation (notebooks/ has no .py files left)
make run-pre-commit   # ruff check --fix + ruff format, whole repo
uv run pre-commit install   # one-time: get the above as a real git hook
```

Run a single test file or test:
```
uv run pytest evaluation/test_mutations.py -v
uv run pytest evaluation/test_mutations.py::test_some_case -v
```

Run the generation/export scripts directly (all default to one ONC shard, sampled down — see
"Memory & scale" below before changing that):
```
PYTHONPATH=. uv run python evaluation/labeled_pairs.py             # demo: prints pair counts
PYTHONPATH=. uv run python evaluation/export_test_dataset.py        # writes evaluation/cases/sample_labeled_pairs.jsonl
PYTHONPATH=. uv run python evaluation/export_population_dataset.py  # writes population_{candidates,queries}.jsonl
SAMPLE_SIZE=20000 PYTHONPATH=. uv run python evaluation/labeled_pairs.py   # override sample size
```

Generate from the full 9-shard ONC dataset (~1,000,000 records), one shard at a time rather than
concatenating all 9 into one in-memory list — see "Memory & scale" below:
```
make generate-full-dataset   # PYTHONPATH=. uv run python evaluation/export_full_onc_dataset.py
# writes evaluation/cases/full_labeled_pairs.jsonl, full_population_candidates.jsonl,
# full_population_queries.jsonl — deliberately not the same filenames as the sample_/population_
# files above, since those are the committed, curated sample consumers already depend on.
```

Lint/typecheck just the files you're touching:
```
uv run ruff check evaluation/mutations.py evaluation/hard_negatives.py
uv run mypy evaluation/mutations.py evaluation/hard_negatives.py
```

## Architecture

### Generation pipeline (`evaluation/`)

All test data derives from the public ONC 2017 Patient Matching Algorithm Challenge dataset
(`evaluation/fixtures/onc/*.csv`, ~1M rows across 9 alphabetically-sharded files) via this repo's
own mutation/mining/construction code — no real member-organization data, no de-identification
step (ONC's data is already public/synthetic).

- **`onc_loader.py`** — loads ONC CSV shards into FHIR `Patient` dicts. No streaming; loading all
  9 shards materializes all ~1M records in memory at once. **Every EnterpriseID in this
  vendored copy is unique, but the same person can appear under more than one ID (shared name+DOB,
  and in some cases SSN).** Never treat "different ID" as "different person": every negative miner
  and the population distractor top-up exclude pairs for which
  `identity_guard.is_possible_same_person` is true. True-match clusters are built by this repo's own
  generators.
- **`mutations.py`** — single-character-edit ("fuzzy-eligible") variants of a record: exactly one
  edit per call, composed as `(original, variant, is_true_match=True)`.
- **`hard_negatives.py`** — mines *genuinely distinct* real ONC records that coincidentally collide
  on high-signal fields (shared ZIP+DOB). Deliberately not mutation-based — mutating a record and
  calling it "a different person" would only test a matcher's own fuzzy tolerance, not reality.
- **`normalization_edge_cases.py`** — diacritic-folded / punctuation-varied name variants that CMS
  spec §V.A requires normalization to fold into an exact match (distinct from `mutations.py`'s
  fuzzy-tolerance variants).
- **`special_populations.py`** — high-risk non-match categories (shelters, nursing facilities,
  correctional institutions, multi-generational households, etc.). Some are mined (real coincidental
  collisions); institutional categories are constructed by overwriting only the address on two
  already-distinct real identities with a fabricated, clearly-synthetic address
  (`"SYNTHETIC TEST ADDRESS"`, reserved `000xx` ZIP block) — the underlying identities are never
  fabricated.
- **`scenarios.py` / `drift_profile.py` / `drift_mutations.py` / `placeholders.py`** — the
  per-patient true-match scenario registry shared by both tiers (session-14 scenarios plus surname
  change, address move, phone/email churn, placeholder values, optional gender drift), its
  placeholder emission rates, the donor-backed mutators, and the placeholder catalog (also the
  pairwise-only placeholder-collision non-matches). `audit.py` / `release_gate.py` gate the result.
- **`population_targets.py` / `population_sampling.py` / `household_assignment.py` / `export_realistic_dataset.py`** —
  cited age-band and household targets, the age-stratified sampler (all ONC shards, one at a time),
  household assignment with shared addresses and contacts, and the generator for the parallel
  `realistic_*` release-candidate files (git-ignored; the committed files are never overwritten).
  `make generate-realistic-dataset` / `make audit-realistic`.
- **`prevalence_estimates.py`** — real, cited public-source prevalence estimates (Census/CDC/Pew/
  peer-reviewed) per test-case category, for optional real-world-weighted aggregation. Every entry
  is either a cited estimate or an explicit `has_public_estimate=False` placeholder — never a
  guessed number.
- **`labeled_pairs.py`** — assembles all of the above into per-provision `(source, target,
  is_true_match)` triples; the shared generation core everything else builds on.
- **`population_cases.py`** — regroups the same generation logic into the second test kind: one
  query patient against a candidate pool (default 40), with a possibly-empty
  `expected_match_ids` set. Reuses `labeled_pairs.py`'s generation rather than duplicating it.
- **`export_test_dataset.py`** / **`export_population_dataset.py`** — materialize the above as the
  portable JSON Lines manifests under `evaluation/cases/`.
- **`rule_eval.py`** — a separate, rule-agnostic statistical harness (Bayesian before/after
  comparison, stratified splitting, SHIP/REJECT/NEEDS-MORE-DATA verdicts) for anyone comparing two
  matching rules against a labeled gold set. Demoed in `notebooks/rule_eval_demo.ipynb`.

Every generator function is exercised by a same-named `test_*.py` file in `evaluation/`.

### The two output tiers (`evaluation/cases/`)

| Tier | Files | Answers | Valid metrics |
|---|---|---|---|
| **Per-provision pairs** | `sample_labeled_pairs.jsonl` | "Does this algorithm correctly implement this specific spec provision?" Deliberately over-samples rare/high-risk categories for statistical power — not representative by design. | Recall, FPR only |
| **Population query** | `population_queries.jsonl` + `population_candidates.jsonl` | "When this algorithm searches a realistic population, does it return the right people?" Naturally representative (real duplicate cluster + mostly-random distractors). | Precision, recall, FPR, FDR, F1, accuracy |

**Never compute precision/FDR/F1/accuracy over the per-provision tier** — its should-match ratio is
a generation-parameter artifact, not a real base rate. Use the population tier for those. See
`evaluation/cases/README.md`'s "Frequency and real-world representativeness" for the full rationale,
and its "Option A"/"Option B" sections for runnable scoring snippets any language/algorithm can
follow against these files.

### Memory & scale — read before raising `SAMPLE_SIZE`/`POOL_SIZE` or passing multiple shards

Loading the full ONC dataset and transforming it has crashed a cluster before. `onc_loader.py` has
no streaming (one Python list of ~1M dicts if given all 9 shards), and `generate_raw_pairs()` /
`mine_shared_address_hard_negatives()` assume a fully-materialized in-memory list — they add their
own overhead on top of whatever step 1 already allocated. All `__main__` scripts default to **one
shard, sampled down** for exactly this reason. If you need full-dataset scale, express it as a
distributed job (Spark), not a single-process Python list — see `SYNTHETIC_DATA_SETUP.md`'s
"Memory & scale" section for the full guidance.

## Conventions

- `from __future__ import annotations` at the top of every module; `typing.Dict`/`List`/`Set` over
  builtin generics is the established codebase-wide convention (ruff's `UP006`/`UP035`/`FURB192`
  are deliberately ignored in `pyproject.toml` rather than rewriting every existing file).
- Field values are copied through from the ONC CSVs as-is — this repo's generation pipeline does
  **not** normalize case/punctuation (that step was intentionally dropped in session 13 along with
  the removed matching-engine dependency). Any consumer must apply its own normalization before comparing.
- Every generated case's `rationale` field traces to a specific category/provenance — never a
  black box (Design Principle 2 in `DESIGN.md`/the workgroup Doc).
- `docs/sessions/` narrates the design history chronologically (`completed/` and `pending/`) —
  check there before assuming something is unimplemented; `session_13.md` in particular explains
  the removed matching-engine dependency and how that shapes the current scope.
