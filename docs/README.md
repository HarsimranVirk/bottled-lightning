# Docs index — the feature ledger

This folder is the source of truth for design decisions (see `AGENTS.md` →
"Feature work goes through plan mode" and "Implementation gate"). One row per
feature so it is always obvious what exists, what is locked, and what the code
actually does.

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
the agent after implementation, recorded only as `reviewed <date>` in the
ledger. Do not create `walkthrough-<feature>.md`.

Frontend-only design that predates the gate uses `frontend-design-<feature>.md`;
it is part of the class/API design record for that feature.

## Ledger

Status values: `proposed` → `locked` → `building` → `review` → `done`.
A feature is `done` only when the guide exists **and** the live walkthrough has
been reviewed with the user (recorded as a date, not a file).

| Feature | Status | Decision register | FR | Walkthrough (live) | Guide | Last updated |
|---|---|---|---|---|---|---|
| Loan deviations (`deviations_z02`) | `review` — change C-1 built, walkthrough pending | `decisions-deviations.md` (v2, LOCKED 2026-11-06) | `FR-deviations.md` (v5.30) | pending | `guide-sync-recovery.md` | 2026-11-07 |
| LMS 2.0 contract approval gate | `review` — built, live submit/walkthrough pending | `decisions-lms2-approval.md` (v2, LOCKED 2026-11-06) | `FR-deviations.md` FR-6.17 (v5.29) | pending | `guide-lms2-approval.md` | 2026-11-06 |
| Deck search & pin picker | `review` — built, walkthrough pending | `decisions-deck-picker.md` (v1, LOCKED 2026-11-06) | `FR-deviations.md` FR-10.12 (v5.28) | pending | `guide-deck-picker.md` | 2026-11-06 |
| Approved history | `building` | missing — gap | — | not reviewed — gap | missing — gap | 2026-11-06 |
| Retention — jobs, logs, sync runs | `review` — built, walkthrough pending | `decisions-retention.md` (v2, LOCKED) | `FR-deviations.md` FR-8.6–FR-8.10 | pending | `guide-retention.md` | 2026-11-05 |
| Table UX — history links, resizable tables | `review` — built, walkthrough pending | `decisions-table-ux.md` (v2, LOCKED) | `FR-deviations.md` FR-8.11, FR-9.13, FR-9.20–FR-9.24 | pending | `guide-table-ux.md` | 2026-11-05 |
| Final action (Implement) | `review` — built, live test pending | `decisions-final-action.md` (v2, LOCKED) | `FR-deviations.md` FR-6.5–FR-6.7, FR-6.14, FR-6.16 | pending | `guide-final-action.md` | 2026-11-05 |
| Delivery — launchers, self-update, LAN access | `review` — built, walkthrough pending | `decisions-delivery.md` (v2, LOCKED) | `FR-delivery.md` FR-1–FR-6 | pending | `guide-delivery.md` | 2026-11-05 |
| Extraction recovery (late record URL) | `review` — built, walkthrough pending | `decisions-extraction-recovery.md` (v1, LOCKED 2026-11-06) | `FR-deviations.md` FR-3.9 (v5.28) | pending | `guide-final-action.md` | 2026-11-06 |
| Shared table filters | `review` — built, walkthrough pending | `decisions-table-filter-picker.md` (v1, LOCKED 2026-11-06) | `FR-deviations.md` FR-9.18, FR-9.19, FR-9.21 (v5.28) | pending | `guide-table-filter-picker.md` | 2026-11-06 |
| Workflow builders | `building` | missing — gap | — | not reviewed — gap | missing — gap | 2026-11-05 |

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
