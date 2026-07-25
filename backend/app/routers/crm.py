"""CRM: leads and a simple sales pipeline."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/api", tags=["crm"])

STAGES = ("new", "qualified", "proposal", "won", "lost")


@router.get("/leads", response_model=list[schemas.LeadOut])
def list_leads(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return db.query(models.Lead).order_by(models.Lead.id.desc()).all()


@router.post("/leads", response_model=schemas.LeadOut, status_code=201)
def create_lead(
    payload: schemas.LeadBase,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    if payload.stage not in STAGES:
        raise HTTPException(status_code=400, detail=f"Stage must be one of {STAGES}")
    lead = models.Lead(**payload.model_dump())
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


@router.put("/leads/{lead_id}", response_model=schemas.LeadOut)
def update_lead(
    lead_id: int,
    payload: schemas.LeadBase,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    lead = db.get(models.Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if payload.stage not in STAGES:
        raise HTTPException(status_code=400, detail=f"Stage must be one of {STAGES}")
    for field, value in payload.model_dump().items():
        setattr(lead, field, value)
    db.commit()
    db.refresh(lead)
    return lead
