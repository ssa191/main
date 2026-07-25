"""Purchasing & Suppliers: suppliers and purchase orders.

Receiving a purchase order increases stock and posts the payable to the ledger.
"""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user
from ..services import ledger

router = APIRouter(prefix="/api", tags=["purchasing"])


def _next_number(db: Session, model, prefix: str) -> str:
    count = db.query(model).count() + 1
    return f"{prefix}-{count:05d}"


def _order_out(order: models.PurchaseOrder) -> schemas.PurchaseOrderOut:
    out = schemas.PurchaseOrderOut.model_validate(order)
    out.supplier_name = order.supplier.name if order.supplier else None
    out.lines = []
    for line in order.lines:
        lo = schemas.OrderLineOut.model_validate(line)
        lo.product_name = line.product.name if line.product else None
        lo.line_total = line.line_total
        out.lines.append(lo)
    return out


# ------------------------------ Suppliers --------------------------------- #
@router.get("/suppliers", response_model=list[schemas.SupplierOut])
def list_suppliers(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return db.query(models.Supplier).order_by(models.Supplier.name).all()


@router.post("/suppliers", response_model=schemas.SupplierOut, status_code=201)
def create_supplier(
    payload: schemas.SupplierBase,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    supplier = models.Supplier(**payload.model_dump())
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return supplier


# -------------------------- Purchase orders ------------------------------- #
@router.get("/purchase-orders", response_model=list[schemas.PurchaseOrderOut])
def list_purchase_orders(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    orders = db.query(models.PurchaseOrder).order_by(models.PurchaseOrder.id.desc()).all()
    return [_order_out(o) for o in orders]


@router.post("/purchase-orders", response_model=schemas.PurchaseOrderOut, status_code=201)
def create_purchase_order(
    payload: schemas.PurchaseOrderCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    if not db.get(models.Supplier, payload.supplier_id):
        raise HTTPException(status_code=404, detail="Supplier not found")
    if not db.get(models.Warehouse, payload.warehouse_id):
        raise HTTPException(status_code=404, detail="Warehouse not found")
    if not payload.lines:
        raise HTTPException(status_code=400, detail="Order must have at least one line")

    order = models.PurchaseOrder(
        number=_next_number(db, models.PurchaseOrder, "PO"),
        supplier_id=payload.supplier_id,
        warehouse_id=payload.warehouse_id,
        order_date=payload.order_date or date.today(),
    )
    total = Decimal(0)
    for line in payload.lines:
        product = db.get(models.Product, line.product_id)
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {line.product_id} not found")
        price = line.unit_price if line.unit_price is not None else product.cost_price
        order.lines.append(
            models.PurchaseOrderLine(
                product_id=product.id, quantity=line.quantity, unit_price=price
            )
        )
        total += Decimal(price) * line.quantity
    order.total = total
    db.add(order)
    db.commit()
    db.refresh(order)
    return _order_out(order)


@router.post("/purchase-orders/{order_id}/receive", response_model=schemas.PurchaseOrderOut)
def receive_purchase_order(
    order_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    order = db.get(models.PurchaseOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    try:
        ledger.receive_purchase_order(db, order)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    db.refresh(order)
    return _order_out(order)


@router.post("/purchase-orders/{order_id}/cancel", response_model=schemas.PurchaseOrderOut)
def cancel_purchase_order(
    order_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    order = db.get(models.PurchaseOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if order.status == "received":
        raise HTTPException(status_code=400, detail="Cannot cancel a received order")
    order.status = "cancelled"
    db.commit()
    db.refresh(order)
    return _order_out(order)
