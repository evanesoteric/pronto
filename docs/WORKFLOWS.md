# Workflows

Every state-changing process in the system. Each entry lists the state
machine, the events (API calls or tasks) that drive it, and the service
functions that implement it.

The rule: **if a flow isn't documented here, don't build it.** Add the
doc first, then the code.

---

## 1. Receiving Stock

**Trigger:** A delivery arrives at a facility.

**States:** N/A — this is a single-shot operation.

**Service:** `apps.inventory.services.receive_stock`

**Steps:**
1. Operator enters item SKU, lot number, quantity, unit cost.
2. Service `get_or_create`s the `InventoryLot` by `(item, lot_number, facility)`.
3. Service writes a `StockMovement(delta=+qty, reason=RECEIPT)`.
4. Lot cache updated in the same transaction.

**Idempotency:** If called twice with the same lot + reference, it creates
two receipts. That is correct — two deliveries of the same lot number are
two receipts. The caller is responsible for not double-clicking; the
frontend disables the button after submit.

**Emits:** Nothing. (Future: could trigger a QC sample task.)

---

## 2. Brewing a Batch

**Trigger:** Brewer clicks "Start Brew" on a planned batch.

**States:**
```
PLANNED ──start_brew──▶ BREWING ──transfer_to_tank──▶ FERMENTING
FERMENTING ──advance──▶ CONDITIONING ──package──▶ PACKAGED ──advance──▶ CLOSED
```

**Services:**
- `apps.production.services.create_batch` (PLANNED)
- `apps.production.services.start_brew` (PLANNED → BREWING; consumes
  ingredients via `inventory.services.consume_fifo`)
- `apps.production.services.transfer_to_tank` (BREWING → FERMENTING;
  acquires tank)
- `apps.production.services.advance_status` (FERMENTING → CONDITIONING,
  CONDITIONING → PACKAGED, PACKAGED → CLOSED)
- `apps.production.services.package_batch` (creates finished good lot)

**Failure modes:**
- `InsufficientStock` if any ingredient is short → the entire brew start
  rolls back. No partial consumption. The user is told which item is short
  and by how much.
- `BatchStateError` if the transition is illegal (e.g., trying to start a
  batch that's already BREWING).

**Side effects:**
- Tank status flips to `fermenting` on `transfer_to_tank` and back to
  `idle` when the batch closes.
- `Batch.status` changes drive dashboards and reports.

---

## 3. Packaging a Batch

**Trigger:** Brewer clicks "Package" and specifies finished good item,
volume, container count, and finished lot number.

**Service:** `apps.production.services.package_batch`

**Steps:**
1. Lock the batch. Verify it's in CONDITIONING or PACKAGED.
2. Walk all `StockMovement(delta<0, batch=batch)` rows to compute the total
   ingredient cost for the batch.
3. Divide by packaged volume to compute `unit_cost` for the finished lot.
4. Call `inventory.services.receive_stock` to create the finished good lot
   and its `PACKAGE_PRODUCE` movement.
5. Flip batch to PACKAGED, stamp `packaged_at`.

**Idempotency:** Guarded by status. Once PACKAGED, re-invocation raises
`BatchStateError`. Safe to retry on failure — either the whole thing
committed or none of it did.

**Future:** This service will also consume packaging materials (cans,
labels, cartons) via `consume_fifo` for each.

---

## 4. Order Fulfillment

**Trigger:** Sales receives an order and confirms it.

**States:**
```
DRAFT ──confirm──▶ CONFIRMED ──allocate──▶ ALLOCATED
ALLOCATED ──ship──▶ FULFILLED ──invoice──▶ INVOICED
```

**Services (see `apps/sales/services.py`):**
- `create_order` → DRAFT
- `confirm_order` → CONFIRMED
- `allocate_order` → ALLOCATED (reserves lots, does NOT move inventory yet)
- `ship_order` → FULFILLED (consumes allocated lots via the ledger)
- `invoice_order` → INVOICED (creates a `JournalEntry` for COGS)

**Why allocation is separate from shipping:** In beverage sales, an order
may be confirmed on Tuesday and shipped on Friday. Between those, the
finished good lot is *promised* to that order — no other order should be
allowed to consume it. Allocation locks that promise down without moving
stock until the truck is loaded.

**Allocation model:** A `StockAllocation` row (order_line, lot, quantity)
is created. Available quantity for a lot becomes
`quantity_on_hand - sum(open allocations)`.

**Failure modes:**
- `InsufficientStock` during allocation → order line is marked
  `backordered`, the rest of the order proceeds. Partial allocation is
  allowed at the line level.
- Tank/`InsufficientStock` during ship → raises, whole ship rolls back.

---

## 5. Inventory Adjustment (Cycle Count)

**Trigger:** Operator performs a physical count and finds a discrepancy.

**Service:** `apps.inventory.services.adjust_stock`

**Steps:**
1. Operator submits the counted quantity; the system computes `delta =
   counted − cached`.
2. If `delta == 0`, no-op.
3. Otherwise write `StockMovement(delta, reason=ADJUSTMENT, note="cycle
   count: <explanation>")`.

**Policy:** Every adjustment over some threshold (configurable, default
5% of lot quantity) requires a `note`. This is enforced in the service.

---

## 6. Inventory Transfer Between Facilities

**Trigger:** Stock needs to move from Facility A to Facility B.

**States:** N/A — it's a two-phase atomic operation.

**Service:** `apps.inventory.services.transfer_stock` (build this out from
the scaffold; documented here so it's designed before it's built).

**Steps:**
1. Lock source lot.
2. Write `TRANSFER_OUT` movement (−qty).
3. Lock/create destination lot (same item, same lot_number, at Facility B).
4. Write `TRANSFER_IN` movement (+qty).
5. Both moves in one transaction.

**Idempotency:** The caller passes a `reference`. If a movement with that
reference already exists, the service raises rather than double-transferring.

---

## 7. Batch Cost Rollup (nightly)

**Trigger:** Celery beat, nightly at 02:00.

**Task:** `apps.finance.tasks.rollup_batch_costs`

**Steps:**
1. Find batches closed in the last 24h without a rolled-up cost.
2. For each, compute `sum(-delta * lot.unit_cost)` across its movements.
3. Write a `BatchCost` row.
4. Emit a `JournalEntry` (debit WIP, credit inventory) if the batch was
   packaged and shipped.

**Idempotency:** `BatchCost` has a `OneToOneField` to `Batch`. Re-running
hits an `IntegrityError` which is caught and logged as "already rolled up."

---

## 8. TTB Brewers Report (monthly)

**Trigger:** Celery beat, first of month at 04:00.

**Task:** `apps.compliance.tasks.generate_ttb_report`

**Steps:**
1. Determine the reporting period (previous calendar month).
2. Query the ledger for all `RECEIPT`, `BREW_CONSUME`, `PACKAGE_PRODUCE`,
   `SHIPMENT`, `SHRINKAGE`, and `ADJUSTMENT` movements within the period,
   grouped by item category.
3. Compute the TTB-required totals (production, removals, losses,
   inventory on hand).
4. Write a `TTBReport` row with a JSON snapshot of the numbers.
5. Emit a CSV in the exact format TTB's Permits Online accepts.

**Idempotency:** Unique on `(facility, period_start, period_end)`.
Re-running regenerates the JSON but does not duplicate the row.

**Manual override:** Operators can edit the JSON before filing. The
service computes the "system numbers"; the JSON field holds the "as-filed
numbers." Once `submitted_at` is set, further regeneration is blocked.

---

## 9. Period Close (monthly)

**Trigger:** CFO clicks "Close Period" in the admin after month-end.

**Task:** `apps.finance.tasks.close_period` (invoked via admin action).

**Steps:**
1. Ensure no batches are open from the period.
2. Roll up all unposted `StockMovement` rows into `JournalEntry` batches
   by GL account.
3. Post the entries (immutable).
4. Mark the `AccountingPeriod` as closed — subsequent attempts to post
   movements into that period fail.

**Failure modes:**
- Open batches → `PeriodCloseError`, with a list of blocking batch numbers.
- Missing GL mappings → `PeriodCloseError`, listing the unmapped items.

**This is the most dangerous command in the system.** It mutates financial
state and is not easily reversed. Restrict execution to a single role
(`finance_close`) and log everything.

---

## 10. Low Stock Alert

**Trigger:** Celery beat, every 15 minutes.

**Task:** `apps.forecasting.tasks.low_stock_scan`

**Steps:**
1. For each facility, call `inventory.selectors.low_stock_items`.
2. Diff against alerts already sent (tracked in `StockAlert`).
3. For newly-below-threshold items, send an email/notification.

**Idempotency:** `StockAlert` has a unique constraint on
`(item, facility, resolved_at=null)`. Once raised, it isn't re-raised
until resolved.
