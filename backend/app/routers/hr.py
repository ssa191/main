"""HR: departments and employees."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/api", tags=["hr"])


@router.get("/departments", response_model=list[schemas.DepartmentOut])
def list_departments(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return db.query(models.Department).order_by(models.Department.name).all()


@router.post("/departments", response_model=schemas.DepartmentOut, status_code=201)
def create_department(
    name: str,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    if db.query(models.Department).filter(models.Department.name == name).first():
        raise HTTPException(status_code=409, detail="Department already exists")
    dept = models.Department(name=name)
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return dept


def _employee_out(emp: models.Employee) -> schemas.EmployeeOut:
    out = schemas.EmployeeOut.model_validate(emp)
    out.department_name = emp.department.name if emp.department else None
    return out


@router.get("/employees", response_model=list[schemas.EmployeeOut])
def list_employees(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    return [_employee_out(e) for e in db.query(models.Employee).order_by(models.Employee.full_name).all()]


@router.post("/employees", response_model=schemas.EmployeeOut, status_code=201)
def create_employee(
    payload: schemas.EmployeeBase,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    if payload.department_id and not db.get(models.Department, payload.department_id):
        raise HTTPException(status_code=404, detail="Department not found")
    data = payload.model_dump()
    data["hire_date"] = data.get("hire_date") or date.today()
    emp = models.Employee(**data)
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return _employee_out(emp)


@router.put("/employees/{employee_id}", response_model=schemas.EmployeeOut)
def update_employee(
    employee_id: int,
    payload: schemas.EmployeeBase,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    emp = db.get(models.Employee, employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    data = payload.model_dump()
    if data.get("hire_date") is None:
        data["hire_date"] = emp.hire_date
    for field, value in data.items():
        setattr(emp, field, value)
    db.commit()
    db.refresh(emp)
    return _employee_out(emp)
