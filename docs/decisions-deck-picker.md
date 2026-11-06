# Decision Register — Deck Search & Pin Picker

| | |
|---|---|
| **Status** | LOCKED |
| **Version** | v1 |
| **Date** | 2026-11-06 |
| **Locked** | 2026-11-06 |
| **Approved by** | HarsimranVirk (user) |
| **Scope** | The Deviations Z02 review deck's search-and-pin control: selecting deviations, ordering them, and the boundary between frontend state and the server |
| **Companions** | `docs/FR-deviations.md` (v5.26), `docs/frontend-design-deviations.md` (v4.11), `docs/data-model-deviations.md` (v3.9), `docs/api-deviations.md` (v2.11), `docs/class-design-deviations.md` (v4.9) |

## Context

The deck currently presents every decidable item in the server's `last_seen` order and
offers no way to jump to a particular deviation. The operator asked for a control that is
both a search field and a dropdown, with a checkbox per deviation, so a selected
deviation can be brought to the top of the deck immediately.

The change is presentation-only. It reorders rows the page already fetched, writes no
decision, and does not alter extraction, submission, retention or any persisted table.
This register records the choices that keep it that way.

## Register

| ID | Decision (one sentence) | Rejected alternative | Why | Touches | Status |
|---|---|---|---|---|---|
| D-01 | The picker is one Salt `ComboBox` with `multiselect`, so the same control is a text field and a dropdown and Salt's multiselect `Option` supplies the checkbox glyph. | A separate `Input` above a `Dropdown` (two controls), or a hand-built popover with a custom checkbox list. | The ComboBox is the Salt component for typeahead plus multi-selection, and its multiselect option already renders the required checkboxes. A bespoke overlay would break the "Salt components only, layout-only CSS" rule (FR-9.14). | `frontend/src/components/DeckPicker.tsx` | locked |
| D-02 | The text input filters the dropdown by deviation key, case-insensitively; checked keys also appear as removable pills and a **Clear** button unpins all of them. | Search over descriptions, customer names or amounts; no clear action. | The key is the deck card's identity and every option is labelled with it, so key filtering is unambiguous without loading detail payloads. Pills and Clear make an active pin visible and reversible without reopening the menu. | `frontend/src/components/DeckPicker.tsx` | locked |
| D-03 | Pinned rows move to the top immediately and multiple pins keep the order in which they were checked (first checked first). | Latest checked first, or preserving the natural deck order among pinned rows. | "First checked first" lets the operator build a deliberate review queue; the first pin satisfies the immediate "bring it to the top" requirement. | `frontend/src/deck.ts`, `frontend/src/pages/DeviationsPage.tsx` | locked |
| D-04 | Pinning only reorders the deck; it never filters out unselected rows, and the tallies, completion card, decision rules and keyboard shortcuts are unchanged. The picker is not rendered when the deck has no rows. | Show only the selected deviations until the selection is cleared; use the picker as a filter. | The deck is the queue of all remaining work. Filtering would hide pending items and make the completion/tally state claim work is done while cards still exist. | `frontend/src/components/DecisionDeck.tsx`, `frontend/src/pages/DeviationsPage.tsx` | locked |
| D-05 | Pins are ephemeral React state in `DeviationsPage` and reset on reload; they are not written to the database, `localStorage`, or the URL. | Persist the pin/order on the server, or remember it in the browser. | A pin means "review this one next", not a durable work allocation. Server persistence would add API and schema surface, and browser persistence could silently reorder a later session for no benefit. | `frontend/src/pages/DeviationsPage.tsx` | locked |
| D-06 | The dropdown's options are only the decidable/pending rows currently loaded in the deck (the deck fetches up to 500); decided, absent and purged items are reached through History. | Search all deviations through the server, including decided or unloaded items. | Selecting a decided item would require undo or a read-only card and a new API search path. The requested behaviour is to jump within the current deck, so the already-fetched rows are sufficient and need no server call. | `frontend/src/components/DeckPicker.tsx`, `frontend/src/pages/DeviationsPage.tsx` | locked |
| D-07 | `DeviationsPage` owns `pinnedKeys`, a pure `orderDeckRows` helper in `deck.ts` computes the card order, and `DecisionDeck` receives both the ordered `rows` for the card and the natural `pickerRows` for stable option order. | Keep the selection inside `DecisionDeck` and reorder there. | The page fetches the top card's detail by key; if the deck reordered privately, the detail request and the visible card could disagree. Stable picker options also stop the overlay list jumping while the operator checks several items. | `frontend/src/deck.ts`, `frontend/src/pages/DeviationsPage.tsx`, `frontend/src/components/DecisionDeck.tsx` | locked |
| D-08 | A pin is dropped when its row leaves the deck or its decision succeeds; unknown or duplicate keys are ignored when ordering so a stale key can never show a phantom pill or duplicate card. | Keep pins until the page reloads and let them reappear if the same key returns. | A key that is gone from the deck (accepted, skipped, or absent from Salesforce) has nothing to reorder. Pruning keeps the control honest and prevents a returning `needs_review` item from silently jumping the queue. | `frontend/src/deck.ts`, `frontend/src/pages/DeviationsPage.tsx` | locked |
| D-09 | The change adds no endpoint, query parameter, table, migration or generated TypeScript type; the detail request follows the ordered top card and the tallies keep counting every fetched row. | Add a server-side `pinned`/custom order field, or a new deck endpoint. | The ordering is per-operator and per-session, so persisting or server-computing it would add contract surface for no user-visible gain. Client-side reordering is reversible and leaves the API untouched. | `frontend/src/pages/DeviationsPage.tsx`, `frontend/src/components/DeckPicker.tsx` | locked |

## What stays the same

- `GET /api/deviations` keeps its `last_seen` ordering and its response shape; the server
  never learns about a pin.
- Decisions, field proposals, submit jobs, history, the auth gate and the keyboard
  shortcuts are untouched. Pinning an item does not decide it and does not write to
  Salesforce.
- The tallies and the deck-complete card still describe every row in the fetched deck,
  not only the pinned subset.
- No row is duplicated: a pinned row leaves its normal position and returns to it when
  unselected.

## Amendments

None. Amendments are appended here with a date and the files/behaviour they invalidate;
locked rows are never edited in place.
