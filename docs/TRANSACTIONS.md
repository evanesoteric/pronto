# Transactions and Race Conditions

Inventory is a shared resource. Two brewers on two tablets, both trying to
draw down the same lot of 2-row malt at the same time, is a real scenario
in a working brewery. This document explains exactly how the codebase
prevents that from corrupting data.

## The Problem

Consider naive code:

```python
# DO NOT DO THIS
lot = InventoryLot.objects.get(pk=lot_id)
if lot.quantity_on_hand >= quantity:
    lot.quantity_on_hand -= quantity
    lot.save()
```

Two workers execute this concurrently, both read `quantity_on_hand = 10`,
both want to consume 8. Both pass the check. Both write `2`. Result:
**16 kg consumed from a 10 kg lot**. The cache now says 2, but the ledger
says −6. Reconcile catches it a day later. By then the batch was packaged.

## The Fix — Three Layers

### Layer 1: Lock the row

```python
with transaction.atomic():
    lot = InventoryLot.objects.select_for_update().get(pk=lot_id)
    if lot.quantity_on_hand < quantity:
        raise InsufficientStock(...)
    StockMovement.objects.create(lot=lot, delta=-quantity, ...)
    InventoryLot.objects.filter(pk=lot.pk).update(
        quantity_on_hand=F("quantity_on_hand") - quantity
    )
```

`select_for_update()` emits `SELECT … FOR UPDATE`, which takes a row-level
lock. Worker B blocks at the `.get()` until Worker A commits. Then B sees
`quantity_on_hand = 2`, the check fails, `InsufficientStock` raises, and B
rolls back. **One winner, one loser, no corruption.**

### Layer 2: Use `F()` expressions for the cache update

Even with a lock, `lot.quantity_on_hand = lot.quantity_on_hand - quantity`
followed by `lot.save()` is a read-modify-write that can be miscompiled if
you ever refactor to remove the lock. `F("quantity_on_hand") - quantity`
pushes the arithmetic into SQL:

```sql
UPDATE inventory_inventorylot
SET quantity_on_hand = quantity_on_hand - 8
WHERE id = 42;
```

Postgres guarantees this is atomic at the row level. Belt and suspenders.

### Layer 3: `@transaction.atomic` around the whole unit of work

The lock is held until the transaction commits. If any step inside (say,
the `StockMovement.objects.create`) raises, the whole thing rolls back and
the lock releases. Nothing partial ever hits disk.

## The Canonical Pattern

Every service function that mutates transactional state follows this shape:

```python
@transaction.atomic
def do_something(*, arg1, arg2, performed_by):
    # 1. Lock every row you will read-then-write, in a stable order.
    lot = InventoryLot.objects.select_for_update().get(pk=lot_id)
    batch = Batch.objects.select_for_update().get(pk=batch_id)

    # 2. Validate invariants against the locked state.
    if lot.quantity_on_hand < quantity:
        raise InsufficientStock(...)

    # 3. Write the immutable ledger row.
    movement = StockMovement.objects.create(...)

    # 4. Update the denormalized cache atomically.
    InventoryLot.objects.filter(pk=lot.pk).update(
        quantity_on_hand=F("quantity_on_hand") + movement.delta
    )

    # 5. Return whatever the caller needs.
    return movement
```

## Lock Ordering

Postgres detects and aborts deadlocks, but you should still acquire locks
in a consistent order across the codebase to avoid them entirely.

**Global rule:** always lock in this order —
1. `InventoryLot`
2. `Batch`
3. `Order`
4. `Tank`

If you need to lock two lots (e.g., a transfer), lock by `pk` ascending:

```python
lots = (InventoryLot.objects
        .select_for_update()
        .filter(pk__in=[a, b])
        .order_by("pk"))
```

If you can't express the lock order, that's a sign the operation should be
split into two transactions.

## Isolation Level

Postgres defaults to `READ COMMITTED`. That's what we use. It's sufficient
because:
- Every cross-row invariant we care about is guarded by an explicit lock.
- We never rely on "read a value, then later write based on it" without a
  lock.

Do **not** set `SERIALIZABLE` at the project level — it'll cause retry
storms under load. If you find a query that needs it, use
`transaction.atomic()` with an explicit `SERIALIZABLE` isolation level on
that one function.

## What About the Reconcile Command?

`reconcile_inventory` exists because eventually a bug will slip through.
It walks every lot and compares `quantity_on_hand` to `SUM(delta)`. Any
mismatch is logged and (with `--fix`) repaired. This is not a substitute
for correct transactions — it's an audit net.

Run it nightly via Celery beat. If it ever fires, someone on-call gets a
Slack message. A reconcile fix is a **warning**, not a resolution — the
underlying race always gets investigated.

## Celery Task Transactions

Celery tasks are not magic. Inside a task:

```python
@app.task(bind=True, max_retries=3)
def package_batch_task(self, batch_id, ...):
    try:
        package_batch(batch_id=batch_id, ...)
    except InsufficientStock as e:
        # Do NOT retry — this is a business error, not a transient one.
        raise
    except OperationalError as e:
        # Transient DB error — retry with backoff.
        raise self.retry(exc=e, countdown=2 ** self.request.retries)
```

Key points:
- Business-logic exceptions (`InsufficientStock`, `BatchStateError`) are
  **never retried**. Retrying them just re-raises.
- Infrastructure exceptions (`OperationalError`, `InterfaceError`) are
  retried with exponential backoff.
- Every task is idempotent (Rule 6 in `ARCHITECTURE.md`). If it fires twice,
  the second invocation either no-ops or produces the same result.

## Test Coverage

`apps/inventory/tests/test_concurrency.py` has a real race-condition test
using threads and a Postgres test database. It asserts that 20 threads
trying to consume 1 unit each from a 10-unit lot results in exactly 10
movements and 0 on hand — not 15, not 20, not negative.

If you refactor the lock away, that test fails. Keep it green.
