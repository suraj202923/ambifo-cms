from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models.crm import Customer
from ..models.documents import CustomerDiagram
from ..models.user import User
from ..schemas.engine import DiagramGenerateIn, DiagramOut, DiagramSaveIn, DiagramUpdateIn
from ..services.engine_client import engine_client

router = APIRouter(prefix="/api/diagrams", tags=["diagrams"])


def now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/generate", response_model=DiagramOut, status_code=status.HTTP_201_CREATED)
def generate_diagram(
    payload: DiagramGenerateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not db.get(Customer, payload.customer_id):
        raise HTTPException(status_code=404, detail="Customer not found")

    request_body = {
        "title": payload.title,
        "entities": payload.entities,
        "ai_generated": payload.ai_generated,
    }
    try:
        result = engine_client.generate_diagram(request_body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Engine diagram generation failed: {exc}") from exc

    diagram = CustomerDiagram(
        customer_id=payload.customer_id,
        diagram_name=payload.diagram_name,
        macro_key=payload.macro_key,
        diagram_content=result.get("mermaid", ""),
        aws_calculator_link=payload.aws_calculator_link,
        is_active=True,
        created_by=current_user.username,
    )
    db.add(diagram)
    db.commit()
    db.refresh(diagram)
    return diagram


@router.post("/save", response_model=DiagramOut, status_code=status.HTTP_201_CREATED)
def save_diagram(
    payload: DiagramSaveIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not db.get(Customer, payload.customer_id):
        raise HTTPException(status_code=404, detail="Customer not found")

    diagram = CustomerDiagram(
        customer_id=payload.customer_id,
        diagram_name=payload.diagram_name,
        macro_key=payload.macro_key,
        diagram_content=payload.diagram_content,
        aws_calculator_link=payload.aws_calculator_link,
        is_active=True,
        created_by=current_user.username,
    )
    db.add(diagram)
    db.commit()
    db.refresh(diagram)
    return diagram


@router.put("/{diagram_id}", response_model=DiagramOut)
def update_diagram(
    diagram_id: int,
    payload: DiagramUpdateIn,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    diagram = db.get(CustomerDiagram, diagram_id)
    if not diagram:
        raise HTTPException(status_code=404, detail="Diagram not found")
    if payload.diagram_name is not None:
        diagram.diagram_name = payload.diagram_name
    if payload.diagram_content is not None:
        diagram.diagram_content = payload.diagram_content
    if payload.aws_calculator_link is not None:
        diagram.aws_calculator_link = payload.aws_calculator_link
    if payload.is_active is not None:
        diagram.is_active = payload.is_active
    db.commit()
    db.refresh(diagram)
    return diagram


@router.get("", response_model=list[DiagramOut])
def list_diagrams(
    customer_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = db.query(CustomerDiagram)
    if customer_id:
        q = q.filter(CustomerDiagram.customer_id == customer_id)
    return q.order_by(CustomerDiagram.updated_at.desc()).limit(100).all()


@router.get("/{diagram_id}", response_model=DiagramOut)
def get_diagram(
    diagram_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    diagram = db.get(CustomerDiagram, diagram_id)
    if not diagram:
        raise HTTPException(status_code=404, detail="Diagram not found")
    return diagram


@router.delete("/{diagram_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_diagram(
    diagram_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    diagram = db.get(CustomerDiagram, diagram_id)
    if not diagram:
        raise HTTPException(status_code=404, detail="Diagram not found")
    db.delete(diagram)
    db.commit()