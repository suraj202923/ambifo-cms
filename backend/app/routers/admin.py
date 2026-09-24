from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_admin
from ..models.crm import Customer
from ..models.user import User
from ..schemas.auth import AdminUserCreate, AdminUserUpdate, UserOut
from ..security import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return db.query(User).order_by(User.username).all()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AdminUserCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        is_admin=payload.is_admin,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.email is not None:
        if db.query(User).filter(User.email == payload.email, User.id != user_id).first():
            raise HTTPException(status_code=409, detail="Email already registered")
        user.email = payload.email
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.new_password is not None:
        user.password_hash = hash_password(payload.new_password)
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.is_admin is not None:
        if not payload.is_admin and user.is_admin and user.id == admin.id:
            raise HTTPException(status_code=400, detail="Cannot remove your own admin role")
        user.is_admin = payload.is_admin
    if payload.is_active is False:
        if user.id == admin.id:
            raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
        if user.is_admin and user.is_active:
            active_admins = (
                db.query(func.count(User.id))
                .filter(User.is_admin == True, User.is_active == True)  # noqa: E712
                .scalar()
            )
            if active_admins <= 1:
                raise HTTPException(status_code=400, detail="Cannot deactivate the last active admin")
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    if user.is_admin and user.is_active:
        active_admins = (
            db.query(func.count(User.id))
            .filter(User.is_admin == True, User.is_active == True)  # noqa: E712
            .scalar()
        )
        if active_admins <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last active admin")
    db.query(Customer).filter(Customer.assign_to_user_id == user_id).update(
        {Customer.assign_to_user_id: None}
    )
    user.is_active = False
    db.commit()


@router.post("/users/reset-all-passwords", status_code=status.HTTP_200_OK)
def reset_all_passwords(
    payload: dict,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    new_password = (payload or {}).get("new_password")
    if not new_password or len(new_password) < 6:
        raise HTTPException(status_code=422, detail="new_password must be at least 6 characters")
    hashed = hash_password(new_password)
    active = db.query(User).filter(User.is_active == True)  # noqa: E712
    active.update({User.password_hash: hashed}, synchronize_session=False)
    db.commit()
    return {"updated": active.count(), "updated_at": datetime.now(timezone.utc).isoformat()}