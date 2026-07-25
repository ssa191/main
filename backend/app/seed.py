"""Seed the database with a realistic demo company on first run.

Idempotent: does nothing if users already exist. This gives anyone who starts
the app a populated, explorable ERP without manual data entry.
"""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from . import models
from .security import hash_password
from .services import ledger


def seed_if_empty(db: Session) -> None:
    if db.query(models.User).count() > 0:
        return

    # --- Users ------------------------------------------------------------- #
    db.add_all(
        [
            models.User(
                email="admin@acme.test",
                full_name="Alice Admin",
                role="admin",
                hashed_password=hash_password("admin123"),
            ),
            models.User(
                email="manager@acme.test",
                full_name="Mark Manager",
                role="manager",
                hashed_password=hash_password("manager123"),
            ),
        ]
    )

    # --- Chart of accounts ------------------------------------------------- #
    accounts = [
        ("1000", "Cash / Bank", "asset"),
        ("1100", "Accounts Receivable", "asset"),
        ("1200", "Inventory", "asset"),
        ("2000", "Accounts Payable", "liability"),
        ("3000", "Owner's Equity", "equity"),
        ("4000", "Sales Revenue", "income"),
        ("5000", "Cost of Goods Sold", "expense"),
        ("6000", "Operating Expenses", "expense"),
    ]
    db.add_all(models.Account(code=c, name=n, type=t) for c, n, t in accounts)

    # --- Warehouses -------------------------------------------------------- #
    wh_main = models.Warehouse(code="WH1", name="Main Warehouse", location="Riyadh")
    wh_east = models.Warehouse(code="WH2", name="East Depot", location="Dammam")
    db.add_all([wh_main, wh_east])

    # --- Departments ------------------------------------------------------- #
    dept_ops = models.Department(name="Operations")
    dept_sales = models.Department(name="Sales")
    dept_fin = models.Department(name="Finance")
    db.add_all([dept_ops, dept_sales, dept_fin])

    db.flush()  # assign ids

    # --- Products ---------------------------------------------------------- #
    products = [
        models.Product(sku="WID-100", name="Widget Standard", category="Widgets",
                       unit_price=Decimal("25.00"), cost_price=Decimal("12.00"), reorder_level=50),
        models.Product(sku="WID-200", name="Widget Pro", category="Widgets",
                       unit_price=Decimal("45.00"), cost_price=Decimal("22.00"), reorder_level=30),
        models.Product(sku="GDG-300", name="Gadget Mini", category="Gadgets",
                       unit_price=Decimal("15.00"), cost_price=Decimal("7.50"), reorder_level=80),
        models.Product(sku="GDG-400", name="Gadget Max", category="Gadgets",
                       unit_price=Decimal("90.00"), cost_price=Decimal("48.00"), reorder_level=20),
        models.Product(sku="ACC-500", name="Cable Pack", category="Accessories",
                       unit_price=Decimal("8.00"), cost_price=Decimal("3.00"), reorder_level=100),
    ]
    db.add_all(products)
    db.flush()

    # --- Opening stock (as receipts) --------------------------------------- #
    opening = {"WID-100": 120, "WID-200": 25, "GDG-300": 200, "GDG-400": 60, "ACC-500": 40}
    for p in products:
        ledger.apply_stock_movement(
            db, product_id=p.id, warehouse_id=wh_main.id,
            quantity=opening[p.sku], movement_type="receipt", reference="opening balance",
        )

    # --- Customers & Suppliers -------------------------------------------- #
    customers = [
        models.Customer(name="Globex Corp", email="orders@globex.test", phone="+966 11 111 1111"),
        models.Customer(name="Initech Ltd", email="buy@initech.test", phone="+966 11 222 2222"),
        models.Customer(name="Umbrella Retail", email="po@umbrella.test", phone="+966 11 333 3333"),
    ]
    suppliers = [
        models.Supplier(name="Stark Supplies", email="sales@stark.test", phone="+966 13 444 4444"),
        models.Supplier(name="Wayne Materials", email="sales@wayne.test", phone="+966 13 555 5555"),
    ]
    db.add_all(customers + suppliers)

    # --- Employees --------------------------------------------------------- #
    db.add_all(
        [
            models.Employee(full_name="Sara Ops", email="sara@acme.test", position="Warehouse Lead",
                            department_id=dept_ops.id, salary=Decimal("8000"),
                            hire_date=date.today() - timedelta(days=400)),
            models.Employee(full_name="Omar Sales", email="omar@acme.test", position="Account Executive",
                            department_id=dept_sales.id, salary=Decimal("9500"),
                            hire_date=date.today() - timedelta(days=250)),
            models.Employee(full_name="Lena Finance", email="lena@acme.test", position="Accountant",
                            department_id=dept_fin.id, salary=Decimal("11000"),
                            hire_date=date.today() - timedelta(days=120)),
        ]
    )

    # --- CRM leads --------------------------------------------------------- #
    db.add_all(
        [
            models.Lead(name="Enterprise rollout", company="Hooli", contact_email="cto@hooli.test",
                        stage="qualified", estimated_value=Decimal("45000"), owner="Omar Sales"),
            models.Lead(name="Reseller agreement", company="Pied Piper", contact_email="ceo@pp.test",
                        stage="proposal", estimated_value=Decimal("30000"), owner="Omar Sales"),
            models.Lead(name="Trial order", company="Vandelay", contact_email="art@vandelay.test",
                        stage="new", estimated_value=Decimal("5000"), owner="Omar Sales"),
        ]
    )

    db.flush()

    # --- A sample confirmed sales order (exercises the full flow) ---------- #
    so = models.SalesOrder(
        number="SO-00001", customer_id=customers[0].id, warehouse_id=wh_main.id,
        order_date=date.today() - timedelta(days=3),
    )
    so.lines = [
        models.SalesOrderLine(product_id=products[0].id, quantity=10, unit_price=products[0].unit_price),
        models.SalesOrderLine(product_id=products[2].id, quantity=20, unit_price=products[2].unit_price),
    ]
    so.total = sum((Decimal(l.unit_price) * l.quantity for l in so.lines), Decimal(0))
    db.add(so)
    db.flush()
    ledger.confirm_sales_order(db, so)  # issues stock + posts revenue & COGS

    # --- A sample received purchase order ---------------------------------- #
    po = models.PurchaseOrder(
        number="PO-00001", supplier_id=suppliers[0].id, warehouse_id=wh_main.id,
        order_date=date.today() - timedelta(days=5),
    )
    po.lines = [
        models.PurchaseOrderLine(product_id=products[1].id, quantity=50, unit_price=products[1].cost_price),
    ]
    po.total = sum((Decimal(l.unit_price) * l.quantity for l in po.lines), Decimal(0))
    db.add(po)
    db.flush()
    ledger.receive_purchase_order(db, po)  # receives stock + posts payable

    db.commit()
