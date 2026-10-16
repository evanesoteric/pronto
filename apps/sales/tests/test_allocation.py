from decimal import Decimal
import pytest
from django.contrib.auth import get_user_model

from apps.core.models import Facility
from apps.inventory import services as inv
from apps.inventory.models import Item, ItemCategory
from apps.production.models import Recipe
from apps.sales import services as sales
from apps.sales.models import Customer, OrderStatus

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def scenario():
    user = User.objects.create_user("sales", role="sales")
    facility = Facility.objects.create(name="Main", code="main")
    beer = Item.objects.create(
        sku="KEG-PALE", name="Pale Ale Keg", category=ItemCategory.FINISHED, unit="L"
    )
    # Two finished lots, FIFO by received_at
    inv.receive_stock(item=beer, facility=facility, lot_number="L1",
                       quantity=Decimal("500"), unit_cost=Decimal("1"),
                       performed_by=user)
    inv.receive_stock(item=beer, facility=facility, lot_number="L2",
                       quantity=Decimal("500"), unit_cost=Decimal("1"),
                       performed_by=user)

    customer = Customer.objects.create(name="Bar", account_number="C001")
    order = sales.create_order(
        customer=customer, facility=facility, number="O001",
        order_date="2026-10-06",
        lines=[{"item": beer, "quantity": Decimal("700"),
                "unit_price": Decimal("3.50")}],
        performed_by=user,
    )
    return user, facility, beer, order


def test_allocate_splits_across_lots(scenario):
    user, facility, beer, order = scenario
    sales.confirm_order(order=order, performed_by=user)
    sales.allocate_order(order=order, performed_by=user)
    order.refresh_from_db()
    assert order.status == OrderStatus.ALLOCATED
    line = order.lines.first()
    assert line.allocated_quantity == Decimal("700")
    assert not line.backordered


def test_allocate_marks_backorder(scenario):
    user, facility, beer, order = scenario
    line = order.lines.first()
    line.quantity = Decimal("1200")  # more than available
    line.save()
    sales.confirm_order(order=order, performed_by=user)
    sales.allocate_order(order=order, performed_by=user)
    line.refresh_from_db()
    assert line.allocated_quantity == Decimal("1000")
    assert line.backordered


def test_ship_consumes_ledger(scenario):
    user, facility, beer, order = scenario
    sales.confirm_order(order=order, performed_by=user)
    sales.allocate_order(order=order, performed_by=user)
    sales.ship_order(order=order, performed_by=user)

    from apps.inventory.models import InventoryLot
    l1 = InventoryLot.objects.get(lot_number="L1")
    l2 = InventoryLot.objects.get(lot_number="L2")
    assert l1.quantity_on_hand == Decimal("0")
    assert l2.quantity_on_hand == Decimal("300")


def test_double_allocation_is_idempotent_on_quantity(scenario):
    """
    Allocating twice should not double-reserve. The service checks
    remaining_to_ship, and the second call sees needed == 0.
    """
    user, facility, beer, order = scenario
    sales.confirm_order(order=order, performed_by=user)
    sales.allocate_order(order=order, performed_by=user)
    sales.allocate_order(order=order, performed_by=user)
    line = order.lines.first()
    assert line.allocated_quantity == Decimal("700")
