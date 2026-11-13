# Guide — network profile (bounded submissions and extractions)

A per-machine setting for how patient the browser is. It exists because the app had no
job-level timeout: each wait was capped at 60 s, but a submission could stack five
objects × several waits and run for many minutes, and a page that never answered looked
exactly like a flag to click.

## The three presets

| Preset | One action | Object read | Object write | Whole run |
|---|---|---|---|---|
| **Fast** | 60 s | 45 s | 90 s | 180 s |
| **Default** | 60 s | 75 s | 150 s | 300 s |
| **Slow** | 120 s | 150 s | 300 s | 600 s |

Derivation, all from one whole-run budget: `action = max(60 s, budget/5)`,
`read = budget/4`, `write = budget/2`. The floor on `action` matters: **Fast must never
make extraction, discovery, login or the list refresh less patient than the shipped
60 s**, so a profile change can only relax the per-action wait.

`Default` is the shipped value and reproduces the old `REQUEST_TIMEOUT_MS = 60_000`
exactly, so nothing changes until someone chooses otherwise.

## Changing it

The gear icon in the header (left of the theme toggle) opens the dialog. Each radio
button names its consequence, and the numbers under the group come from the server.

- The value is saved to `data/settings.json` (`{"network_profile": "slow"}`), written
  atomically, and is **live**: the next job uses it, no restart.
- A running job snapshots the budget once at `run()` start, so one job runs under one
  profile. Its per-action waits do read the live value (adapters share one policy).
- With no file, `SF_NETWORK_PROFILE` (`fast|default|slow`) is the boot default; an
  unknown value logs and falls back to `default`. A malformed file is logged and
  ignored, never fatal at boot.

API: `GET /api/settings`, `PATCH /api/settings` — see `api-deviations.md` §7b.

## What a timeout means

The fault matters, because the outcomes differ:

| Fault | Detection | Result |
|---|---|---|
| Tab died (crash/external close) | `page.is_closed()` at group boundaries and between targets | `TransientBrowserError` → job retried once; item stays in its working status until the retry fails |
| One object's write overran | `asyncio.timeout` around that group | That group's targets `UNKNOWN`; **the remaining objects are still written**, then the submission fails `writes not accepted: …=unknown` |
| One object's read overran | same, around the read | `None` for that object: audit-only during precheck, a read-back mismatch during validation |
| Whole run overran | `asyncio.timeout` around the run | Submission: `submission did not finish within 300s`. Extraction: `ExtractOutcome.INCOMPLETE` |

Two deliberate choices:

- **A timed-out write does not stop the other objects.** Submissions never retry
  themselves, so every field that lands is manual work saved, and the per-field truth
  records exactly what was written. This is only safe because the whole-run budget caps
  the cost.
- **Extraction overruns park the item** (`INCOMPLETE`) rather than retrying. `FAILED`
  would requeue once and cost 2 × budget; `INCOMPLETE` asks the operator, who can see
  why.

## Tuning it

Pick `Slow` when a healthy submit on that machine takes minutes (VPN, tethering,
congested wifi). A false timeout is expensive — the submission is abandoned half-written
and never retried — so prefer the slower preset over the faster one. `Fast` exists for a
machine where the *net* budget is the problem, not the per-object ones.

The job log names the profile at the start of every run:

```
budget: profile=default action=60s read=75s write=150s total=300s
```

## Tests

- `tests/test_config.py` — derivation, the action floor, live application, file
  round-trip and malformed files.
- `tests/test_submission.py` — group write timeout records `UNKNOWN` and keeps writing;
  whole-run timeout fails with the budget.
- `tests/test_extraction.py` — overrun is `INCOMPLETE` and parks the item.
- `frontend/src/components/SettingsMenu.test.tsx` — the dialog renders and saves.
