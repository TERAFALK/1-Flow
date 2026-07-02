from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..deps import get_current_user, require_admin
from ..auth import hash_password
from ..schemas import UserCreate, UserUpdate, UserOut
from .. import models

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=List[UserOut])
def list_users(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return db.query(models.User).order_by(models.User.full_name).all()


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    if db.query(models.User).filter(models.User.email == body.email).first():
        raise HTTPException(status_code=400, detail="E-postadressen används redan")
    user = models.User(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/me", response_model=UserOut)
def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user


@router.get("/{user_id}", response_model=UserOut)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Användare ej hittad")
    return user


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Användare ej hittad")
    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "password":
            if value:
                user.hashed_password = hash_password(value)
        else:
            setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Kan inte ta bort dig själv")
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Användare ej hittad")
    if db.query(models.TimeEntry).filter(models.TimeEntry.user_id == user_id).first():
        raise HTTPException(
            status_code=400,
            detail="Användaren har registrerad tid och kan inte tas bort – avaktivera kontot istället",
        )
    # Släpp alla nullbara referenser till användaren innan borttagning
    for model, col in (
        (models.WorkOrder, models.WorkOrder.assigned_to),
        (models.WorkOrder, models.WorkOrder.created_by),
        (models.StockTransaction, models.StockTransaction.user_id),
        (models.Task, models.Task.assigned_to),
        (models.Task, models.Task.created_by),
        (models.Activity, models.Activity.created_by),
        (models.WorkOrderFile, models.WorkOrderFile.uploaded_by),
        (models.PickList, models.PickList.created_by),
    ):
        db.query(model).filter(col == user_id).update({col: None}, synchronize_session=False)
    db.delete(user)
    db.commit()
