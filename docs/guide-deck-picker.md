# Guide — Deck Search & Pin Picker

| | |
|---|---|
| **Status** | Implemented |
| **Version** | v1 |
| **Date** | 2026-11-06 |
| **Feature** | Search-and-pin control on the Deviations Z02 review deck |
| **Design** | `docs/decisions-deck-picker.md` (v1, LOCKED), `docs/FR-deviations.md` FR-10.12, `docs/frontend-design-deviations.md` §3.2a |

## What it does

The deck has a **Find & pin deviations** field above the active card. It is both a
search box and a dropdown:

1. Type part of a deviation number (for example `486382`) to filter the options.
2. Open the dropdown and check one or more deviations. Each option carries a checkbox;
   checked deviations appear as removable pills in the field.
3. The first checked deviation becomes the active card immediately. Additional checks
   queue below it in the order you checked them.
4. Uncheck a pill (or the option) to return that deviation to its normal position.
5. **Clear** unpins everything and resets the search text.

Pinning is presentation-only. It does not accept, skip, submit, or write anything to
Salesforce. The tallies, **Skip** and **Accept & update** keep working exactly as before.

## How to use it

1. Start the app as usual:

   ```bash
   source .venv/bin/activate
   python -m app.main
   ```

   For frontend development, `npm --prefix frontend run dev` proxies `/api` to
   `http://localhost:8765`.

2. Open the **Deviations Z02** tab. The picker sits above the card, below the tallies.
3. Type a deviation number, check the one you want, and review it. Use **Shift+→** to
   accept or **Shift+←** to skip as before. The shortcuts are ignored while the picker
   input has focus.
4. Switch to **History** with the existing toggle if you need a decided deviation; the
   picker only lists cards currently in the deck.

The picker calls no endpoint of its own. The page still loads the deck from
`GET /api/deviations?…`; the selected keys only change the order of those rows in the
browser.

## Configuration and state

- **No environment variables** are added.
- **No database, table, or API change.** The pin list is React state in
  `frontend/src/pages/DeviationsPage.tsx`.
- Pins reset on a page reload and are not shared between operators.
- Each pin remembers the row's presence epoch, so a deviation that leaves the deck and
  later returns does not silently jump back to the top.

## Five likely failure modes

| Symptom | Cause | What to do |
|---|---|---|
| A known deviation is not in the dropdown | It is not in the current deck: already decided, absent from Salesforce, purged, or beyond the 500-row deck page | Check **History**, reload the deck, or run a sync. The picker is not a global search. |
| Typing shows no options | The text does not match any current deviation key | Clear the field or try a shorter part of the number. |
| A pinned card disappears | It was accepted/skipped, or it left the Salesforce list | That is intentional; the pin is dropped with the card. |
| All pins vanish after reload | Pins are ephemeral by design | Re-check the deviations you want to review next. |
| The picker is missing or disabled | The deck is empty (complete) or still loading | Wait for the deck, or use **Replay skipped** / **View history** on the completion card. |

## Design references

- Requirements: `docs/FR-deviations.md` FR-10.12.
- Locked decisions: `docs/decisions-deck-picker.md` D-01–D-09.
- Frontend design: `docs/frontend-design-deviations.md` §3.2a.
- Execution order and rollback: `docs/refactor-plan-deck-picker.md`.
- No persistence change: `docs/data-model-deviations.md` §1.2.
- No API change: `docs/api-deviations.md` §5 “Deck picker (client-only)”.
