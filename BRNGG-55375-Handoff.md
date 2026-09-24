# Handoff — BRNGG-55375 QR Code / DeCA Compliance Epic

**Date:** 2026-08-23 (updated same day after Phase 1). **Purpose:** let a fresh session continue this work without re-deriving anything already established.

## Start here

This session's auto-memory already has a full running log of this epic — read it first:
`/Users/moslemasaad/.claude/projects/-Users-moslemasaad-bringg/memory/project_brngg_55375_qr_code_epic.md`
(indexed in `MEMORY.md` as "BRNGG-55375 QR Code Epic"). It covers the story map, every corrected assumption, both locked-in architecture decisions, and the Phase 0 review/fixes — this handoff doc does **not** repeat that content, only points to it and adds what's changed since the last memory write (the branch/commit) plus what to do next.

## Where the design lives (don't re-derive — read these)

All in `/Users/moslemasaad/bringg/`, working tree:
- `BRNGG-55375-QR-Code-Tech-Design.md` — the master design doc, includes the full E2E Mermaid sequence diagram (§ near top) and the ER diagram + worked example (§1).
- `BRNGG-55375-QR-Code-Implementation-Plan.md` — the ordered, phase-by-phase build checklist.
- Per-story implementation docs (each has a "Read first" correction/decision callout at the top — read those before the rest of the file):
  - `BRNGG-57146-S2-Documents-Schema-And-Read-Path.md` (hagmonia — schema done, read endpoints not started)
  - `BRNGG-55375-ServiceData-Document-Models-Prereq.md` (service-data — not started, unblocks the write path)
  - `BRNGG-57148-S4-Generation-Trigger-And-Write-Path.md` (hagmonia-js — not started)
  - `BRNGG-57147-S3-Render-Mocked-PDF.md` (templates-service — not started)
  - `BRNGG-57656-S2.1-DocumentsReady-Webhook.md` (hagmonia-js — not started, payload envelope still open, see below)
- A pseudo-implementation file per phase above (same basenames + `-Pseudo-Implementation.md`) — near-final code sketches with the full flow diagram boxed to that phase's part. Start from these, not from scratch, when building each phase.

Jira: epic [BRNGG-55375](https://bringg.atlassian.net/browse/BRNGG-55375). All design decisions this session were also posted as dated comments on BRNGG-57146, BRNGG-57147, BRNGG-57148, BRNGG-57656, and a new prerequisite ticket BRNGG-57886 was created for the service-data work.

## What's actually built (real code, not just docs)

Phase 0 (hagmonia: `documents`/`document_runs` schema, `GeneratedDocument`/`DocumentRun` models, `documents_configurations` config columns + validator, specs) is done, reviewed by an independent fresh-eyes pass (which caught and fixed a real bug — see memory for detail), all 20 specs passing against a migrated test DB.

**Committed, pushed, and PR'd:** branch `BRNGG-57146-documents-schema-and-models` on `hagmonia`, pushed to `origin`, PR open at **[hagmonia#12740](https://github.com/bringg/hagmonia/pull/12740)** — not yet merged, not yet reviewed by anyone else as of this handoff.

**Phase 1 (service-data: `Document`/`DocumentRun` models) is done, in `service-data`** — `src/models/document.ts`, `src/models/document_run.ts`, barrel export in `src/index.ts`, plus `test/models/document.test.ts`/`test/models/document_run.test.ts`. All 4 new tests pass, and the full existing suite (1303 tests) still passes — run for real against this machine's live local Postgres/Redis, not just typechecked. Caught one real bug the two prior research passes and the pseudo-implementation doc both missed: `documents`/`document_runs` need an explicit `softDelete: false` override, since `service-data`'s `RedisCache` plugin defaults every model to `softDelete: true` and neither table has a `delete_at` column — full detail in memory. **Not yet done for Phase 1:** the version-bump PR + Jenkins publish, and bumping `hagmonia-js`'s dependency — deferred as cross-repo/CI steps, not needed until Phase 3 actually starts.

**Committed, pushed, and PR'd:** branch `BRNGG-57886-document-service-data-models` on `service-data`, single commit `3a6c2207`, PR open at **[service-data#1210](https://github.com/bringg/service-data/pull/1210)** — not yet merged, not yet reviewed by anyone else. **Unlike Phase 0, this has not had an independent fresh-eyes review pass** — worth doing (same as Phase 0 got) while the PR sits open.

## The two locked-in architecture decisions (full reasoning in memory + the S4 doc)

1. **Write path lives in hagmonia-js, not hagmonia** — hagmonia owns schema + reads only.
2. **Redlock (not `pg_advisory_xact_lock`)** for the idempotent-claim lock in S4, and **the "a failed generation never auto-retries" gap is accepted** for this build pass (confirmed via research that RabbitMQ never retries a failed handler in this stack, at any layer).

## Genuinely open — needs a human answer, not more research

- **The `documents_ready` webhook payload envelope (Option A vs B)** — whether ADEO needs just a run identifier or also per-order identifiers. This depends on a real-world sync between the user and Liel Armoza (escalated via a `#adeo_efti` Slack thread) that may or may not have happened yet by the time a new session picks this up — **ask the user for the outcome before building S2.1's exact payload**, don't guess.
- Whether cancelled tasks are included in S4's per-run task query (flagged, not decided).
- Whether a zero-task run should be skipped or generate an empty document (flagged, not decided).

## Suggested next action

Phase 1 is code-complete and tested but not committed or published. Two independent next steps, either is reasonable:
1. Get a fresh-eyes review of the Phase 1 diff (same pattern as Phase 0's review), then commit/push/PR it, following the `commit-push` skill convention.
2. Start Phase 3 (hagmonia-js write path, S4) design/build in parallel — it's the richest remaining phase (Redlock decision already made) — but it needs Phase 1 actually *published* (not just written) before hagmonia-js can depend on the new package version, so sequence the version-bump PR + Jenkins publish first if going this route.

## Suggested skills for the next session

- **`commit-push`** — this repo's convention (author as `moslem-asaad`, no Claude co-author trailer) — already used this session, keep using it for any further commits.
- **`review`** or a fresh subagent code-review pass (as done for Phase 0) — worth repeating for each subsequent phase before considering it done; it found a real, non-obvious bug last time (a `has_many` foreign-key derivation mistake) that an in-context self-review missed.
- **`to-issues`** or direct Jira updates — if new stories/subtasks are needed as work progresses, this session's convention was dated "🔄 Decided" comments on existing tickets rather than editing descriptions wholesale (to avoid corrupting the long original ticket text).
