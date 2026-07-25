"""Cross-module business logic: inventory movements and double-entry posting.

This is where the modules stop being independent CRUD tables and start
behaving like an ERP: confirming a sales order both *issues stock* and *posts
revenue + cost of goods sold*, and receiving a purchase order both *receives
stock* and *posts a payable*. Keeping this logic in one place means the
accounting ledger and the inventory ledger can never drift apart.
"""
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models

# Well-known account codes used by the automatic postings below. They are
# created in seed.py; look-ups are by code so the logic is data-driven.
ACC_CASH = "1000"          # Cash / Bank (asset)
ACC_INVENTORY = "1200"     # Inventory (asset)
ACC_AP = "2000"            # Accounts Payable (liability)
ACC_SALES = "4000"         # Sales Revenue (income)
ACC_COGS = "5000"          # Cost of Goods Sold (expense)


def _account_id(db: Session, code: str) -> int:
    acc = db.scalar(select(models.Account).where(models.Account.code == code))
    if acc is None:
        raise ValueError(f"Required account {code} is missing from the chart of accounts")
    return acc.id


def apply_stock_movement(
    db: Session,
    product_id: int,
    warehouse_id: int,
    quantity: int,
    movement_type: str,
    reference: str = "",
) -> models.StockLevel:
    """Record a stock movement and update the materialized on-hand balance.

    `quantity` is signed: positive for receipts, negative for issues.
    """
    db.add(
        models.StockMovement(
            product_id=product_id,
            warehouse_id=warehouse_id,
            quantity=quantity,
            movement_type=movement_type,
            reference=reference,
        )
    )
    level = db.scalar(
        select(models.StockLevel).where(
            models.StockLevel.product_id == product_id,
            models.StockLevel.warehouse_id == warehouse_id,
        )
    )
    if level is None:
        level = models.StockLevel(
            product_id=product_id, warehouse_id=warehouse_id, quantity=0
        )
        db.add(level)
    level.quantity += quantity
    return level


def post_journal(db: Session, memo: str, source: str, lines: list[tuple[int, Decimal, Decimal]]):
    """Create a balanced journal entry from (account_id, debit, credit) tuples."""
    total_debit = sum((Decimal(d) for _, d, _ in lines), Decimal(0))
    total_credit = sum((Decimal(c) for _, _, c in lines), Decimal(0))
    if total_debit != total_credit:
        raise ValueError(
            f"Journal entry does not balance: debit {total_debit} != credit {total_credit}"
        )
    entry = models.JournalEntry(memo=memo, source=source)
    for account_id, debit, credit in lines:
        entry.lines.append(
            models.JournalLine(account_id=account_id, debit=Decimal(debit), credit=Decimal(credit))
        )
    db.add(entry)
    return entry


def confirm_sales_order(db: Session, order: models.SalesOrder) -> None:
    """Issue stock and post revenue + COGS for a confirmed sales order."""
    if order.status != "draft":
        raise ValueError("Only draft sales orders can be confirmed")

    revenue = Decimal(0)
    cogs = Decimal(0)
    for line in order.lines:
        apply_stock_movement(
            db,
            product_id=line.product_id,
            warehouse_id=order.warehouse_id,
            quantity=-line.quantity,
            movement_type="issue",
            reference=order.number,
        )
        revenue += Decimal(line.unit_price) * line.quantity
        cogs += Decimal(line.product.cost_price) * line.quantity

    # Revenue recognition: debit Cash, credit Sales Revenue.
    post_journal(
        db,
        memo=f"Sales order {order.number}",
        source="sales",
        lines=[
            (_account_id(db, ACC_CASH), revenue, Decimal(0)),
            (_account_id(db, ACC_SALES), Decimal(0), revenue),
        ],
    )
    # Cost of goods sold: debit COGS, credit Inventory.
    if cogs > 0:
        post_journal(
            db,
            memo=f"COGS for {order.number}",
            source="sales",
            lines=[
                (_account_id(db, ACC_COGS), cogs, Decimal(0)),
                (_account_id(db, ACC_INVENTORY), Decimal(0), cogs),
            ],
        )
    order.status = "confirmed"


def receive_purchase_order(db: Session, order: models.PurchaseOrder) -> None:
    """Receive stock and post the payable for a purchase order."""
    if order.status != "draft":
        raise ValueError("Only draft purchase orders can be received")

    total = Decimal(0)
    for line in order.lines:
        apply_stock_movement(
            db,
            product_id=line.product_id,
            warehouse_id=order.warehouse_id,
            quantity=line.quantity,
            movement_type="receipt",
            reference=order.number,
        )
        total += Decimal(line.unit_price) * line.quantity

    # Debit Inventory (asset up), credit Accounts Payable (liability up).
    post_journal(
        db,
        memo=f"Purchase order {order.number}",
        source="purchase",
        lines=[
            (_account_id(db, ACC_INVENTORY), total, Decimal(0)),
            (_account_id(db, ACC_AP), Decimal(0), total),
        ],
    )
    order.status = "received"


def account_balance(db: Session, account: models.Account) -> Decimal:
    """Signed balance using normal-balance sign conventions per account type.

    Assets and expenses carry a debit-normal balance; liabilities, equity and
    income carry a credit-normal balance. Returning the normal-balance figure
    keeps every account's balance a positive number in typical operation.
    """
    debit, credit = db.execute(
        select(
            func.coalesce(func.sum(models.JournalLine.debit), 0),
            func.coalesce(func.sum(models.JournalLine.credit), 0),
        ).where(models.JournalLine.account_id == account.id)
    ).one()
    debit, credit = Decimal(debit), Decimal(credit)
    if account.type in ("asset", "expense"):
        return debit - credit
    return credit - debit
