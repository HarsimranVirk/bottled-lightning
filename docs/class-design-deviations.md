# Class Design — Workflows (Deviations first)

| | |
|---|---|
| **Status** | Draft for review |
| **Version** | v2 |
| **Date** | 2026-11-04 |
| **Companion** | `docs/FR-deviations-v2.md` (v2.1), `docs/refactor-plan-deviations.md` |
| **Change** | v2 introduces the workflow abstraction; v1 was deviations-only |
| **Implemented so far** | Phases 1–3 on `refactor/deviations-v2`: `app/db`, `app/core` (models, status, field, list view, workflow, registry, repos), `app/salesforce/{runtime,session,login,tabs,list_page,adapters}`, `app/workflows/deviations_z02/{catalog,description,product_map,adapters,extraction}` |

This document describes the target class design. It separates the parts that are the
same for every Salesforce workflow (browser, tabs, queue, leases, refresh, closure) from
the parts that are specific to one workflow (what to extract, where values are written,
how the final action works). Deviations is the only workflow implemented now;
cancellations and future workflows plug into the same interfaces.

Requirement IDs (`FR-x.y`) refer to the deviations FR doc.

---

## 1. Shape

One process, one browser, one event loop, one queue. Workflows are registered objects,
not parallel stacks.

```
                    ┌────────────────────────────────────────────────────┐
  HTTP (threadpool) │  api/routes/*                                      │
                    │    └── services (sync; enqueue or query only)       │
                    └───────────────────────┬────────────────────────────┘
                                            │ runtime.run(coro)
                    ┌───────────────────────▼────────────────────────────┐
                    │  BrowserRuntime (dedicated thread + asyncio loop)   │
                    │                                                    │
                    │  SessionProvider ── snapshot inject / expiry       │
                    │  BrowserContext (warm, one per process)            │
                    │                                                    │
                    │  WorkflowRegistry                                  │
                    │    ├── deviations   → ListWatcher, Extraction,     │
                    │    │                   Submission, catalog         │
                    │    └── (cancellations, …) same shape               │
                    │                                                    │
                    │  Dispatcher ── claim jobs, N in flight             │
                    │    └── Worker ── routing by (workflow, kind)       │
                    │          ├── workflow.extraction.run(...)          │
                    │          └── workflow.submission.run(...)          │
                    │  TabGroup ── per-job tabs, closed on exit          │
                    └───────────────────────┬────────────────────────────┘
                                            │
                              SQLite (WAL) + repositories (workflow-scoped)
```

Everything that touches Playwright lives on that one loop. HTTP handlers never touch a
`Page`; they submit a coroutine and wait. SQLite calls are synchronous but sub-millisecond
and run inline (documented exception; `asyncio.to_thread` is the escape hatch).

---

## 2. Module layout

```
app/
  config.py                       Settings (frozen dataclass + env loader)
  db/
    connection.py                 Database: engine, thread-local conns, transaction()
    schema.py                     DDL v2 + PRAGMA user_version migrations
  core/                           shared mechanism — knows no workflow
    models.py                     WorkItem, FieldValue, Attribute, PageRef, Job, SyncRun
    status.py                     WorkItemStatus, JobKind, JobStatus, Phase, ClosureSource
    logging.py                    SF_LOG_LEVEL (default INFO; DEBUG for per-row noise)
  utils/
    dom.py                        async Playwright helpers (safe text, waits, URL joins)
    field.py                      EditableField, FieldTarget, ValueType, normalise()
    errors.py                     Error taxonomy
    registry.py                   WorkflowRegistry
    workflow.py                   Workflow spec + ExtractionPipeline / SubmissionPipeline
    list_view.py                  ListViewSpec, ListRow, ListSample, is_valid_sample()
    repo/
      work_items.py               WorkItemRepository
      fields.py                   FieldValueRepository
      attributes.py               AttributeRepository
      refs.py                     PageRefRepository
      jobs.py                     JobRepository (claim / lease / complete)
      sessions.py                 SessionRepository
      sync_runs.py                SyncRunRepository
      events.py                   EventRepository
  salesforce/
    runtime.py                    BrowserRuntime
    session.py                    SessionProvider (+ is_login_page, cookie decoding)
    login.py                      `python -m app.salesforce.login` (headed, --reset)
    tabs.py                       TabGroup
    list_page.py                  ListPage (refresh/read for one ListViewSpec)
    adapters.py                   ObjectAdapter protocol, AdapterRegistry
  pipeline/
    watcher.py                    ListWatcher (one per registered workflow)
    reconciler.py                 Reconciler (generic)
    closure.py                    ClosureResolver (generic)
  jobs/
    dispatcher.py                 Dispatcher
    worker.py                     Worker
    lease.py                      Lease
    outcomes.py                   ExtractOutcome, SubmitOutcome
  api/
    schemas.py                    Pydantic DTOs
    services.py                   WorkItemService, AdminService
    routes/
      workflows.py                make_router(workflow) — one mount per workflow
      jobs.py  sessions.py  syncs.py  workers.py  updates.py
  workflows/
    deviations_z02/
      __init__.py                 build_workflow(settings, deps, adapters)
      catalog.py                  DeviationObject, FIELD_CATALOG
      description.py              parse_description_fields() (pure)
      product_map.py              CL_CONTRACT_PRODUCT_MAP (reference data)
      adapters/
        __init__.py               build_adapters(org_base, timeout_ms)
        deviation_record.py  opportunity.py  cl_contract.py
        collateral.py  lms2.py    (LMS2 CL contract + collateral)
      extraction.py               DeviationsZ02Extraction
      submission.py               DeviationsZ02Submission
    cancellations/                same shape, later
  main.py
  updater.py                      unchanged
```

Deleted: `store.py`, `browser.py`, `jobs.py`, `sync.py`, `routes.py`, `types.py`,
`deviations/`, `deviations_z01..z04/`, `cancellations/`.

---

## 3. Extensibility model

### 3.1 What is shared, what is per-workflow

| Shared (core) | Per workflow |
|---|---|
| Browser, context, tabs, timeouts | List view URL, filter, key pattern |
| Session snapshot, expiry, auth gate | Row → attribute mapping |
| Job queue, lease, retry, dispatcher | Extraction order and object set |
| Refresh loop, valid-sample rule | Adapters (SF objects, selectors, fields) |
| Presence/absence reconciliation | Field catalogue and write targets |
| Closure resolution and attribution | Submission phases and final action |
| Audit trail, events, job logs | Status labels rendered in UI |
| REST scaffolding (`make_router`) | Any workflow-specific endpoint |
| Repositories (workflow-scoped) | — |

The split is deliberate: core owns *when* and *how safely*, workflows own *what*.

### 3.2 The two interfaces

```python
class ExtractionPipeline(Protocol):
    async def run(self, item: WorkItem, tabs: TabGroup, log: JobLogger) -> ExtractOutcome: ...

class SubmissionPipeline(Protocol):
    async def run(self, item: WorkItem, tabs: TabGroup, log: JobLogger) -> SubmitOutcome: ...
```

Both are `Protocol`s, not base classes: implementations do not inherit behaviour, they
satisfy the shape. That keeps a future workflow from being forced into the deviations
phase machine.

Outcomes are shared vocabulary, because the worker (not the pipeline) owns the effect:

```python
class ExtractOutcome(StrEnum):
    EXTRACTED = "extracted"     # ready for the operator
    SKIPPED = "skipped"         # ambiguity / missing data, terminal, with reason
    FAILED = "failed"           # retryable

class SubmitOutcome(StrEnum):
    COMPLETED = "completed"     # final action performed by us
    ALREADY_CLOSED = "already_closed"   # gone in SF; clean terminal, not an error
    FAILED = "failed"           # retryable or needs review, decided by the pipeline
```

`COMPLETED` is rendered as **Implemented** by the deviations workflow (FR wording). The
core does not know the word "implement".

### 3.3 The workflow object

```python
@dataclass(frozen=True, slots=True)
class Workflow:
    name: str                                   # "deviations_z02"
    route: str                                  # "deviations" → /api/deviations
    list_view: ListViewSpec
    catalog: tuple[EditableField, ...]
    adapters: AdapterRegistry
    extraction: ExtractionPipeline
    submission: SubmissionPipeline
    map_row: Callable[[ListRow], Mapping[str, str]]   # list-visible attrs → store
    terminal_labels: Mapping[WorkItemStatus, str]     # UI wording, e.g. COMPLETED→Implemented
```

`name` identifies the workflow internally (and scopes every DB row); `route` is the REST
noun. The Z02 deviations workflow registers as `deviations_z02` with `route="deviations"`,
so the API stays `/api/deviations` while a future `deviations_z01` can take its own route.

`WorkflowRegistry`:

```python
class WorkflowRegistry:
    def register(self, workflow: Workflow) -> None: ...
    def get(self, name: str) -> Workflow: ...            # raises UnknownWorkflow
    def all(self) -> tuple[Workflow, ...]: ...
```

Registration happens by importing the package (`main.py` imports
`app.workflows.deviations_z02`), whose `build_workflow(...)` returns the `Workflow` the
registry is given. No dynamic discovery, no entry points, no plugin loading — the list of
workflows is a literal in `main.py`.

### 3.4 Adding a workflow

A checklist, so this stays a 5-file job and not a framework:

1. `app/workflows/<name>/catalog.py` — object kinds + `FIELD_CATALOG`.
2. `app/workflows/<name>/adapters/` — one `ObjectAdapter` per SF object.
3. `app/workflows/<name>/extraction.py` — implements `ExtractionPipeline`.
4. `app/workflows/<name>/submission.py` — implements `SubmissionPipeline`.
5. `__init__.py` — build the `Workflow` and register it; add it to `main.py`.
6. Mount `make_router(workflow)`; the frontend picks up the workflow from
   `GET /api/workflows`.

Nothing in `core/`, `salesforce/`, `pipeline/` or `jobs/` changes. If a new workflow
needs a new status or a new outcome, that is an enum member plus a `terminal_labels`
entry, not a code path.

### 3.5 The cost, stated plainly

Workflow-agnostic storage (one `work_items` table with a `workflow` column) is less
obvious than `deviations(...)`. Mitigation: `WorkItemRepository` is the only thing that
sees the table, and it always takes an explicit `workflow` argument, so call sites read
`items.list(workflow=deviations, status=READY)`. If a third workflow ever needs
materially different persistence, it gets its own table and its own repository — the
interface does not force shared storage.

---

## 4. Configuration

```python
@dataclass(frozen=True, slots=True)
class Settings:
    org_base: str
    deviations_list: ListViewSpec        # filter name + object path + pattern
    data_dir: Path
    db_path: Path
    workers: int                         # 1..5, default 3      (FR-7.4)
    refresh_interval_s: float            # 30                    (FR-2.2)
    request_timeout_ms: int
    login_wait_s: int
    headless: bool
    update_policy: str
```

Constructed once in `main()` and injected. The worker count persists in `settings.json`;
changing it at runtime restarts the dispatcher only.

---

## 5. Domain (core)

### 5.1 Enums (`core/status.py`)

```python
class WorkItemStatus(StrEnum):
    PRESENT = "present"
    EXTRACTING = "extracting"
    READY = "ready"
    EDITING = "editing"
    SUBMITTING = "submitting"
    APPLYING = "applying"
    VALIDATING = "validating"
    EXECUTING = "executing"          # the workflow's final action is running
    ABSENT_PENDING = "absent_pending"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"          # terminal, source=system
    CLOSED = "closed"                # terminal, source=external
    SKIPPED = "skipped"              # terminal, with reason

TERMINAL_STATUSES: frozenset[WorkItemStatus] = frozenset(
    {WorkItemStatus.COMPLETED, WorkItemStatus.CLOSED, WorkItemStatus.SKIPPED}
)

class JobKind(StrEnum):
    EXTRACT = "extract"
    SUBMIT = "submit"

class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED_AUTH = "blocked_auth"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

class Phase(StrEnum):
    EXTRACT = "extract"
    APPLY = "apply"
    VALIDATE = "validate"
    EXECUTE = "execute"

class ClosureSource(StrEnum):
    SYSTEM = "system"
    EXTERNAL = "external"

class WriteOutcome(StrEnum):
    SAVED = "saved"
    REJECTED = "rejected"
    UNKNOWN = "unknown"
```

`WorkItemStatus` is the shared lifecycle. A workflow may add members (and register them as
terminal) but may not redefine the meaning of the existing ones.

### 5.2 Entities (`core/models.py`)

Frozen dataclasses; no behaviour beyond small predicates.

```python
@dataclass(frozen=True, slots=True)
class WorkItem:
    workflow: str
    key: str                      # Deviation-28102026-484106
    record_url: str | None        # from the list row; extraction needs it
    status: WorkItemStatus
    source: ClosureSource | None
    reason: str | None
    present: bool
    epoch: int
    first_seen: datetime
    last_seen: datetime
    absent_since: datetime | None
    approved_at: str | None
    extracted_at: datetime | None
    execute_attempted_at: datetime | None    # implement clicked
    execute_confirmed_at: datetime | None    # implement observed
    closed_at: datetime | None

@dataclass(frozen=True, slots=True)
class FieldValue:
    workflow: str
    item: str
    key: str
    extracted: str | None
    last_synced: str | None
    proposed: str | None          # operator edit, wins over sync  (FR-2.5)
    applied: str | None
    status: str
    updated_at: datetime

@dataclass(frozen=True, slots=True)
class Attribute:
    workflow: str
    item: str
    name: str                     # description, requested_roi, product_type, …
    value: str | None

@dataclass(frozen=True, slots=True)
class PageRef:
    workflow: str
    item: str
    kind: str                     # workflow-defined: "cl_contract", "lms2_collateral", …
    name: str
    url: str

@dataclass(frozen=True, slots=True)
class Job:
    id: int
    workflow: str
    kind: JobKind
    item: str
    status: JobStatus
    phase: Phase | None
    attempts: int
    lease_owner: str | None
    lease_expires_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None

@dataclass(frozen=True, slots=True)
class SyncRun:
    id: int
    workflow: str
    captured_at: datetime
    header_total: int | None
    rows_read: int
    valid: bool
    warning: str | None
    added: int
    updated: int
    closed: int
```

`Attribute` is the generic home for read-only extracted values (FR-4.4), so the core never
needs a deviation-shaped column.

### 5.3 Field model (`core/field.py`)

```python
class ValueType(StrEnum):
    AMOUNT = "amount"        # Indian grouping, 25,50,000
    TENURE_MONTHS = "months"
    TEXT = "text"

@dataclass(frozen=True, slots=True)
class FieldTarget:
    object_kind: str         # a key in the workflow's AdapterRegistry
    label: str               # SF field label

@dataclass(frozen=True, slots=True)
class EditableField:
    key: str
    label: str
    value_type: ValueType
    targets: tuple[FieldTarget, ...]   # one or many  (FR-6.3)
    required: bool = True
    source: str | None = None          # where extraction reads it from, if parsed

def normalise(value: str, value_type: ValueType) -> str: ...
def fields_for(catalog: Sequence[EditableField], kind: str) -> tuple[EditableField, ...]: ...
```

`normalise` and `fields_for` are pure and unit-tested; they are the only places that know
about amount formatting or per-object field slicing.

---

## 6. Persistence

### 6.1 `Database`

```python
class Database:
    def __init__(self, path: Path) -> None: ...
    def connect(self) -> sqlite3.Connection: ...
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]: ...
    def migrate(self) -> None: ...     # PRAGMA user_version
```

WAL, `foreign_keys=ON`, `busy_timeout=5000`, one connection per thread.

### 6.2 Schema v2

All item tables are workflow-scoped; `workflow` is part of every primary key.

```sql
CREATE TABLE work_items (
    workflow TEXT NOT NULL,
    item_key TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT, reason TEXT,
    present INTEGER NOT NULL DEFAULT 1,
    epoch INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
    absent_since TEXT,
    approved_at TEXT,
    extracted_at TEXT,
    execute_attempted_at TEXT, execute_confirmed_at TEXT,
    closed_at TEXT,
    PRIMARY KEY (workflow, item_key)
);
CREATE INDEX work_items_status ON work_items(workflow, status);

CREATE TABLE work_item_fields (
    workflow TEXT NOT NULL, item_key TEXT NOT NULL, field_key TEXT NOT NULL,
    extracted TEXT, last_synced TEXT, proposed TEXT, applied TEXT,
    status TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (workflow, item_key, field_key)
);

CREATE TABLE work_item_attributes (
    workflow TEXT NOT NULL, item_key TEXT NOT NULL, name TEXT NOT NULL,
    value TEXT,
    PRIMARY KEY (workflow, item_key, name)
);

CREATE TABLE work_item_refs (
    workflow TEXT NOT NULL, item_key TEXT NOT NULL, kind TEXT NOT NULL,
    name TEXT NOT NULL, url TEXT NOT NULL,
    PRIMARY KEY (workflow, item_key, kind)
);

CREATE TABLE work_item_edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow TEXT NOT NULL, item_key TEXT NOT NULL, field_key TEXT NOT NULL,
    old_value TEXT, new_value TEXT,
    job_id INTEGER, created_at TEXT NOT NULL
);

CREATE TABLE work_item_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow TEXT, item_key TEXT, job_id INTEGER,
    kind TEXT NOT NULL, detail TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow TEXT NOT NULL, item_key TEXT NOT NULL,
    kind TEXT NOT NULL, status TEXT NOT NULL,
    phase TEXT, attempts INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT, lease_expires_at TEXT,
    created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
    error TEXT
);
CREATE INDEX jobs_claim ON jobs(status, kind, created_at);
CREATE UNIQUE INDEX jobs_active ON jobs(workflow, item_key)
    WHERE status IN ('queued', 'running', 'blocked_auth');

CREATE TABLE job_logs (
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL, line TEXT NOT NULL, at TEXT NOT NULL,
    PRIMARY KEY (job_id, seq)
);

CREATE TABLE sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow TEXT NOT NULL, captured_at TEXT NOT NULL,
    header_total INTEGER, rows_read INTEGER NOT NULL,
    valid INTEGER NOT NULL, warning TEXT,
    added INTEGER NOT NULL DEFAULT 0, updated INTEGER NOT NULL DEFAULT 0,
    closed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org TEXT, storage_state TEXT NOT NULL,
    cookie_count INTEGER NOT NULL, created_at TEXT NOT NULL
);

CREATE TABLE session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL
);
```

The `jobs_active` partial unique index is invariant I2 enforced by the database rather than
by application logic.

### 6.3 Repositories

```python
class WorkItemRepository:
    def get(self, workflow: str, key: str) -> WorkItem | None: ...
    def list(self, workflow: str, status: WorkItemStatus | None,
             query: str | None, limit: int, offset: int) -> tuple[list[WorkItem], int]: ...
    def create_present(self, workflow: str, row: ListRow, at: datetime) -> WorkItem: ...
    def touch(self, workflow: str, key: str, at: datetime) -> None: ...
    def transition(self, workflow: str, key: str,
                   to: WorkItemStatus, **fields: object) -> WorkItem: ...
    def set_absent(self, workflow: str, key: str, at: datetime) -> None: ...
    def begin_epoch(self, workflow: str, key: str) -> WorkItem: ...
    def mark_execute_attempted(self, workflow: str, key: str, at: datetime) -> None: ...
    def mark_execute_confirmed(self, workflow: str, key: str, at: datetime) -> None: ...

class FieldValueRepository:
    def for_item(self, workflow: str, key: str) -> dict[str, FieldValue]: ...
    def set_extracted(self, workflow: str, key: str,
                      values: Mapping[str, str | None]) -> None: ...
    def set_last_synced(self, workflow: str, key: str,
                        values: Mapping[str, str | None]) -> None: ...
    def propose(self, workflow: str, key: str,
                changes: Mapping[str, str | None]) -> None: ...
    def discard_proposed(self, workflow: str, key: str) -> None: ...
    def mark_applied(self, workflow: str, key: str, field_key: str, value: str) -> None: ...

class AttributeRepository:
    def for_item(self, workflow: str, key: str) -> dict[str, str | None]: ...
    def upsert(self, workflow: str, key: str,
               values: Mapping[str, str | None]) -> None: ...

class PageRefRepository:
    def for_item(self, workflow: str, key: str) -> dict[str, PageRef]: ...
    def replace(self, workflow: str, key: str, refs: Sequence[PageRef]) -> None: ...

class JobRepository:
    def enqueue(self, workflow: str, kind: JobKind, key: str) -> Job: ...
    def claim(self, owner: str, ttl_s: float) -> Job | None: ...
    def heartbeat(self, job_id: int, ttl_s: float) -> None: ...
    def set_phase(self, job_id: int, phase: Phase) -> None: ...
    def complete(self, job_id: int) -> None: ...
    def fail(self, job_id: int, error: str, retryable: bool) -> None: ...
    def release_blocked(self, job_id: int) -> None: ...
    def cancel_active_for(self, workflow: str, key: str) -> int: ...
    def requeue_stale(self) -> int: ...
    def recent(self, workflow: str | None, kind: JobKind | None,
             status: JobStatus | None, limit: int) -> list[Job]: ...
    def log(self, job_id: int, line: str) -> None: ...

class SessionRepository:
    def snapshot(self) -> SessionSnapshot | None: ...
    def save(self, storage_state: str, cookie_count: int, org: str | None) -> None: ...
    def clear(self) -> None: ...
    def event(self, kind: str, detail: str) -> None: ...

class SyncRunRepository:
    def record(self, run: SyncRun) -> int: ...
    def latest(self, workflow: str) -> SyncRun | None: ...

class EventRepository:
    def emit(self, kind: str, workflow: str | None, item: str | None,
             job_id: int | None, detail: str | None) -> None: ...
```

Repositories never touch Playwright and never contain workflow-specific logic.

---

## 7. Salesforce layer (shared)

### 7.1 `BrowserRuntime`

```python
class BrowserRuntime:
    def __init__(self, settings: Settings, session: SessionProvider) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def run[T](self, factory: Callable[[], Coroutine[None, None, T]]) -> T: ...
    def spawn(self, factory: Callable[[], Coroutine[None, None, object]]) -> None: ...
```

One dedicated thread, one `asyncio` loop, one persistent Chromium context for the process
lifetime (FR-7.3). `run` is the thread-safe bridge used by HTTP handlers; `spawn` starts
long-lived tasks (watchers, dispatcher).

### 7.2 `SessionProvider`

```python
class SessionProvider:
    async def ensure(self, page: Page) -> None: ...     # raises SessionExpired
    async def reload(self, ctx: BrowserContext) -> None: ...
    async def save_from(self, ctx: BrowserContext) -> None: ...
    def is_expired(self) -> bool: ...
    def mark_expired(self) -> None: ...
```

Adapters may raise `SessionExpired` at any SF call; the worker translates it (8.4).

### 7.3 `TabGroup`

Per-job tab ownership — the parallel-tabs primitive (FR-3.6).

```python
class TabGroup:
    def __init__(self, ctx: BrowserContext, timeout_ms: int) -> None: ...
    @asynccontextmanager
    async def open(self, url: str) -> AsyncIterator[Page]: ...
    async def close_all(self) -> None: ...
    @property
    def open_count(self) -> int: ...
```

### 7.4 `ListViewSpec` / `ListSample` / `ListPage`

```python
@dataclass(frozen=True, slots=True)
class ListViewSpec:
    url: str
    pattern: str          # Deviation-\d+-\d+

@dataclass(frozen=True, slots=True)
class ListRow:
    key: str
    href: str
    columns: Mapping[str, str]
    approved_at: str | None

@dataclass(frozen=True, slots=True)
class ListSample:
    captured_at: datetime
    header_total: int | None
    rows: tuple[ListRow, ...]
    @property
    def valid(self) -> bool: ...

def is_valid_sample(header_total: int | None, rows: Sequence[ListRow]) -> bool:
    return header_total is not None and header_total == len(rows)
```

`ListPage` wraps one page and one spec: `async def refresh()`, `async def read() -> ListSample`.

### 7.5 `ObjectAdapter`

```python
@dataclass(frozen=True, slots=True)
class DiscoveryContext:
    item_key: str
    record_url: str
    opportunity_url: str | None = None
    product_type: str | None = None

@dataclass(frozen=True, slots=True)
class DiscoveredRef:
    kind: str
    name: str
    url: str

@dataclass(frozen=True, slots=True)
class Discovery:
    refs: tuple[DiscoveredRef, ...] = ()
    attributes: Mapping[str, str | None] = field(default_factory=dict)
    fields: Mapping[str, str | None] = field(default_factory=dict)
    skip_reason: str | None = None

class ObjectAdapter(Protocol):
    kind: str
    async def discover(self, tabs: TabProvider, context: DiscoveryContext) -> Discovery: ...
    async def open(self, tabs: TabProvider, ref: PageRef) -> Page: ...
    async def read(self, page: Page, fields: Sequence[EditableField]) -> dict[str, str | None]: ...
    async def write(self, page: Page, values: Mapping[str, str]) -> dict[str, WriteOutcome]: ...

class AdapterRegistry:
    def __init__(self, adapters: Iterable[ObjectAdapter]) -> None: ...
    def get(self, kind: str) -> ObjectAdapter: ...
```

`discover()` runs during extraction and returns only what that object contributes: its
link, its read-only attributes, any catalogue values it is the source of, or a skip
reason (FR-3.7). It never persists and never decides item status.

`write()` = open the record → click Edit → fill the catalogue fields → Save → return
per-field outcomes; `read()` is used for post-save verification (FR-6.4). Both land in
Phase 6. Adapters depend on `TabProvider` (two async methods), not on the concrete
`TabGroup`, so pipelines can be tested without a browser.

---

## 8. Pipelines (shared)

### 8.1 `ListWatcher` — one per workflow

```python
class ListWatcher:
    def __init__(self, workflow: Workflow, browser: BrowserRuntime,
                 reconciler: Reconciler, settings: Settings) -> None: ...
    async def run_forever(self) -> None: ...
    async def refresh_once(self) -> SyncRun: ...
```

Each workflow gets one dedicated, always-open page on its own list view (FR-2.1, FR-7.5).
It never runs jobs. It never writes terminal status — it hands the sample to the
`Reconciler`.

### 8.2 `Reconciler` — generic

```python
class Reconciler:
    def __init__(self, workflow: Workflow, items: WorkItemRepository,
                 fields: FieldValueRepository, attrs: AttributeRepository,
                 jobs: JobRepository, runs: SyncRunRepository,
                 closure: ClosureResolver) -> None: ...
    def apply(self, sample: ListSample) -> SyncRun: ...
```

This is the only reader of `ListSample`, and it implements FR-2.3–2.9 and FR-6.13 without
knowing what a deviation is:

```
if not sample.valid:            record warning, mutate nothing        (FR-2.9)
for row in sample.rows:
    unknown      → create_present + enqueue EXTRACT                   (FR-2.3)
    known        → touch(last_seen), update last_synced via workflow.map_row
                   (never proposed, FR-2.5); if absent before → begin_epoch (FR-6.13)
for known item not in rows:     closure.close_if_absent(...)           (FR-2.6)
```

`workflow.map_row(row)` is the only workflow-specific part: a pure function mapping list
columns to stored attributes. For deviations today it is nearly empty (the list view gives
the number, the href and the approval date; the four editable values come from the detail
page).

### 8.3 `ClosureResolver` — generic

```python
class ClosureResolver:
    def close_if_absent(self, item: WorkItem, observed_at: datetime) -> None: ...
    def release_lease(self, workflow: str, item: str) -> None: ...
```

Decision table (FR-2.8, FR-6.11):

```
if an active job lease exists          → ABSENT_PENDING, stop (resolved on release)
elif execute_confirmed_at is set       → COMPLETED, source=system
elif execute_attempted_at is set       → COMPLETED, source=system, flag implement_unconfirmed
else                                   → CLOSED, source=external, reason=already_implemented
then: cancel active jobs, emit event
```

### 8.4 `AuthGate`

```python
class AuthGate:
    def pause(self, reason: str) -> None: ...
    def resume(self) -> None: ...
    @property
    def paused(self) -> bool: ...
    def on_session_expired(self, jobs: JobRepository) -> None: ...
```

One object, injected everywhere, so FR-1.4 is a single policy: pause dispatch, mark active
jobs `BLOCKED_AUTH`, resume after a fresh snapshot.

---

## 9. Deviations workflow (concrete)

### 9.1 Crate

```python
class DeviationObject(StrEnum):
    DEVIATION = "deviation"
    OPPORTUNITY = "opportunity"
    CL_CONTRACT = "cl_contract"
    COLLATERAL = "collateral"
    LMS2_CL_CONTRACT = "lms2_cl_contract"
    LMS2_COLLATERAL = "lms2_collateral"

FIELD_CATALOG: tuple[EditableField, ...] = (
    EditableField("loan_amount", "Loan Amount", ValueType.AMOUNT,
                  (FieldTarget(DeviationObject.CL_CONTRACT, "Loan Amount"),),
                  source="loan_amount"),
    EditableField("property_value", "Property Value", ValueType.AMOUNT,
                  (FieldTarget(DeviationObject.COLLATERAL, "Property Value"),),
                  source="property_value"),
    EditableField("tenure", "Tenure", ValueType.TENURE_MONTHS,
                  (FieldTarget(DeviationObject.CL_CONTRACT, "Tenure"),),
                  source="tenure"),
    EditableField("emi_incl_hffc", "EMI & other fixed payments incl. HFFC Loan",
                  ValueType.AMOUNT,
                  (FieldTarget(DeviationObject.CL_CONTRACT, "EMI"),),
                  source="emi_incl_hffc"),
)
```

**Targets are placeholders pending O-1** and are the only lines that change when the
mapping is confirmed.

### 9.2 `DeviationsZ02Extraction`

```python
class DeviationsZ02Extraction:
    def __init__(self, workflow: str, items: WorkItemRepository,
                 fields: FieldValueRepository, attrs: AttributeRepository,
                 refs: PageRefRepository, events: EventRepository,
                 adapters: AdapterRegistry, *, force: bool = False) -> None: ...
    async def run(self, item: WorkItem, tabs: TabProvider, log: JobLogger) -> ExtractOutcome: ...
```

Order (dependencies only):

1. `deviation_record` adapter → description, ROI fields, record id/url, opportunity ref.
   A skip here ends the item immediately.
2. `opportunity` adapter → product type (the CL-contract match needs it).
3. In parallel on the same `TabGroup`: `cl_contract`, `collateral`, `lms2_cl_contract`,
   `lms2_collateral` related lists / panels.
4. Persist: description-parsed values → `set_extracted`; ROI/product type/description →
   `attributes`; refs → `replace()`.
5. `EXTRACTED`, or `SKIPPED` with the first skip reason (FR-3.7). An adapter exception is
   logged and becomes a skip for that object, never a crash; `SessionExpired` propagates.
6. Early exit when `extracted_at` is set (FR-3.8), unless constructed with `force=True`.

### 9.3 `DeviationsZ02Submission`

```python
class DeviationsZ02Submission:
    async def run(self, item: WorkItem, tabs: TabGroup, log: JobLogger) -> SubmitOutcome: ...
```

```
precheck   → present?                     no → ALREADY_CLOSED            (FR-6.6)
apply      → group targets by object_kind; per object: read current, compare with
             the values the edit was based on (FR-6.2), write, collect outcomes
validate   → re-read every target: equality + still present                 (FR-6.4)
execute    → mark execute_attempted → click Implement → modal confirm →
             observe page state → mark execute_confirmed                   (FR-6.5/6.7)
```

`ALREADY_CLOSED` is not an error: the worker marks the job succeeded (FR-6.6).

### 9.4 Description parser

`parse_description_fields(description) -> dict[str, str | None]` stays pure, moves to
`workflows/deviations_z02/description.py`, and keeps the bare-`EMI-` exclusion rule.

---

## 10. Job execution (shared)

### 10.1 `Dispatcher`

```python
class Dispatcher:
    def __init__(self, jobs: JobRepository, workers: Sequence[Worker],
                 registry: WorkflowRegistry, settings: Settings,
                 auth: AuthGate) -> None: ...
    async def run_forever(self) -> None: ...
    def set_concurrency(self, n: int) -> None: ...
```

Claim loop + `asyncio.Semaphore(settings.workers)`. No thread pool and no global
`Queue.join()` (the current implementation's join waits for every queued task, which is a
correctness bug as soon as two jobs exist). Pauses with `AuthGate` (FR-7.8); requeues
stale leases at boot and on a timer (FR-7.2).

### 10.2 `Worker`

```python
class Worker:
    def __init__(self, name: str, registry: WorkflowRegistry, jobs: JobRepository,
                 auth: AuthGate, events: EventRepository) -> None: ...
    async def execute(self, job: Job) -> None: ...
```

Routes `(job.workflow, job.kind)` → `workflow.extraction` / `workflow.submission`;
owns the `TabGroup` lifecycle, phase markers, log lines, exception translation, and
guaranteed lease release.

### 10.3 Retry policy

| Failure | Retry | Result |
|---|---|---|
| `TransientBrowserError` | once | `FAILED(retryable)` |
| `SessionExpired` | no — requeue | `BLOCKED_AUTH`, pool paused |
| `AmbiguousRecord` | no | `SKIPPED` |
| `SaveRejected` / `ValueMismatch` | no | `NEEDS_REVIEW` |
| `AlreadyClosed` | no | `CLOSED(external)` — success |

---

## 11. Service + API

### 11.1 Services

```python
class WorkItemService:
    def list(self, workflow: str, status: WorkItemStatus | None, query: str | None,
             limit: int, offset: int) -> WorkItemPage: ...
    def get(self, workflow: str, key: str) -> WorkItemDetail: ...
    def patch_fields(self, workflow: str, key: str,
                     changes: Mapping[str, str | None]) -> WorkItemDetail: ...
    def discard_fields(self, workflow: str, key: str) -> WorkItemDetail: ...
    def submit(self, workflow: str, key: str) -> JobHandle: ...

class AdminService:
    def login(self) -> LoginHandle: ...
    def logout(self) -> None: ...
    def force_sync(self, workflow: str) -> SyncRun: ...
    def set_workers(self, count: int) -> QueueState: ...
    def queue(self) -> QueueState: ...
```

`WorkItemService` is synchronous: submit only enqueues. Operations that need the browser
live in `AdminService`, which owns the `BrowserRuntime` bridge.

### 11.2 Routes

`make_router(workflow: Workflow) -> APIRouter` is mounted once per workflow at
`/api/{workflow.name}`; the shape is identical for every workflow.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/workflows` | registered workflows + labels + field catalogue |
| GET | `/api/sessions` | auth state + last event |
| POST | `/api/sessions` | start manual login |
| DELETE | `/api/sessions` | clear snapshot |
| GET | `/api/syncs?workflow=` | last sync run + health |
| POST | `/api/syncs` | force a refresh |
| GET | `/api/deviations` | unified view, `?status=&q=&limit=&offset=` |
| GET | `/api/deviations/{key}` | one item, grouped by object |
| PATCH | `/api/deviations/{key}/field-values` | propose values |
| DELETE | `/api/deviations/{key}/field-values` | discard proposals |
| POST | `/api/deviations/{key}/jobs` | enqueue SUBMIT |
| GET | `/api/jobs?workflow=&kind=&status=` | queue |
| GET | `/api/jobs/{id}` / `GET /api/jobs/{id}/logs` | job detail |
| DELETE | `/api/jobs/{id}` | cancel a queued job |
| GET / PATCH | `/api/workers` | concurrency + in-flight |
| GET/POST | `/api/updates`, `/api/updates/checks`, `/api/updates/installations` | unchanged |

`/api/deviations` is simply `make_router(deviations)` mounted under its own noun — no
generic `/api/workflows/{name}/items`. Adding a workflow adds `/api/cancellations` with
the same shape and no new handler code.

Legacy aliases (`/views`, `/views/{id}/run`, `/deviations/run`, `/deviations/sync`, …) are
removed, not deprecated.

### 11.3 DTOs

Pydantic models at the boundary only: `WorkflowView` (name, labels, catalogue),
`ItemRow`, `ItemDetail` (attributes, field views, refs), `FieldView`
(extracted/last_synced/proposed/applied/status), `JobView`, `SyncView`, `AuthView`,
`QueueView`. Domain dataclasses never leak into JSON.

---

## 12. Invariants

Each should have a test.

1. **I1** Only a workflow's `SubmissionPipeline` writes terminal status.
2. **I2** At most one active job per `(workflow, item)` — enforced by the `jobs_active`
   partial unique index.
3. **I3** No final action unless every apply and validation succeeded and the item is
   still present (FR-6.5, FR-6.6).
4. **I4** A resync never overwrites `proposed` (FR-2.5).
5. **I5** An invalid sample mutates nothing (FR-2.9).
6. **I6** A terminal status cannot be written while a lease is held (FR-6.11) —
   `transition()` asserts it.
7. **I7** A job's effects are idempotent per phase, so a released lease is safe to re-run
   (FR-6.8).
8. **I8** Extraction is skipped when `extracted_at` is set (FR-3.8).
9. **I9** Core (`core/`, `salesforce/`, `pipeline/`, `jobs/`) imports no workflow module;
   workflows import core, never each other.

## 13. Test seams

- Pure: `is_valid_sample`, `parse_description_fields`, `normalise`, `fields_for`,
  `WorkItemStatus` transitions, `ClosureResolver` decision table, `map_row`.
- Repositories: temp-file SQLite, no browser.
- Pipelines: fake `ObjectAdapter`s and a fake `TabGroup`; assert phase order, abort on
  failure, idempotency, and that the final action is never reached on failed validation.
- Workflow registry: a minimal fake workflow proves a new workflow needs no core change
  (this is the test that keeps the abstraction honest).
- Browser layer: manual / behind `SF_LIVE_TESTS=1`.
