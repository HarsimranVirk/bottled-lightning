# Refactor Plan — Deck Search & Pin Picker

| | |
|---|---|
| **Status** | BUILT — walkthrough pending |
| **Version** | v1 |
| **Date** | 2026-11-06 |
| **Decision register** | `docs/decisions-deck-picker.md` (v1, LOCKED 2026-11-06) |
| **Requirements** | `docs/FR-deviations.md` FR-10.12 |
| **Companions** | `docs/frontend-design-deviations.md` §3.2a, `docs/api-deviations.md` §5, `docs/data-model-deviations.md` §1.2 |

This is a frontend-only change. There is no database migration, no API cutover and no
backfill. The execution order below is the order the slices are announced and built.

## Phases

### Slice 1 — ordering helper (D-03, D-07, D-08)

- Add `orderDeckRows(rows, pinnedKeys)` to `frontend/src/deck.ts`:
  pinned rows in check order, then every remaining row in its existing order.
- Ignore unknown and duplicate keys; never duplicate a row.
- Add `frontend/src/deck.test.ts` cases: no pins, one pin, several pins, unknown key,
  duplicate key, unpinned order preserved.

**Acceptance:** the helper is pure, typed, and its tests pass without React.

### Slice 2 — picker component (D-01, D-02, D-04, D-06)

- Add `frontend/src/components/DeckPicker.tsx` using Salt `ComboBox` with
  `multiselect`; options are the deck rows, selected keys render as pills, and a
  **Clear** button unpins all.
- Add `frontend/src/components/DeckPicker.test.tsx`: typing filters options, checking
  an option reports the selected keys, unchecking removes it, Clear empties the
  selection, and an empty option list disables the control.

**Acceptance:** the component is controlled and fetching-free; its options are stable
and only deck rows appear.

### Slice 3 — page and deck integration (D-03, D-04, D-05, D-07, D-08, D-09)

- `DeviationsPage`: own the pin list (key plus row epoch), derive the live keys so a row
  that left the deck drops its pin, compute `orderedRows` with `orderDeckRows`, fetch the
  top card's detail from the ordered rows, drop a pin when its decision succeeds, and
  pass ordered `rows` plus natural `pickerRows` to the deck.
- `DecisionDeck`: render `DeckPicker` above the active card; pass selection and the
  selected callback through.
- Extend `DecisionDeck.test.tsx` and add page coverage if the existing test harness
  supports it: pinning changes the active card immediately, unchecking restores it, and
  the tallies/buttons remain unchanged.

**Acceptance:** checking a deviation makes it the active card with no network request;
the detail query follows it; accepting or skipping it drops the pin; an empty deck
renders no picker.

### Slice 4 — close-out

- Run the gate: `ruff check app/ frontend/`, `mypy --strict app tests`,
  `npm --prefix frontend run typecheck`, `npm --prefix frontend run test`.
- Update `docs/frontend-design-deviations.md` Slice H to `done`, write
  `docs/guide-deck-picker.md`, move the ledger row to `review`, and hold the live
  walkthrough.

## Cutover

No runtime cutover: the frontend bundle is the only artefact. Building the frontend and
restarting the app activates the picker. There is no server state to migrate.

## Rollback

Revert `DeckPicker.tsx`, its tests, the `orderDeckRows` helper and the two integration
sites; the deck then renders the server rows directly as it does today. No data is lost
because pins were never persisted. The docs return to their pre-change versions and the
decision register gains a dated amendment.
