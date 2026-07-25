# Acme ERP

A working, modular **Enterprise Resource Planning (ERP)** system — a single
application that unifies a company's core operations (inventory, sales,
purchasing, accounting, HR, and CRM) on one shared database, so that a business
event in one module automatically flows through to the others.

This is a genuine, runnable full‑stack app with a REST API, a web UI, seed data,
and real double‑entry accounting — not a mock‑up. It is deliberately compact so
the whole thing is readable end‑to‑end, and it's architected so new modules slot
in by copying the existing pattern.

---

## Quick start

```bash
cd backend
./run.sh
```

Then open <http://127.0.0.1:8000> and sign in with a demo account:

| Email               | Password     | Role    |
| ------------------- | ------------ | ------- |
| `admin@acme.test`   | `admin123`   | admin   |
| `manager@acme.test` | `manager123` | manager |

On first launch the database is created and seeded with a realistic company
(products, warehouses, customers, suppliers, employees, leads, plus one
confirmed sales order and one received purchase order). Interactive API docs are
at <http://127.0.0.1:8000/docs>.

> Prefer to run it by hand? `python3 -m venv .venv && source .venv/bin/activate
> && pip install -r requirements.txt && uvicorn app.main:app --reload`

---

## What an ERP actually is (and why this design)

An ERP's defining feature isn't the list of modules — it's that they share **one
source of truth** and **one set of business rules**, so data entered once is
reused everywhere and cross‑module effects happen automatically. The classic
example, which this project implements literally:

> Confirming a **sales order** must simultaneously (a) reduce **inventory** and
> (b) post **revenue** and **cost of goods sold** to the **general ledger** — in
> one atomic transaction, so operations and finance can never disagree.

That is the heart of the system and it lives in one place:
[`backend/app/services/ledger.py`](backend/app/services/ledger.py).

### Why this stack

I chose **Python + FastAPI + SQLAlchemy + SQLite** with a framework‑free
JavaScript frontend, over the alternatives, for concrete reasons:

- **Runs with one command, no build step.** The frontend is plain HTML/CSS/JS
  served by the API, so there's no Node toolchain, bundler, or `npm install`.
- **Real REST API.** The backend exposes a clean JSON API (auto‑documented at
  `/docs`) that any client — this UI, a React app, a mobile app, or another
  service — can consume. Swapping the UI for React later changes nothing on the
  server.
- **No database server required.** SQLite is a file; production can switch to
  PostgreSQL by changing one environment variable (`DATABASE_URL`), because all
  data access goes through SQLAlchemy.
- **Small and legible.** The entire schema is one file; each module is one
  router. You can read the whole system in an afternoon.

Django would have given a faster admin UI but couples you to its conventions;
a Node/React SPA is more "modern" but needs a build pipeline that gets in the
way of *understanding* the system. For a foundation you can run, read, and
extend, this is the pragmatic pick.

---

## Architecture

```
Browser (SPA)  ──HTTP/JSON──►  FastAPI routers  ──►  Service layer  ──►  SQLAlchemy models  ──►  SQLite/Postgres
static/app.js                  app/routers/*.py      app/services/         app/models.py
```

- **Routers** (`app/routers/`) — one file per module. They validate input, call
  the service/ORM layer, and shape responses. Thin by design.
- **Service layer** (`app/services/ledger.py`) — the cross‑module business logic
  that keeps inventory and accounting in lock‑step. This is what makes it an ERP
  rather than a set of independent CRUD tables.
- **Models** (`app/models.py`) — the entire database schema in one file, using
  the header/line document pattern for orders and journal entries. Money is
  stored as `Numeric(14,2)` to avoid floating‑point rounding errors.
- **Schemas** (`app/schemas.py`) — Pydantic request/response contracts, kept
  separate from the ORM so the wire format and storage can evolve independently.
- **Auth** (`app/security.py`, `app/deps.py`) — JWT bearer tokens; passwords
  hashed with PBKDF2 (standard library, nothing to compile). Role‑based access
  (`admin` / `manager` / `staff`) is enforced with a dependency.

### Project layout

```
backend/
├── requirements.txt
├── run.sh                     # one-command launcher
├── static/                    # the web UI (served by FastAPI)
│   ├── index.html
│   ├── styles.css
│   └── app.js                 # SPA: router, views, API client
└── app/
    ├── main.py                # app wiring; creates schema + seeds on startup
    ├── config.py              # env-driven settings (secret, DB URL, branding)
    ├── database.py            # engine, session, Base
    ├── security.py            # password hashing + JWT
    ├── deps.py                # auth / role dependencies
    ├── models.py              # ← the entire schema
    ├── schemas.py             # Pydantic API contracts
    ├── seed.py                # demo company seed data
    ├── services/
    │   └── ledger.py          # ← inventory + double-entry posting (the core)
    └── routers/
        ├── auth.py            # login, users
        ├── dashboard.py       # cross-module KPIs
        ├── inventory.py       # products, warehouses, stock
        ├── sales.py           # customers, sales orders
        ├── purchasing.py      # suppliers, purchase orders
        ├── accounting.py      # chart of accounts, journal, trial balance
        ├── hr.py              # departments, employees
        └── crm.py             # leads / pipeline
```

---

## Modules

| Module | What it does | Key business action |
| ------ | ------------ | ------------------- |
| **Inventory & Products** | Product catalog, warehouses, on‑hand stock levels, an append‑only movement log | Stock adjustments write a `StockMovement` and update the materialized balance |
| **Sales & Orders** | Customers, sales orders with line items | **Confirm** → issues stock + posts revenue & COGS |
| **Purchasing** | Suppliers, purchase orders | **Receive** → increases stock + posts a payable |
| **Accounting** | Chart of accounts, journal entries, **trial balance** | Every posting is balanced double‑entry; manual entries are validated to balance |
| **HR** | Departments, employees, salaries | CRUD with department roll‑up |
| **CRM** | Leads and a `new → qualified → proposal → won/lost` pipeline | Pipeline value feeds the dashboard |
| **Core** | Auth, users/roles, and a dashboard that aggregates KPIs from every module | — |

### The integration in detail

When you confirm sales order `SO‑00002` for 5 units at \$25 (cost \$12):

1. **Inventory:** a `StockMovement` of `‑5` is recorded and the product's on‑hand
   balance drops by 5.
2. **Ledger (revenue):** debit *Cash* \$125, credit *Sales Revenue* \$125.
3. **Ledger (COGS):** debit *Cost of Goods Sold* \$60, credit *Inventory* \$60.

All in one database transaction. Because every ledger posting is balanced, the
**trial balance always balances** — the app exposes `/api/trial-balance` and the
Accounting screen shows a live "Balanced ✓" indicator proving it. Receiving a
purchase order works symmetrically: stock up, *Inventory* debited, *Accounts
Payable* credited.

This is exactly what distinguishes an ERP from a collection of apps: you enter
the sale once and finance, operations, and reporting all update consistently.

---

## API reference (selected)

All endpoints are under `/api` and require a bearer token except `/api/auth/login`.

```
POST /api/auth/login                 → { access_token, user }
GET  /api/dashboard                  → cross-module KPIs

GET/POST     /api/products           GET/POST /api/warehouses
POST         /api/stock/adjust       GET      /api/stock

GET/POST     /api/customers          GET/POST /api/sales-orders
POST         /api/sales-orders/{id}/confirm | /cancel

GET/POST     /api/suppliers          GET/POST /api/purchase-orders
POST         /api/purchase-orders/{id}/receive | /cancel

GET/POST     /api/accounts           GET/POST /api/journal
GET          /api/trial-balance

GET/POST/PUT /api/employees          GET/POST /api/departments
GET/POST/PUT /api/leads
```

Full, interactive documentation is generated automatically at `/docs`.

---

## How to extend it (add a new module)

The codebase is a template. To add, say, a **Projects** module:

1. **Model** — add a `Project` class to `app/models.py`.
2. **Schema** — add `ProjectCreate` / `ProjectOut` to `app/schemas.py`.
3. **Router** — copy `app/routers/crm.py` to `projects.py` and adjust.
4. **Wire it up** — add the router to the tuple in `app/main.py`.
5. **UI** — add a `Views.projects` function and a nav entry in `static/app.js`.

If the new module has financial impact, post to the ledger through
`services/ledger.py` so accounting stays consistent — never write journal lines
ad‑hoc from a router.

---

## Production notes

This is a solid foundation, not a hardened product. Before real use you'd want:

- **Set `SECRET_KEY`** (env var) to a strong random value and use HTTPS.
- **Switch to PostgreSQL** by setting `DATABASE_URL`, and add
  [Alembic](https://alembic.sqlalchemy.org/) migrations instead of
  `create_all()`.
- **Wrap multi‑step postings in explicit transactions** and add row‑level locking
  for concurrent stock updates.
- **Finer‑grained permissions**, audit logging, pagination on list endpoints,
  and reversing entries for cancellations of already‑posted documents.
- **Tests** — the service layer is the highest‑value place to start.

---

## Configuration

Environment variables (or a `backend/.env` file):

| Variable          | Default                        | Purpose                          |
| ----------------- | ------------------------------ | -------------------------------- |
| `SECRET_KEY`      | `dev-secret-change-me...`      | JWT signing key                  |
| `DATABASE_URL`    | `sqlite:///./erp.db`           | e.g. `postgresql+psycopg://...`  |
| `COMPANY_NAME`    | `Acme Industries`              | Branding                         |
| `APP_NAME`        | `Acme ERP`                     | Branding                         |
