"""Dashboard: cross-module KPIs for the landing page."""
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user
from ..services import ledger

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard", response_model=schemas.DashboardStats)
def dashboard(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    # Low-stock: products whose total on-hand is at or below their reorder level.
    low_stock = 0
    for p in db.query(models.Product).all():
        on_hand = db.scalar(
            select(func.coalesce(func.sum(models.StockLevel.quantity), 0)).where(
                models.StockLevel.product_id == p.id
            )
        )
        if int(on_hand or 0) <= p.reorder_level:
            low_stock += 1

    # Inventory valuation at cost = sum(on_hand * cost_price).
    inventory_value = Decimal(0)
    for level in db.query(models.StockLevel).all():
        inventory_value += Decimal(level.product.cost_price) * level.quantity

    revenue = ledger.account_balance(
        db, db.query(models.Account).filter(models.Account.code == ledger.ACC_SALES).first()
    ) if db.query(models.Account).filter(models.Account.code == ledger.ACC_SALES).first() else Decimal(0)

    purchases = Decimal(0)
    ap = db.query(models.Account).filter(models.Account.code == ledger.ACC_AP).first()
    if ap:
        purchases = ledger.account_balance(db, ap)

    pipeline = db.scalar(
        select(func.coalesce(func.sum(models.Lead.estimated_value), 0)).where(
            models.Lead.stage.notin_(("won", "lost"))
        )
    ) or 0

    return schemas.DashboardStats(
        products=db.query(models.Product).count(),
        low_stock=low_stock,
        customers=db.query(models.Customer).count(),
        suppliers=db.query(models.Supplier).count(),
        open_sales_orders=db.query(models.SalesOrder).filter(models.SalesOrder.status == "draft").count(),
        open_purchase_orders=db.query(models.PurchaseOrder).filter(models.PurchaseOrder.status == "draft").count(),
        employees=db.query(models.Employee).filter(models.Employee.is_active).count(),
        open_leads=db.query(models.Lead).filter(models.Lead.stage.notin_(("won", "lost"))).count(),
        revenue=revenue,
        purchases=purchases,
        pipeline_value=Decimal(pipeline),
        inventory_value=inventory_value,
    )
