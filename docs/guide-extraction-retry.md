# Guide — Extraction Retry

What to do when a deviation card says a page could not be read. Companion to
`docs/FR-deviations.md` FR-3.5–FR-3.10 and FR-9.26.

## What the card is telling you

Extraction reads five Salesforce objects for every deviation: the Opportunity, the CL
contract for the product, the collateral, and the two LMS 2.0 records. Each one is stored
as a **link** with one of three states:

| State | Meaning | What you see |
|---|---|---|
| `found` | The page opened and the record exists. | The linked name. |
| `absent` | The list rendered and Salesforce says the record does not exist. | "No collateral attached to this opportunity". |
| `unresolved` | The lookup did not finish: the page did not open, the list never rendered, or the match was ambiguous. | "Couldn't open the collateral list", "There are 2 CL contracts for this product — can't tell which one". |

A deviation is only ready when **all five** links are `found`. If any is missing, the
deviation lands in **Needs Review** with the first missing link's sentence at the top of
the card, and the job shows as failed in the Jobs table. Nothing retries on its own.

## Retrying

Press **Retry extraction** on the card. While the job runs the button is disabled and the
card says *"Retrying extraction — this can take a minute."*

The retry re-reads Salesforce from scratch (values, attributes and every link) and clears
the previous reason if it succeeds, so the card either leaves the deck as Ready or comes
back with a new, more specific reason.

What a retry cannot do:

- It cannot resolve a genuine `absent`. If Salesforce really has no collateral attached,
  retrying returns the same sentence. That deviation is missing data: reject it and fix
  the record in Salesforce, or leave it for whoever owns the data.
- It cannot resolve an ambiguous match. Two CL contracts for the same product need a
  human decision in Salesforce (remove the wrong one) before extraction can choose.
- It is not available for a deviation whose extraction is already complete. If a card is
  in Needs Review for a *submission* failure, the retry button is not shown — correct the
  field values and submit again instead.

## When it keeps failing

1. **Session expired.** Check the session banner first; a dead session makes every page
   look unreadable. Log in, then retry.
2. **The card names a page that does exist.** That is an `unresolved` link: the page
   loaded too slowly or the list never rendered. One more retry is reasonable; a third
   identical failure is worth reporting with the job's log lines (Jobs table → the
   failed `extract` job), because the log keeps the exception and the timing that the
   card deliberately hides.
3. **The card says "There are N … records — can't tell which one."** Clean up the
   duplicate in Salesforce, then retry.
4. **The card says "No … for this product".** Extraction is working; the product mapping
   has no matching record. Check the Opportunity's Product Type against the contract's
   Product column, then retry.

## What the operator never sees

Exception names, Playwright timeouts and stack traces stay in the job log and the server
log. The card and the job's `error` column carry only the plain sentence, so a screenshot
of the deck is safe to share.

## Limits worth knowing

- A first-seen list row with no record link produces **no card and no job**. It appears
  once the live list renders the link, and extraction runs then.
- Legacy deviations extracted before link states existed may show a card after an upgrade;
  that is the startup audit repairing them, not a new failure. One retry clears it.
