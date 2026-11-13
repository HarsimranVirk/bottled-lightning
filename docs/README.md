# Docs index — the feature ledger

This folder holds reference design and operator docs (see `AGENTS.md` →
"Feature work: plan → review → implement"). They are written when a change is
big enough to need a record; they are not required for every change. The
ledger below records what exists and how far each feature got.

## Naming convention

| File | Written when | Purpose |
|---|---|---|
| `FR-<feature>.md` | plan | Requirements, scope, numbered `FR-x.y`, acceptance criteria |
| `class-design-<feature>.md` | plan | Classes, Protocols, seams, ownership |
| `data-model-<feature>.md` | plan | Tables, columns, keys, retention, migration |
| `api-<feature>.md` | plan | Endpoints, payloads, status/error cases, TS types |
| `decisions-<feature>.md` | plan → **lock** | Numbered `D-xx` register; the lock record |
| `refactor-plan-<feature>.md` | after lock | Phases, cutover, rollback — the execution order |
| `guide-<feature>.md` | after build | Short operator/developer guide (1–2 pages) |

The code walkthrough is **not** a document: it is a live discussion/review with
the agent after implementation, recorded only in the ledger. Do not create
`walkthrough-<feature>.md`.

Frontend-only design that predates this convention uses
`frontend-design-<feature>.md`; it is part of the class/API design record for
that feature.

## Ledger

Status values: `proposed` → `locked` → `building` → `review` → `done`. These
record how far each existing feature got under the old gate; new work only needs
a plan, a review, and small implementation slices.

| Feature | Status | Decision register | FR | Walkthrough (live) | Guide | Last updated |
|---|---|---|---|---|---|---|
| Job runtime — bounded waits, detailed logs, lease recovery | `review` — built, live walkthrough pending | `decisions-job-runtime.md` (v1, LOCKED 2026-11-07) | `FR-deviations.md` FR-7.2, FR-7.12–FR-7.14 (v5.31) | pending | `guide-job-runtime.md` | 2026-11-07 |
| Loan deviations (`deviations_z02`) | `review` — change C-1 built, walkthrough pending | `decisions-deviations.md` (v2, LOCKED 2026-11-06) | `FR-deviations.md` (v5.30) | pending | `guide-sync-recovery.md` | 2026-11-07 |
| LMS 2.0 contract approval gate | `review` — built, live submit/walkthrough pending | `decisions-lms2-approval.md` (v2, LOCKED 2026-11-06) | `FR-deviations.md` FR-6.17 (v5.29) | pending | `guide-lms2-approval.md` | 2026-11-06 |
| Deck search & pin picker | `review` — built, walkthrough pending | `decisions-deck-picker.md` (v1, LOCKED 2026-11-06) | `FR-deviations.md` FR-10.12 (v5.28) | pending | `guide-deck-picker.md` | 2026-11-06 |
| Approved history | `building` | missing — gap | — | not reviewed — gap | missing — gap | 2026-11-06 |
| Retention — jobs, logs, sync runs | `review` — built, walkthrough pending | `decisions-retention.md` (v2, LOCKED) | `FR-deviations.md` FR-8.6–FR-8.10 | pending | `guide-retention.md` | 2026-11-05 |
| Table UX — history links, resizable tables | `review` — built, walkthrough pending | `decisions-table-ux.md` (v2, LOCKED) | `FR-deviations.md` FR-8.11, FR-9.13, FR-9.20–FR-9.24 | pending | `guide-table-ux.md` | 2026-11-05 |
| Final action (Implement) | `review` — built, live test pending | `decisions-final-action.md` (v2, LOCKED) | `FR-deviations.md` FR-6.5–FR-6.7, FR-6.14, FR-6.16 | pending | `guide-final-action.md` | 2026-11-05 |
| Delivery — launchers, self-update, LAN access | `review` — built, walkthrough pending | `decisions-delivery.md` (v2, LOCKED) | `FR-delivery.md` FR-1–FR-6 | pending | `guide-delivery.md` | 2026-11-05 |
| Extraction recovery (late record URL) | `done` — superseded by the retry register | `decisions-extraction-recovery.md` (v1, SUPERSEDED 2026-11-12) | — | — | — | 2026-11-12 |
| Retryable incomplete extraction | `review` — built, walkthrough pending | `decisions-extraction-retry.md` (v1, LOCKED 2026-11-12) | `FR-deviations.md` FR-2.14, FR-3.5–FR-3.10, FR-6.18, FR-9.26 (v5.32) | pending | `guide-extraction-retry.md` | 2026-11-12 |
| Shared table filters | `review` — built, walkthrough pending | `decisions-table-filter-picker.md` (v1, LOCKED 2026-11-06) | `FR-deviations.md` FR-9.18, FR-9.19, FR-9.21 (v5.28) | pending | `guide-table-filter-picker.md` | 2026-11-06 |
| Workflow builders | `building` | missing — gap | — | not reviewed — gap | missing — gap | 2026-11-05 |
| Update-check resilience — failed checks retry, Check again | `review` — built, walkthrough pending | `decisions-updates.md` (v1, LOCKED 2026-11-07) | `FR-delivery.md` FR-2.2, FR-2.5, FR-2.6, FR-4.5 (v1.2) | pending | `guide-updates.md` | 2026-11-07 |
| Network profile — bounded submits/extractions, live per-machine setting | `review` — built, live submit pending | missing — gap | — | pending | `guide-network-profile.md` | 2026-11-13 |

Supporting docs that are not per-feature: `dev-tools.md`.

## Reading order for a finished feature

1. `guide-<feature>.md` — what it does and how to use it.
2. `decisions-<feature>.md` — what was locked and what was rejected.
3. Ask the agent for the live walkthrough — the traces, the non-obvious code,
   the failure paths, and the `D-id → code → test` reconciliation, discussed in
   chat.
4. The four design docs — the full reasoning.

If the guide and the ledger disagree with the code, the docs are stale and must
be fixed in the same change as the code.
