"""Pydantic schemas — the API's public request/response contracts.

Kept separate from ORM models so the wire format can evolve independently of
the database schema.
"""
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

ORM = ConfigDict(from_attributes=True)


# ------------------------------- Auth ------------------------------------- #
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ORM
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str = Field(min_length=6)
    role: str = "staff"


# ----------------------------- Inventory ---------------------------------- #
class ProductBase(BaseModel):
    sku: str
    name: str
    category: str = "General"
    description: str = ""
    unit_price: Decimal = Decimal(0)
    cost_price: Decimal = Decimal(0)
    reorder_level: int = 0
    is_active: bool = True


class ProductCreate(ProductBase):
    pass


class ProductOut(ProductBase):
    model_config = ORM
    id: int
    on_hand: int = 0  # computed across warehouses


class WarehouseBase(BaseModel):
    code: str
    name: str
    location: str = ""


class WarehouseOut(WarehouseBase):
    model_config = ORM
    id: int


class StockLevelOut(BaseModel):
    model_config = ORM
    product_id: int
    warehouse_id: int
    quantity: int
    product_name: str | None = None
    warehouse_name: str | None = None


class StockAdjust(BaseModel):
    product_id: int
    warehouse_id: int
    quantity: int  # signed delta
    reference: str = "manual adjustment"


# ------------------------------- Sales ------------------------------------ #
class CustomerBase(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    billing_address: str = ""


class CustomerOut(CustomerBase):
    model_config = ORM
    id: int


class OrderLineIn(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)
    unit_price: Decimal | None = None  # defaults to product price if omitted


class OrderLineOut(BaseModel):
    model_config = ORM
    id: int
    product_id: int
    product_name: str | None = None
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class SalesOrderCreate(BaseModel):
    customer_id: int
    warehouse_id: int
    order_date: date | None = None
    lines: list[OrderLineIn]


class SalesOrderOut(BaseModel):
    model_config = ORM
    id: int
    number: str
    customer_id: int
    customer_name: str | None = None
    warehouse_id: int
    order_date: date
    status: str
    total: Decimal
    lines: list[OrderLineOut] = []


# ----------------------------- Purchasing --------------------------------- #
class SupplierBase(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    address: str = ""


class SupplierOut(SupplierBase):
    model_config = ORM
    id: int


class PurchaseOrderCreate(BaseModel):
    supplier_id: int
    warehouse_id: int
    order_date: date | None = None
    lines: list[OrderLineIn]


class PurchaseOrderOut(BaseModel):
    model_config = ORM
    id: int
    number: str
    supplier_id: int
    supplier_name: str | None = None
    warehouse_id: int
    order_date: date
    status: str
    total: Decimal
    lines: list[OrderLineOut] = []


# ----------------------------- Accounting --------------------------------- #
class AccountBase(BaseModel):
    code: str
    name: str
    type: str


class AccountOut(AccountBase):
    model_config = ORM
    id: int
    balance: Decimal = Decimal(0)


class JournalLineIn(BaseModel):
    account_id: int
    debit: Decimal = Decimal(0)
    credit: Decimal = Decimal(0)


class JournalLineOut(BaseModel):
    model_config = ORM
    account_id: int
    account_name: str | None = None
    debit: Decimal
    credit: Decimal


class JournalEntryCreate(BaseModel):
    entry_date: date | None = None
    memo: str = ""
    lines: list[JournalLineIn]


class JournalEntryOut(BaseModel):
    model_config = ORM
    id: int
    entry_date: date
    memo: str
    source: str
    lines: list[JournalLineOut] = []


# -------------------------------- HR -------------------------------------- #
class DepartmentOut(BaseModel):
    model_config = ORM
    id: int
    name: str


class EmployeeBase(BaseModel):
    full_name: str
    email: str = ""
    position: str = ""
    department_id: int | None = None
    salary: Decimal = Decimal(0)
    hire_date: date | None = None
    is_active: bool = True


class EmployeeOut(EmployeeBase):
    model_config = ORM
    id: int
    department_name: str | None = None


# -------------------------------- CRM ------------------------------------- #
class LeadBase(BaseModel):
    name: str
    company: str = ""
    contact_email: str = ""
    stage: str = "new"
    estimated_value: Decimal = Decimal(0)
    owner: str = ""


class LeadOut(LeadBase):
    model_config = ORM
    id: int


# ----------------------------- Dashboard ---------------------------------- #
class DashboardStats(BaseModel):
    products: int
    low_stock: int
    customers: int
    suppliers: int
    open_sales_orders: int
    open_purchase_orders: int
    employees: int
    open_leads: int
    revenue: Decimal
    purchases: Decimal
    pipeline_value: Decimal
    inventory_value: Decimal


Token.model_rebuild()
