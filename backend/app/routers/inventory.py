"""Inventory & Products: catalog, warehouses, stock levels and adjustments."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user
from ..services import ledger

router = APIRouter(prefix="/api", tags=["inventory"])


def _product_out(db: Session, p: models.Product) -> schemas.ProductOut:
    on_hand = db.scalar(
        select(func.coalesce(func.sum(models.StockLevel.quantity), 0)).where(
            models.StockLevel.product_id == p.id
        )
    )
    data = schemas.ProductOut.model_validate(p)
    data.on_hand = int(on_hand or 0)
    return data


# ------------------------------ Products ---------------------------------- #
@router.get("/products", response_model=list[schemas.ProductOut])
def list_products(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return [_product_out(db, p) for p in db.query(models.Product).order_by(models.Product.name).all()]


@router.post("/products", response_model=schemas.ProductOut, status_code=201)
def create_product(
    payload: schemas.ProductCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    if db.query(models.Product).filter(models.Product.sku == payload.sku).first():
        raise HTTPException(status_code=409, detail="SKU already exists")
    product = models.Product(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return _product_out(db, product)


@router.put("/products/{product_id}", response_model=schemas.ProductOut)
def update_product(
    product_id: int,
    payload: schemas.ProductCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    product = db.get(models.Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    for field, value in payload.model_dump().items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return _product_out(db, product)


# ----------------------------- Warehouses --------------------------------- #
@router.get("/warehouses", response_model=list[schemas.WarehouseOut])
def list_warehouses(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return db.query(models.Warehouse).order_by(models.Warehouse.code).all()


@router.post("/warehouses", response_model=schemas.WarehouseOut, status_code=201)
def create_warehouse(
    payload: schemas.WarehouseBase,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    if db.query(models.Warehouse).filter(models.Warehouse.code == payload.code).first():
        raise HTTPException(status_code=409, detail="Warehouse code already exists")
    wh = models.Warehouse(**payload.model_dump())
    db.add(wh)
    db.commit()
    db.refresh(wh)
    return wh


# ---------------------------- Stock levels -------------------------------- #
@router.get("/stock", response_model=list[schemas.StockLevelOut])
def list_stock(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rows = db.query(models.StockLevel).all()
    out = []
    for r in rows:
        item = schemas.StockLevelOut.model_validate(r)
        item.product_name = r.product.name
        item.warehouse_name = r.warehouse.name
        out.append(item)
    return out


@router.post("/stock/adjust", response_model=schemas.StockLevelOut)
def adjust_stock(
    payload: schemas.StockAdjust,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    if not db.get(models.Product, payload.product_id):
        raise HTTPException(status_code=404, detail="Product not found")
    if not db.get(models.Warehouse, payload.warehouse_id):
        raise HTTPException(status_code=404, detail="Warehouse not found")
    level = ledger.apply_stock_movement(
        db,
        product_id=payload.product_id,
        warehouse_id=payload.warehouse_id,
        quantity=payload.quantity,
        movement_type="adjust",
        reference=payload.reference,
    )
    db.commit()
    db.refresh(level)
    item = schemas.StockLevelOut.model_validate(level)
    item.product_name = level.product.name
    item.warehouse_name = level.warehouse.name
    return item
