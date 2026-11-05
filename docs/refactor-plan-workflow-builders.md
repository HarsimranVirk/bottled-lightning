# Refactor Plan — Workflow Builders (multi-workflow wiring)

| | |
|---|---|
| **Status** | **Superseded** — implemented; decisions folded into `docs/class-design-deviations.md` (v4.5) |
| **Version** | v2 |
| **Date** | 2026-11-05 |
| **Depends on** | `docs/class-design-deviations.md` (v3), `docs/refactor-plan-deviations.md` (v3.2) |
| **Touches** | `app/core/workflow.py`, `app/salesforce/urls.py` (new), `app/config.py`, `app/main.py`, `app/workflows/deviations_z02/__init__.py`, tests, `tools/` |
| **Does not touch** | the API surface, the database, the frontend |

> **Why this document exists.** The wiring refactor below was designed and approved,
> then parked behind a separate refactor. It has since been implemented; the decision
> record now lives in `docs/class-design-deviations.md` §3.3, §3.4 and §4. This file is
> kept only as the historical plan.
>
> **Implementation note.** `config.LIST_URL_TEMPLATE` was removed rather than retained:
> the legacy v1 modules it existed for (`app/sync.py`, `routes.py`, `legacy_jobs.py`,
> `store.py`) are no longer in the tree, so keeping it would have left a second,
> unused URL builder next to `app.salesforce.urls.list_view_url`.

## 1. Problem

`build_workflow` is already a factory function — that part is correct and stays. What does
not scale is the **composition root**: `Stack.__init__` (`app/main.py:73-167`) builds
exactly one workflow, shares one `AdapterRegistry` imported from
`app.workflows.deviations_z02.adapters` (`app/main.py:44`), and constructs one
`Reconciler`, one `WorkflowListSource` and one `ListWatcher` for it.

Everything downstream is already generic: `WorkflowRegistry`, per-workflow routers
(`app/api/app.py:48`), `Worker` resolving by `job.workflow`, `Stack.watchers` being a
`dict[str, ListWatcher]`, and every DB row being scoped by workflow name. Only
instantiation is hardcoded.

A second problem rides along: `Settings` carries per-workflow fields
(`deviations_z02_list_url`, `deviations_z02_pattern`, `app/config.py:92-93`), so global
config knows about one workflow's Salesforce internals and every new workflow edits
`app/config.py`.

## 2. Decisions

| ID | Decision |
|---|---|
| **D1** | Introduce `WorkflowBuilder` as a **callable alias**, not a class: `Callable[[Settings, WorkflowDeps], Workflow]`, declared in `app/core/workflow.py`. |
| **D2** | `app/main.py` holds the registration list as a literal: `BUILDERS: tuple[WorkflowBuilder, ...] = (build_workflow,)`. No dynamic discovery, no entry points, no plugin loading — consistent with `class-design-deviations.md:214-217`. |
| **D3** | Each builder constructs **its own** `AdapterRegistry` by calling its package's `build_adapters(...)`. `main.py` stops importing Z02's adapters. `AdapterRegistry` is documented as per-workflow, so sharing one instance across workflows would be wrong. |
| **D4** | `Settings` keeps **global config only** (`org_base`, `data_dir`, `db_path`, `workers`, `refresh_interval_s`, `request_timeout_ms`, `login_wait_s`, `headless`, `update_policy`). The list URL and row pattern move into the Z02 package as module constants. |
| **D5** | The Salesforce list URL shape moves to `app/salesforce/urls.py::list_view_url(org_base, object_api, filter_name)`. The legacy `config.LIST_URL_TEMPLATE` **stays** in `app/config.py` for `app/sync.py`, because `refactor-plan-deviations.md:36-40` forbids further edits to v1 modules; it disappears with them in Phase 9. |
| **D6** | `Stack` becomes a loop: one `Workflow` per builder, registered; one `Reconciler` per workflow; one `WorkflowListSource` + `ListWatcher` per workflow. `ClosureResolver` stays a single shared instance. |

### 2.1 Explicitly rejected

- **Factory classes** (`WorkflowFactory().create(...)`). Same code, one more import, no new
  capability. A module-level function returning a wired object is the idiomatic factory in
  Python.
- **Abstract factory for `Reconciler` / `ListWatcher`.** `Reconciler` varies only on
  `workflow.name` (`app/pipeline/reconciler.py:61-102`) and `workflow.map_row`
  (line 76) — that is parameterisation, not polymorphism. N workflows means N *instances*
  of the same class. An abstract factory exists to choose between *families of related
  products*; there is no second family.
- **Making `Workflow.list_view` optional.** A workflow with no list view (or two) cannot
  be expressed today, because `list_view: ListViewSpec` is mandatory
  (`app/core/workflow.py:104`). That is a real gap, but it belongs to the design of the
  second workflow, not to this wiring refactor. Do not widen scope here.

## 3. Target shape

```python
# app/core/workflow.py  (added; imports Settings from app.config)
WorkflowBuilder = Callable[[Settings, WorkflowDeps], Workflow]
```

```python
# app/main.py
BUILDERS: tuple[WorkflowBuilder, ...] = (build_workflow,)

class Stack:
    def __init__(self, settings: Settings) -> None:
        ...
        deps = WorkflowDeps(items=..., fields=..., attributes=..., refs=..., events=...)
        self.workflows = tuple(build(settings, deps) for build in BUILDERS)
        self.registry = WorkflowRegistry()
        for workflow in self.workflows:
            self.registry.register(workflow)

        self.closure = ClosureResolver(self.items, self.jobs, self.events)
        self.reconcilers = {
            wf.name: Reconciler(wf, self.items, self.jobs, self.attributes,
                                self.sync_runs, self.closure)
            for wf in self.workflows
        }
        self.watchers = {
            wf.name: ListWatcher(
                wf,
                WorkflowListSource(self.runtime, wf, settings, self.provider),
                self.reconcilers[wf.name],
                self.events,
                self.auth,
                settings.refresh_interval_s,
            )
            for wf in self.workflows
        }
```

`self.workflow` (singular) is removed; it has no external readers (`tools/export_openapi.py`
only uses `Stack(settings).app()`).

```python
# app/workflows/deviations_z02/__init__.py
LIST_OBJECT_API = "Consumer_Loan_Deviation__c"
LIST_FILTER = "Z2_Loan_para_pricing1"
LIST_PATTERN = r"Deviation-\d+-\d+"          # see AGENTS.md regex trap: \d+-\d+

def build_workflow(settings, deps, *, force: bool = False) -> Workflow:
    adapters = build_adapters(settings.org_base, settings.request_timeout_ms)
    ...
    list_view=ListViewSpec(
        url=list_view_url(settings.org_base, LIST_OBJECT_API, LIST_FILTER),
        pattern=LIST_PATTERN,
    ),
```

```python
# app/salesforce/urls.py  (new)
def list_view_url(org_base: str, object_api: str, filter_name: str) -> str:
    """Build a Lightning list-view URL: {org}/lightning/o/{object}/{list}?filterName={f}."""
    return f"{org_base}/lightning/o/{object_api}/list?filterName={filter_name}"
```

## 4. Implementation slices

1. **`app/salesforce/urls.py`** — add `list_view_url`. Delete `LIST_HOST_ROOT` from
   `app/config.py` (already dead: zero call sites). Leave `LIST_URL_TEMPLATE` alone (D5).
2. **Z02 package** — add the three constants, call `build_adapters` inside
   `build_workflow`, build the `ListViewSpec` from constants. Delete
   `DEVIATIONS_Z02_OBJECT_API`, `DEVIATIONS_Z02_FILTER`, `DEVIATIONS_Z02_PATTERN` and the
   two `Settings` fields (`app/config.py:74-76, 92-93, 118-123`).
3. **`app/core/workflow.py`** — add the `WorkflowBuilder` alias (and its docstring:
   what a builder owns, that adapters are per-workflow, that it is called once at boot).
4. **`app/main.py`** — `BUILDERS` tuple, the loop above, drop the
   `from .workflows.deviations_z02.adapters import build_adapters` import.
5. **Tests** — remove the two `Settings` kwargs and the explicit `AdapterRegistry`
   argument to `build_workflow`:
   - `tests/test_api.py:49-50, 59-63`
   - `tests/test_registry.py:89-90, 129`
   - `tests/test_jobs.py:144-145`
   - `tests/test_session.py:99-100, 137-138`
   - `tests/test_repositories.py:396-397` — assert against the Z02 package constants
     instead of `settings.deviations_z02_list_url`.
6. **`tools/`** — same substitution in `smoke_list.py:49-50`, `smoke_extract.py:97-98`,
   `smoke_job.py:86, 108-109` (`force=True` stays a keyword on the new signature).
7. **Docs** — fold the decisions into `docs/class-design-deviations.md`:
   - §3.3 registration paragraph: builder tuple, per-workflow adapters.
   - §3.4 checklist step 5: new `build_workflow` signature.
   - §4 `Settings` block: delete `deviations_list: ListViewSpec` (line 252 — the doc
     already drifted from the code; this refactor fixes the drift) and state that
     per-workflow URLs live in the workflow package.
   - A short note that `Stack` loops and that N workflows = N list pages on one serial
     browser runtime.
   Then delete this file (it is a parking note, not a permanent design document) or mark
   it `Superseded`.

## 5. Scope guards

- No behaviour change, no API change, no schema change, no `frontend/src/types.ts` change.
  `docs/FR-deviations.md`, `docs/data-model-deviations.md`, `docs/api-deviations.md` are
  untouched.
- `app/sync.py`, `app/routes.py`, `app/legacy_jobs.py`, `app/store.py` and the rest of the
  v1 surface are **not** edited (D5). `LIST_URL_TEMPLATE` survives in `config.py` purely
  for them.
- `Workflow`, `Reconciler`, `ListWatcher`, `WorkflowListSource`, `ClosureResolver`,
  `AdapterRegistry` keep their current interfaces.
- Still no dynamic discovery: adding a workflow is one import plus one tuple entry.

## 6. Verification

```bash
python -m unittest discover -s tests
mypy --strict app tests
ruff check app/ tools/ tests/
npm --prefix frontend run typecheck      # expected no-op
python -m app.main --no-update           # boot: 1 workflow registered, 1 watcher started
```

Extraction code is not touched, so the header-total cross-check does not need re-running;
confirm the boot log still reports `sync deviations_z02: ... valid=True` once against a
live session before calling the slice done.

## 7. Risks

- **`Callable` alias vs. `Protocol`.** `build_workflow` carries an extra keyword-only
  `force: bool = False`; extra defaulted parameters are compatible with a `Callable`
  target, so the alias should typecheck. If `mypy --strict` disagrees, replace the alias
  with a `Protocol` whose `__call__(self, settings, deps) -> Workflow` — a mechanical
  change, not a redesign. No `cast`, no `type: ignore` (AGENTS.md forbids both).
- **One page per workflow.** N workflows means N always-open list pages on the single
  serial browser runtime, plus N resync loops. Harmless at N=1; the first thing to watch
  when a second workflow lands.
- **Shared `ClosureResolver`.** Safe today: `close_if_absent(item)` reads
  `item.workflow` (`app/pipeline/closure.py:50`). Re-verify if it ever gains
  workflow-independent state.
- **Doc drift.** `class-design-deviations.md:252` already disagrees with the code
  (`deviations_list: ListViewSpec` vs. two flat strings). Slice 7 must fix the doc rather
  than preserve either version.
