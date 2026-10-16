# Architecture

## 1. The Ten Ground Rules

Every contributor to this codebase must internalize these. They are not
suggestions — they are the invariants the whole system is built on. Breaking
any of them silently corrupts inventory, financials, or regulatory filings.

### Rule 1 — The ledger is the truth
`StockMovement` rows are **append-only**. Never `UPDATE`, never `DELETE`.
`InventoryLot.quantity_on_hand` is a *denormalized cache* that exists only
for read performance.

**Corrections are written, not edited.** If a receipt was 100 kg but should
have been 90 kg, you write an `ADJUSTMENT` of −10 kg. The original row stays.

Why: TTB and provincial regulators require a reconstructable audit trail.
Recalls require knowing exactly what happened, in order. Overwriting rows
destroys both.

### Rule 2 — All writes go through services
Views, serializers, admin actions, and management commands must call functions
in `apps/<app>/services.py`. They must **never** call `.save()`, `.create()`,
`.update()`, or `.delete()` on transactional models directly.

Why: services are the only place that can guarantee atomicity + cache
consistency. If a view writes to `quantity_on_hand` directly, the ledger and
the cache diverge and nothing detects it until reconcile runs.

### Rule 3 — Every mutation is wrapped in a transaction
Any function that writes to more than one row **must** use
`@transaction.atomic` and lock the rows it depends on with
`select_for_update()`. See `docs/TRANSACTIONS.md` for the full pattern and
race-condition examples.

### Rule 4 — Facility scoping is enforced at the manager level
A user authorized for Facility A must not be able to query Facility B's
data, even by guessing IDs. Use the `FacilityScopedManager` (see
`apps/core/managers.py`). Never trust a facility ID from a request body.

### Rule 5 — Immutable financial history
Cost calculations (`Batch.cost`, `OrderLine.cost`, COGS) are derived by
walking the ledger at the moment of posting. Once a batch is closed or an
order is invoiced, its numbers are frozen into a `JournalEntry`. Later
corrections write new journal entries; they never mutate prior ones.

### Rule 6 — Idempotency for external triggers
Every Celery task and every management command that mutates state must be
safe to run twice. Use `get_or_create` on a natural key, or check for an
existing row before writing. This matters because cron can double-fire,
tasks can be retried, and operators can run things manually.

### Rule 7 — Background work is asynchronous, but never load-bearing
Celery tasks may *compute* things (reports, rollups, alerts) but the
synchronous request path must never depend on a task completing. A user
receiving a 200 from `POST /api/orders/` must not be told "wait for the
task." Tasks write results to models; the frontend polls or subscribes.

### Rule 8 — No mutable global state in services
Service functions take everything they need as arguments (user, facility,
datetime). No `threading.local`, no module-level caches, no `request`
objects passed around. This is what makes them safely testable and callable
from Celery, admin, and cron contexts.

### Rule 9 — Money and quantity are `Decimal`, never `float`
`Decimal` with fixed precision (3 for quantities, 4 for unit costs, 2 for
totals). Floats introduce rounding errors that compound across batches.
Enforce in the model field definitions and in any serializer.

### Rule 10 — Every new state-changing flow gets a workflow doc
If you add a new process (e.g., "returns handling"), you add a section to
`docs/WORKFLOWS.md` describing the state machine, the events, and the
service functions involved. Undocumented flows are how systems rot.

---

## 2. Module Layout

```
apps/
  core/         Users, Facility, shared mixins, Celery app, base managers
  inventory/    Items, lots, movements, ledger services
  production/   Recipes, tanks, batches, brew lifecycle
  sales/        Customers, orders, fulfillment, allocation
  finance/      Journal entries, COGS rollup, period close
  compliance/   TTB reports, tax filings, lot traceability exports
  quality/      Fermentation readings, QC tests, gates
  forecasting/  Demand planning, reorder suggestions (future)
  reporting/    Cross-domain read models, dashboards (future)
```

Each app has the same internal shape:

```
apps/<app>/
  models.py             Data definitions (no business logic)
  services.py           ALL mutations live here
  selectors.py          Read-only query helpers
  tasks.py              Celery tasks (thin wrappers around services)
  api/
    serializers.py
    views.py
    urls.py
  admin.py
  tests/
  migrations/
```

**The dependency rule:** `sales` may import from `inventory` and
`production`. `inventory` may not import from `sales`. `finance` may import
from all three but nothing imports from `finance`. This is how you avoid
circular imports and keep the ledger at the bottom.

---

## 3. Why These Choices

**Postgres over MySQL**: `SELECT … FOR UPDATE` semantics are cleaner,
JSONB is native (for compliance payloads), and partial indexes are usable
from Django's ORM.

**DRF + drf-spectacular over GraphQL**: An ERP has a small number of
well-defined resources. REST + OpenAPI gives you a mobile client for free
and keeps the mental model simple.

**Celery over cron**: Cron cannot express dependencies ("run B after A"),
retries, or fan-out. Celery can. But cron-shaped work still fits Celery —
just use `apply_async(eta=...)` for schedules instead of standing up a
separate timer.

**No Redis for caching**: Redis is used **only** as the Celery broker and
result backend. We do not cache ORM results or page fragments. Premature
caching in an ERP is how you ship stale inventory numbers to a brewer at
7am on brew day.

---

## 4. What's Deliberately Not Here (Yet)

- Multi-tenant row-level security (single-tenant-per-deployment for now).
- Real-time push (SSE/WebSockets) — polling is fine at prototype scale.
- Event sourcing — the ledger *is* an event log for inventory, but we
  don't generalize the pattern to the whole system.
- Microservices — one process, one database, one deploy.
