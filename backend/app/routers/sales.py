"""Sales & Orders: customers and sales orders.

Confirming a sales order is the key business transaction — it issues stock and
posts revenue/COGS to the ledger via the shared service layer.
"""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user
from ..services import ledger

router = APIRouter(prefix="/api", tags=["sales"])


def _next_number(db: Session, model, prefix: str) -> str:
    count = db.query(model).count() + 1
    return f"{prefix}-{count:05d}"


def _order_out(order: models.SalesOrder) -> schemas.SalesOrderOut:
    out = schemas.SalesOrderOut.model_validate(order)
    out.customer_name = order.customer.name if order.customer else None
    out.lines = []
    for line in order.lines:
        lo = schemas.OrderLineOut.model_validate(line)
        lo.product_name = line.product.name if line.product else None
        lo.line_total = line.line_total
        out.lines.append(lo)
    return out


# ------------------------------ Customers --------------------------------- #
@router.get("/customers", response_model=list[schemas.CustomerOut])
def list_customers(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return db.query(models.Customer).order_by(models.Customer.name).all()


@router.post("/customers", response_model=schemas.CustomerOut, status_code=201)
def create_customer(
    payload: schemas.CustomerBase,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    customer = models.Customer(**payload.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


# ---------------------------- Sales orders -------------------------------- #
@router.get("/sales-orders", response_model=list[schemas.SalesOrderOut])
def list_sales_orders(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    orders = db.query(models.SalesOrder).order_by(models.SalesOrder.id.desc()).all()
    return [_order_out(o) for o in orders]


@router.post("/sales-orders", response_model=schemas.SalesOrderOut, status_code=201)
def create_sales_order(
    payload: schemas.SalesOrderCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    if not db.get(models.Customer, payload.customer_id):
        raise HTTPException(status_code=404, detail="Customer not found")
    if not db.get(models.Warehouse, payload.warehouse_id):
        raise HTTPException(status_code=404, detail="Warehouse not found")
    if not payload.lines:
        raise HTTPException(status_code=400, detail="Order must have at least one line")

    order = models.SalesOrder(
        number=_next_number(db, models.SalesOrder, "SO"),
        customer_id=payload.customer_id,
        warehouse_id=payload.warehouse_id,
        order_date=payload.order_date or date.today(),
    )
    total = Decimal(0)
    for line in payload.lines:
        product = db.get(models.Product, line.product_id)
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {line.product_id} not found")
        price = line.unit_price if line.unit_price is not None else product.unit_price
        order.lines.append(
            models.SalesOrderLine(
                product_id=product.id, quantity=line.quantity, unit_price=price
            )
        )
        total += Decimal(price) * line.quantity
    order.total = total
    db.add(order)
    db.commit()
    db.refresh(order)
    return _order_out(order)


@router.post("/sales-orders/{order_id}/confirm", response_model=schemas.SalesOrderOut)
def confirm_sales_order(
    order_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    order = db.get(models.SalesOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Sales order not found")
    try:
        ledger.confirm_sales_order(db, order)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    db.refresh(order)
    return _order_out(order)


@router.post("/sales-orders/{order_id}/cancel", response_model=schemas.SalesOrderOut)
def cancel_sales_order(
    order_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    order = db.get(models.SalesOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Sales order not found")
    if order.status == "confirmed":
        raise HTTPException(status_code=400, detail="Cannot cancel a confirmed order")
    order.status = "cancelled"
    db.commit()
    db.refresh(order)
    return _order_out(order)
