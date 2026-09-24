from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_admin
from ..models.crm import (
    OpportunityCloudOperator,
    OpportunitySegment,
    OpportunityStatus,
    OpportunityUpdateTag,
)
from ..models.user import User
from ..services.settings import get_setting, set_setting

router = APIRouter(prefix="/api/config", tags=["config"])

# ------------------------------------------------------------------ lookup schemas
class StatusIn(BaseModel):
    name: str
    color: str = "#8a8f98"


class SegmentIn(BaseModel):
    name: str
    credit_percentage: float | None = None
    credit_on_arr: bool = False
    credit_percentage_customer: float | None = None
    credit_percentage_ambifo: float | None = None
    credit_basis_mrr: bool = True
    credit_basis_arr: bool = False


class CloudOperatorIn(BaseModel):
    name: str


class UpdateTagIn(BaseModel):
    name: str
    color: str = "#6b7280"


# ------------------------------------------------------------------ status
@router.get("/statuses")
def list_statuses(
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    return db.query(OpportunityStatus).order_by(OpportunityStatus.name).all()


@router.post("/statuses", status_code=status.HTTP_201_CREATED)
def create_status(
    payload: StatusIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    if db.query(OpportunityStatus).filter(OpportunityStatus.name == payload.name).first():
        raise HTTPException(status_code=409, detail="Status already exists")
    row = OpportunityStatus(name=payload.name, color=payload.color or "#8a8f98")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/statuses/{status_id}")
def update_status(
    status_id: int,
    payload: StatusIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    row = db.get(OpportunityStatus, status_id)
    if not row:
        raise HTTPException(status_code=404, detail="Status not found")
    row.name = payload.name
    row.color = payload.color or row.color
    db.commit()
    db.refresh(row)
    return row


@router.delete("/statuses/{status_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_status(
    status_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    row = db.get(OpportunityStatus, status_id)
    if not row:
        raise HTTPException(status_code=404, detail="Status not found")
    row.is_active = False
    db.commit()


# ------------------------------------------------------------------ segment
@router.get("/segments")
def list_segments(
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    return db.query(OpportunitySegment).order_by(OpportunitySegment.name).all()


@router.post("/segments", status_code=status.HTTP_201_CREATED)
def create_segment(
    payload: SegmentIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    if db.query(OpportunitySegment).filter(OpportunitySegment.name == payload.name).first():
        raise HTTPException(status_code=409, detail="Segment already exists")
    row = OpportunitySegment(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/segments/{segment_id}")
def update_segment(
    segment_id: int,
    payload: SegmentIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    row = db.get(OpportunitySegment, segment_id)
    if not row:
        raise HTTPException(status_code=404, detail="Segment not found")
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/segments/{segment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_segment(
    segment_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    row = db.get(OpportunitySegment, segment_id)
    if not row:
        raise HTTPException(status_code=404, detail="Segment not found")
    row.is_active = False
    db.commit()


# ------------------------------------------------------------------ cloud operators
@router.get("/cloud-operators")
def list_cloud_operators(
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    return db.query(OpportunityCloudOperator).order_by(OpportunityCloudOperator.name).all()


@router.post("/cloud-operators", status_code=status.HTTP_201_CREATED)
def create_cloud_operator(
    payload: CloudOperatorIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    if db.query(OpportunityCloudOperator).filter(OpportunityCloudOperator.name == payload.name).first():
        raise HTTPException(status_code=409, detail="Cloud operator already exists")
    row = OpportunityCloudOperator(name=payload.name)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/cloud-operators/{op_id}")
def update_cloud_operator(
    op_id: int,
    payload: CloudOperatorIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    row = db.get(OpportunityCloudOperator, op_id)
    if not row:
        raise HTTPException(status_code=404, detail="Cloud operator not found")
    row.name = payload.name
    db.commit()
    db.refresh(row)
    return row


@router.delete("/cloud-operators/{op_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cloud_operator(
    op_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    row = db.get(OpportunityCloudOperator, op_id)
    if not row:
        raise HTTPException(status_code=404, detail="Cloud operator not found")
    row.is_active = False
    db.commit()


# ------------------------------------------------------------------ update tags
@router.get("/update-tags")
def list_update_tags(
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    return db.query(OpportunityUpdateTag).order_by(OpportunityUpdateTag.name).all()


@router.post("/update-tags", status_code=status.HTTP_201_CREATED)
def create_update_tag(
    payload: UpdateTagIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    if db.query(OpportunityUpdateTag).filter(OpportunityUpdateTag.name == payload.name).first():
        raise HTTPException(status_code=409, detail="Update tag already exists")
    row = OpportunityUpdateTag(name=payload.name, color=payload.color or "#6b7280")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/update-tags/{tag_id}")
def update_update_tag(
    tag_id: int,
    payload: UpdateTagIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    row = db.get(OpportunityUpdateTag, tag_id)
    if not row:
        raise HTTPException(status_code=404, detail="Update tag not found")
    row.name = payload.name
    row.color = payload.color or row.color
    db.commit()
    db.refresh(row)
    return row


@router.delete("/update-tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_update_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    row = db.get(OpportunityUpdateTag, tag_id)
    if not row:
        raise HTTPException(status_code=404, detail="Update tag not found")
    row.is_active = False
    db.commit()


# --- Teams ---
@router.get("/teams")
def get_teams_config(
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    return {
        "webhook_url": get_setting(db, "teams.webhook_url", ""),
        "enabled": get_setting(db, "teams.enabled", "true").lower() in ("true", "1", "yes"),
    }


@router.put("/teams")
def update_teams_config(
    payload: dict,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    for key, value in (payload or {}).items():
        set_setting(db, f"teams.{key}", value)
    return get_teams_config(db)


# --- Document / Media storage ---
@router.get("/storage")
def get_storage_config(
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    return {
        "backend": get_setting(db, "storage.backend", "local"),
        "docs_dir": get_setting(db, "storage.docs_dir", "storage/documents"),
        "max_upload_mb": int(get_setting(db, "storage.max_upload_mb", "100")),
        "onedrive_folder_link": get_setting(db, "storage.onedrive_folder_link", ""),
    }


@router.put("/storage")
def update_storage_config(
    payload: dict,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    for key, value in (payload or {}).items():
        set_setting(db, f"storage.{key}", value)
    return get_storage_config(db)


# --- Application URL ---
@router.get("/app-url")
def get_app_url_config(
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    return {
        "base_url": get_setting(db, "app.base_url", "http://127.0.0.1:8000"),
    }


@router.put("/app-url")
def update_app_url_config(
    payload: dict,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    data = dict(payload or {})
    if "base_url" in data and data["base_url"]:
        set_setting(db, "app.base_url", data["base_url"])
    return get_app_url_config(db)


# --- AI settings ---
@router.get("/ai")
def get_ai_config(
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    return {
        "provider": get_setting(db, "ai.provider", "openai"),
        "model": get_setting(db, "ai.model", ""),
        "api_key_set": bool(get_setting(db, "ai.api_key", "")),
        "max_tokens": int(get_setting(db, "ai.max_tokens", "2048")),
    }


@router.put("/ai")
def update_ai_config(
    payload: dict,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    data = dict(payload or {})
    if "api_key" in data and (data["api_key"] is None or data["api_key"] == ""):
        # empty means "don't change"; only set when provided
        data.pop("api_key", None)
    for key, value in data.items():
        if value is None:
            continue
        set_setting(db, f"ai.{key}", value)
    return get_ai_config(db)


# --- Meeting availability (global defaults) ---
@router.get("/meeting-availability")
def get_meeting_availability_config(
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    return {
        "default_duration_min": int(get_setting(db, "meeting.duration_min", "30")),
        "default_expiry_days": int(get_setting(db, "meeting.expiry_days", "7")),
    }


@router.put("/meeting-availability")
def update_meeting_availability_config(
    payload: dict,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    for key, value in (payload or {}).items():
        if value is None:
            continue
        set_setting(db, f"meeting.{key}", value)
    return get_meeting_availability_config(db)


# --- DocuSign e-Signature ---
@router.get("/docusign")
def get_docusign_config(
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    return {
        "integration_key": get_setting(db, "docusign.integration_key", ""),
        "account_id": get_setting(db, "docusign.account_id", ""),
        "base_url": get_setting(db, "docusign.base_url", "https://demo.docusign.net"),
        "private_key_set": bool(get_setting(db, "docusign.private_key", "")),
        "enabled": get_setting(db, "docusign.enabled", "false").lower() in ("true", "1", "yes"),
    }


@router.put("/docusign")
def update_docusign_config(
    payload: dict,
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    data = dict(payload or {})
    if "private_key" in data and (data["private_key"] is None or data["private_key"] == ""):
        data.pop("private_key", None)
    for key, value in data.items():
        if value is None:
            continue
        set_setting(db, f"docusign.{key}", value)
    return get_docusign_config(db)


# --- Restart application ---
@router.post("/restart", status_code=status.HTTP_200_OK)
def restart_application(
    db: Session = Depends(get_db),
    _user: User = Depends(require_admin),
):
    # True self-restart without relying on an external supervisor: spawn a
    # detached copy of the API process, then exit this one shortly after.
    import os
    import subprocess
    import sys
    import threading

    def _shutdown():
        import time
        time.sleep(0.3)
        try:
            args = [sys.executable, "run.py"]
            creationflags = 0
            if os.name == "nt":
                creationflags = (
                    subprocess.DETACHED_PROCESS
                    | subprocess.CREATE_NEW_PROCESS_GROUP
                )
            backend_dir = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            subprocess.Popen(
                args,
                cwd=backend_dir,
                creationflags=creationflags,
                close_fds=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
        except Exception:
            pass
        time.sleep(0.8)
        os._exit(0)

    threading.Thread(target=_shutdown, daemon=True).start()
    db.rollback()
    return {"status": "restarting", "started_at": datetime.now(timezone.utc).isoformat()}
