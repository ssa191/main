"""Accounting / Finance: chart of accounts, journal entries, trial balance."""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user
from ..services import ledger

router = APIRouter(prefix="/api", tags=["accounting"])


# --------------------------- Chart of accounts ---------------------------- #
@router.get("/accounts", response_model=list[schemas.AccountOut])
def list_accounts(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    accounts = db.query(models.Account).order_by(models.Account.code).all()
    out = []
    for a in accounts:
        item = schemas.AccountOut.model_validate(a)
        item.balance = ledger.account_balance(db, a)
        out.append(item)
    return out


@router.post("/accounts", response_model=schemas.AccountOut, status_code=201)
def create_account(
    payload: schemas.AccountBase,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    if payload.type not in ("asset", "liability", "equity", "income", "expense"):
        raise HTTPException(status_code=400, detail="Invalid account type")
    if db.query(models.Account).filter(models.Account.code == payload.code).first():
        raise HTTPException(status_code=409, detail="Account code already exists")
    account = models.Account(**payload.model_dump())
    db.add(account)
    db.commit()
    db.refresh(account)
    item = schemas.AccountOut.model_validate(account)
    item.balance = Decimal(0)
    return item


# ----------------------------- Journal ------------------------------------ #
def _entry_out(entry: models.JournalEntry) -> schemas.JournalEntryOut:
    out = schemas.JournalEntryOut.model_validate(entry)
    out.lines = []
    for line in entry.lines:
        lo = schemas.JournalLineOut.model_validate(line)
        lo.account_name = line.account.name if line.account else None
        out.lines.append(lo)
    return out


@router.get("/journal", response_model=list[schemas.JournalEntryOut])
def list_journal(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    entries = db.query(models.JournalEntry).order_by(models.JournalEntry.id.desc()).all()
    return [_entry_out(e) for e in entries]


@router.post("/journal", response_model=schemas.JournalEntryOut, status_code=201)
def create_journal_entry(
    payload: schemas.JournalEntryCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    if len(payload.lines) < 2:
        raise HTTPException(status_code=400, detail="A journal entry needs at least two lines")
    total_debit = sum((Decimal(l.debit) for l in payload.lines), Decimal(0))
    total_credit = sum((Decimal(l.credit) for l in payload.lines), Decimal(0))
    if total_debit != total_credit:
        raise HTTPException(
            status_code=400,
            detail=f"Entry does not balance: debits {total_debit} vs credits {total_credit}",
        )
    for l in payload.lines:
        if not db.get(models.Account, l.account_id):
            raise HTTPException(status_code=404, detail=f"Account {l.account_id} not found")

    entry = models.JournalEntry(
        entry_date=payload.entry_date or date.today(),
        memo=payload.memo,
        source="manual",
    )
    for l in payload.lines:
        entry.lines.append(
            models.JournalLine(account_id=l.account_id, debit=l.debit, credit=l.credit)
        )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _entry_out(entry)


@router.get("/trial-balance")
def trial_balance(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    """Return every account's debit/credit balance and confirm the books balance."""
    accounts = db.query(models.Account).order_by(models.Account.code).all()
    rows = []
    total_debit = Decimal(0)
    total_credit = Decimal(0)
    for a in accounts:
        bal = ledger.account_balance(db, a)
        debit = bal if a.type in ("asset", "expense") else Decimal(0)
        credit = bal if a.type not in ("asset", "expense") else Decimal(0)
        # Show negative normal balances on the opposite side for readability.
        if bal < 0:
            debit, credit = (Decimal(0), -bal) if a.type in ("asset", "expense") else (-bal, Decimal(0))
        if debit == 0 and credit == 0:
            continue
        rows.append(
            {"code": a.code, "name": a.name, "type": a.type,
             "debit": float(debit), "credit": float(credit)}
        )
        total_debit += debit
        total_credit += credit
    return {
        "rows": rows,
        "total_debit": float(total_debit),
        "total_credit": float(total_credit),
        "balanced": total_debit == total_credit,
    }
