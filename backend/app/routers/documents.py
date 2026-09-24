import asyncio
import csv as _csv
import os
import uuid
from datetime import datetime, timezone
from io import BytesIO

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models.crm import Customer, OpportunityHistory
from ..models.documents import CustomerDocument, CustomerSOW
from ..models.user import User
from ..schemas.engine import CustomerDocumentOut, SowGenerateIn, SowOut
from ..services.engine_client import engine_client
from ..services.settings import get_setting

router = APIRouter(prefix="/api/documents", tags=["documents"])

DOC_STORAGE_DIR = "storage/documents"


def now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_storage_dir() -> str:
    path = os.path.abspath(DOC_STORAGE_DIR)
    os.makedirs(path, exist_ok=True)
    return path


@router.post("/sow/generate", response_model=SowOut, status_code=status.HTTP_201_CREATED)
def generate_sow(
    payload: SowGenerateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer = db.get(Customer, payload.customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    sow_title = payload.sow_title or f"Statement of Work — {customer.customer_name}"
    sections = [
        {"title": s.title, "body": s.body}
        for s in payload.sections or []
    ]
    if payload.company:
        sections.append({"title": "Company", "body": payload.company})
    if not sections:
        sections = [
            {"title": "Overview", "body": f"Statement of Work for {customer.customer_name}."},
            {"title": "Scope of Work", "body": "Cloud consultation, migration and optimization services."},
            {"title": "Commercials", "body": f"Commercial terms as agreed with {customer.customer_name}."},
            {"title": "Signatures", "body": "Both parties accept the terms of this SOW."},
        ]

    request_body = {
        "company": payload.company or customer.account_name or customer.customer_name,
        "project_name": customer.customer_name,
        "sow_title": sow_title,
        "sections": sections,
    }
    try:
        doc = engine_client.generate_sow(request_body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Engine document generation failed: {exc}") from exc

    dirpath = ensure_storage_dir()
    safe_name = sow_title.replace(" ", "_").replace("/", "_").replace("\\", "_")[:120]
    filename = f"{customer.id}_{safe_name}_{uuid.uuid4().hex[:6]}.html"
    file_path = os.path.join(dirpath, filename)
    with open(file_path, "w", encoding="utf-8") as fh:
        fh.write(doc.get("content", ""))

    sow = CustomerSOW(
        customer_id=customer.id,
        sow_title=sow_title,
        version=_next_sow_version(db, customer.id),
        status="draft",
        content_html=doc.get("content", ""),
        created_by=current_user.username,
    )
    db.add(sow)
    db.flush()

    hist = OpportunityHistory()
    hist.customer_id = customer.id
    hist.action = "document"
    hist.changes_summary = f"SOW '{sow_title}' generated (v1.0)"
    hist.tag_name = "sow"
    hist.changed_by = current_user.username
    hist.created_at = now()
    db.add(hist)
    db.commit()
    db.refresh(sow)
    return sow


@router.get("/sows", response_model=list[SowOut])
def list_sows(
    customer_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = db.query(CustomerSOW)
    if customer_id:
        q = q.filter(CustomerSOW.customer_id == customer_id)
    return q.order_by(CustomerSOW.updated_at.desc()).limit(100).all()


@router.get("/sows/{sow_id}", response_model=SowOut)
def get_sow(
    sow_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    sow = db.get(CustomerSOW, sow_id)
    if not sow:
        raise HTTPException(status_code=404, detail="SOW not found")
    return sow


# ------------------------------------------------------------- general documents
@router.post("", response_model=CustomerDocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    customer_id: int = Query(...),
    description: str | None = Query(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not db.get(Customer, customer_id):
        raise HTTPException(status_code=404, detail="Customer not found")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Empty file")

    backend = get_setting(db, "storage.backend", "local")
    onedrive_link = get_setting(db, "storage.onedrive_folder_link", "")

    dirpath = ensure_storage_dir()
    prefix = uuid.uuid4().hex[:8]
    stored_name = f"{customer_id}_{prefix}_{file.filename or 'file'}"
    file_path = os.path.join(dirpath, stored_name)
    with open(file_path, "wb") as fh:
        fh.write(content)

    doc = CustomerDocument(
        customer_id=customer_id,
        original_filename=file.filename or "file",
        stored_filename=stored_name,
        file_path=file_path,
        storage_backend="onedrive" if backend == "onedrive" else "local",
        blob_url=onedrive_link if backend == "onedrive" else None,
        file_size_bytes=len(content),
        mime_type=file.content_type,
        description=description,
        uploaded_by=current_user.username,
        created_at=now(),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.get("", response_model=list[CustomerDocumentOut])
def list_documents(
    customer_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = db.query(CustomerDocument)
    if customer_id:
        q = q.filter(CustomerDocument.customer_id == customer_id)
    return q.order_by(CustomerDocument.created_at.desc()).limit(200).all()


@router.get("/{document_id}")
def download_document(
    document_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    doc = db.get(CustomerDocument, document_id)
    if not doc or not doc.file_path:
        raise HTTPException(status_code=404, detail="Document not found")
    if not os.path.exists(doc.file_path):
        raise HTTPException(status_code=404, detail="Document file missing on disk")
    return FileResponse(doc.file_path, filename=doc.original_filename, media_type=doc.mime_type or "application/octet-stream")


@router.delete("/sows/{sow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sow(
    sow_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    sow = db.get(CustomerSOW, sow_id)
    if not sow:
        raise HTTPException(status_code=404, detail="SOW not found")
    db.delete(sow)
    db.commit()


@router.get("/sows/{sow_id}/download")
def download_sow(
    sow_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    sow = db.get(CustomerSOW, sow_id)
    if not sow:
        raise HTTPException(status_code=404, detail="SOW not found")
    if not sow.content_html:
        raise HTTPException(status_code=404, detail="SOW content not available")
    filename = (sow.sow_title or "SOW").replace(" ", "_").replace("/", "_")[:80]
    return HTMLResponse(
        content=sow.content_html,
        headers={"Content-Disposition": f'attachment; filename="{filename}.html"'},
    )


@router.post("/sows/{sow_id}/send", status_code=status.HTTP_201_CREATED)
def send_sow_email(
    sow_id: int,
    recipient_email: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sow = db.get(CustomerSOW, sow_id)
    if not sow:
        raise HTTPException(status_code=404, detail="SOW not found")

    customer = db.get(Customer, sow.customer_id)
    to_email = recipient_email or (customer.email if customer else None)
    if not to_email:
        raise HTTPException(status_code=400, detail="No recipient email available")

    from ..routers.email import get_system_template, render_template
    from ..services.messaging import enqueue_email

    template = get_system_template(db, "System - SOW Document Email")
    if not template:
        raise HTTPException(status_code=500, detail="SOW email template not configured")

    ctx = {
        "customer_name": customer.customer_name if customer else "",
        "sow_title": sow.sow_title or "Statement of Work",
        "today": now().strftime("%B %d, %Y"),
    }
    enqueue_email(
        to_email,
        template.subject_template,
        template.body_template,
        context=ctx,
        email_type="sow",
        customer_id=sow.customer_id,
        template_id=template.id,
    )

    sow.status = "sent"
    db.commit()
    db.refresh(sow)
    return sow


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    doc = db.get(CustomerDocument, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.file_path and os.path.exists(doc.file_path):
        os.remove(doc.file_path)
    db.delete(doc)
    db.commit()


def _next_sow_version(db: Session, customer_id: int) -> str:
    """Increment SOW version for a customer (1.0 → 1.1 → 2.0, etc.)."""
    latest = (
        db.query(CustomerSOW)
        .filter(CustomerSOW.customer_id == customer_id)
        .order_by(CustomerSOW.id.desc())
        .first()
    )
    if not latest or not latest.version:
        return "1.0"
    try:
        major, minor = latest.version.split(".")
        return f"{major}.{int(minor) + 1}"
    except (ValueError, AttributeError):
        return "1.0"


def _col_index(header: list[str], *names: str) -> int | None:
    lowered = [(cell or "").strip().lower() for cell in header]

    def score(cell: str, name: str) -> int:
        if cell == name:
            return 3
        if cell.startswith(name):
            return 2
        if f" {name}" in cell:
            return 1
        return 0

    best_idx: int | None = None
    best_score = 0
    for idx, cell in enumerate(lowered):
        for name in names:
            current = score(cell, name)
            if current > best_score:
                best_idx, best_score = idx, current
    return best_idx


def _parse_aws_calc_csv(text: str) -> tuple[list[dict], str, str]:
    """Parse an AWS Pricing Calculator CSV export into (items, estimate_name, currency)."""
    reader = list(_csv.reader(text.splitlines(True)))
    estimate_name = "AWS Pricing Calculator Estimate"
    currency = "USD"

    if reader and reader[0] and "estimate" in (reader[0][0] or "").strip().lower():
        if len(reader[0]) > 1 and (reader[0][1] or "").strip():
            estimate_name = reader[0][1].strip()
        if len(reader[0]) > 3:
            currency_cell = (reader[0][3] or "").strip()
            if currency_cell.lower() != "currency":
                currency = currency_cell
            elif len(reader[0]) > 4 and (reader[0][4] or "").strip():
                currency = reader[0][4].strip()

    header_idx = None
    for i, row in enumerate(reader):
        cells = [(c or "").strip().lower() for c in row]
        if any("service" in c and "group" in c for c in cells):
            header_idx = i
            break
        if any(c == "service" for c in cells):
            header_idx = i
            break
    if header_idx is None:
        return [], estimate_name, currency

    header = reader[header_idx]
    g_idx = _col_index(header, "group")
    s_idx = _col_index(header, "service")
    r_idx = _col_index(header, "region")
    c_idx = _col_index(header, "configuration", "config", "description")
    m_idx = _col_index(header, "monthly")
    u_idx = _col_index(header, "upfront")

    def cell(row: list[str], idx: int | None) -> str:
        if idx is None or idx >= len(row):
            return ""
        return (row[idx] or "").strip()

    def num(value: str) -> float:
        try:
            return float(value.replace(",", "").replace("$", "").replace(" ", ""))
        except (TypeError, ValueError):
            return 0.0

    items: list[dict] = []
    for row in reader[header_idx + 1 :]:
        if not any((c or "").strip() for c in row):
            continue
        if (cell(row, s_idx or 0) or (cell(row, g_idx) if g_idx is not None else "")).upper() == "TOTAL":
            break
        if g_idx is not None and "total" in cell(row, g_idx).lower():
            break
        items.append(
            {
                "group": cell(row, g_idx),
                "service": cell(row, s_idx),
                "region": cell(row, r_idx),
                "configuration": cell(row, c_idx),
                "monthly": num(cell(row, m_idx)),
                "upfront": num(cell(row, u_idx)),
            }
        )
    items = [it for it in items if it["service"]]
    return items, estimate_name, currency


def _build_bom_xlsx(estimate_name: str, currency: str, items: list[dict]) -> bytes:
    """Render a Bill of Materials Excel workbook from the parsed estimate items."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "BOM"

    navy = "1E293B"
    teal = "0D9488"
    header_fill = PatternFill("solid", fgColor="1E293B")
    header_font = Font(color="FFFFFF", bold=True, size=10)
    title_font = Font(color=navy, bold=True, size=13)
    sub_font = Font(color="64748B", italic=True, size=9)
    thin = Side(style="thin", color="E2E8F0")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    money_fmt = "#,##0.00"

    ws.merge_cells("A1:H1")
    ws["A1"] = f"Bill of Materials — {estimate_name}"
    ws["A1"].font = title_font
    ws.merge_cells("A2:H2")
    ws["A2"] = f"Source: AWS Pricing Calculator estimate · Currency: {currency} · {len(items)} line item(s)"
    ws["A2"].font = sub_font

    headers = ["#", "Group", "Service", "Region", "Description (configuration)", "Qty", "Monthly", "Upfront"]
    for col, name in enumerate(headers, start=1):
        cell = ws.cell(row=4, column=col, value=name)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    items_sorted = sorted(items, key=lambda it: (it["group"] or "", it["service"] or ""))
    grouped: dict[str, list[dict]] = {}
    for it in items_sorted:
        grouped.setdefault(it["group"] or "General", []).append(it)

    row_idx = 5
    seq = 0
    total_monthly = total_upfront = 0.0
    for group, group_items in grouped.items():
        start = row_idx
        for it in group_items:
            seq += 1
            total_monthly += it["monthly"]
            total_upfront += it["upfront"]
            values = [seq, it["group"], it["service"], it["region"], it["configuration"], 1, it["monthly"], it["upfront"]]
            for col, value in enumerate(values, start=1):
                cell = ws.cell(row=row_idx, column=col, value=value)
                cell.border = border
                cell.font = Font(size=9)
                cell.alignment = Alignment(vertical="top", wrap_text=(col == 5))
                if col in (7, 8):
                    cell.number_format = money_fmt
            row_idx += 1
        last = row_idx - 1
        ws.merge_cells(start_row=start, start_column=2, end_row=last, end_column=2)
        ws.cell(row=start, column=2, value=group).font = Font(bold=True, size=9)
        ws.cell(row=start, column=2).alignment = Alignment(vertical="center")

    ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=6)
    total_cell = ws.cell(row=row_idx, column=1, value="TOTAL")
    total_cell.font = Font(bold=True, size=10, color=teal)
    for col, value in [(7, total_monthly), (8, total_upfront)]:
        cell = ws.cell(row=row_idx, column=col, value=value)
        cell.number_format = money_fmt
        cell.font = Font(bold=True, size=10, color=teal)
    for col in range(1, 9):
        ws.cell(row=row_idx, column=col).border = border
        ws.cell(row=row_idx, column=col).fill = PatternFill("solid", fgColor="ECFDF5")
    ws.cell(row=row_idx, column=1).font = Font(bold=True, size=10, color=teal)

    widths = [5, 14, 30, 18, 55, 6, 12, 12]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A5"
    ws.auto_filter.ref = f"A4:H{row_idx - 1 if row_idx > 5 else 4}"

    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def aws_calculator_import_sync(
    db: Session,
    customer: Customer,
    aws_calculator_link: str,
    username: str,
    with_bom: bool = True,
) -> dict:
    """Download the AWS Calculator CSV + PDF for a customer, attach them (plus
    an optional BOM spreadsheet generated from the CSV) to the customer's
    documents, and record a history entry.

    Runs synchronously — caller decides whether to execute it in a thread.
    """
    link = aws_calculator_link.strip()
    if not link:
        raise ValueError("AWS Calculator link is required")

    customer.aws_calculator_link = link

    import shutil
    import tempfile

    from ..services.aws_calculator import (
        download_estimate_csv,
        download_from_calculator_pdf_sync,
    )

    backend = get_setting(db, "storage.backend", "local")
    onedrive_link = get_setting(db, "storage.onedrive_folder_link", "")
    dirpath = ensure_storage_dir()

    safe_name = (customer.customer_name or "customer").strip()
    for ch in ['"', "*", ":", "<", ">", "?", "/", "\\", "|"]:
        safe_name = safe_name.replace(ch, "_")

    tmp_dir = tempfile.mkdtemp(prefix="aws_calc_")
    errors: list[str] = []
    csv_path: str | None = None
    pdf_path: str | None = None
    imported: list[str] = []
    csv_text: str | None = None
    bom_doc: CustomerDocument | None = None

    try:
        # --- download CSV + PDF via headless browser ----------------------
        try:
            csv_path = download_estimate_csv(link, tmp_dir)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"CSV: {exc}")
        try:
            pdf_path = download_from_calculator_pdf_sync(link, tmp_dir)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"PDF: {exc}")

        # --- helper to persist a file as a customer document ---------------
        def _store(data: bytes, orig_name: str, mime: str, desc: str) -> CustomerDocument:
            prefix = uuid.uuid4().hex[:8]
            stored_name = f"{customer.id}_{prefix}_{orig_name}"
            save_path = os.path.join(dirpath, stored_name)
            with open(save_path, "wb") as fh:
                fh.write(data)
            doc = CustomerDocument(
                customer_id=customer.id,
                original_filename=orig_name,
                stored_filename=stored_name,
                file_path=save_path,
                storage_backend="onedrive" if backend == "onedrive" else "local",
                blob_url=onedrive_link if backend == "onedrive" else None,
                file_size_bytes=len(data),
                mime_type=mime,
                description=desc,
                uploaded_by=username,
                created_at=now(),
            )
            db.add(doc)
            db.flush()
            return doc

        # --- store CSV -----------------------------------------------------
        if csv_path and os.path.exists(csv_path):
            with open(csv_path, "rb") as fh:
                csv_bytes = fh.read()
            csv_text = csv_bytes.decode("utf-8-sig", errors="replace")
            doc = _store(
                csv_bytes,
                os.path.basename(csv_path),
                "text/csv",
                "AWS Calculator CSV (auto-downloaded)",
            )
            imported.append(doc.original_filename)

        # --- store PDF -----------------------------------------------------
        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as fh:
                pdf_bytes = fh.read()
            doc = _store(
                pdf_bytes,
                os.path.basename(pdf_path),
                "application/pdf",
                "AWS Calculator PDF (auto-downloaded)",
            )
            imported.append(doc.original_filename)

        # --- generate BOM from CSV -----------------------------------------
        if with_bom and csv_text:
            try:
                items, estimate_name, currency = _parse_aws_calc_csv(csv_text)
                if items:
                    bom_bytes = _build_bom_xlsx(estimate_name, currency, items)
                    bom_filename = f"BOM-{safe_name}-{uuid.uuid4().hex[:6]}.xlsx"
                    bom_doc = _store(
                        bom_bytes,
                        bom_filename,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        f"BOM auto-generated from AWS Calculator ({len(items)} items, {currency})",
                    )
                    imported.append(bom_doc.original_filename)
            except Exception:
                pass
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # --- history entry -----------------------------------------------------
    hist = OpportunityHistory()
    hist.customer_id = customer.id
    hist.action = "document"
    hist.changes_summary = (
        f"AWS Calculator auto-import: {', '.join(imported)}"
        if imported
        else f"AWS Calculator link updated (download failed: {'; '.join(errors) or 'unknown error'})"
    )
    hist.tag_name = "aws-import"
    hist.changed_by = username
    hist.created_at = now()
    db.add(hist)
    db.commit()

    return {
        "customer_id": customer.id,
        "aws_calculator_link": customer.aws_calculator_link,
        "files_imported": imported,
        "bom_generated": bom_doc is not None,
        "bom_filename": bom_doc.original_filename if bom_doc else None,
        "errors": errors,
    }


@router.post("/aws-import", status_code=status.HTTP_201_CREATED)
async def aws_calculator_import(
    customer_id: int = Query(...),
    aws_calculator_link: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download CSV + PDF from an AWS Calculator share link and store them
    (plus a BOM generated from the CSV) as customer documents."""
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    link = aws_calculator_link.strip()
    if not link:
        raise HTTPException(status_code=422, detail="AWS Calculator link is required")

    # The download is slow (~min) — run it off the event loop
    result = await asyncio.to_thread(
        aws_calculator_import_sync, db, customer, link, current_user.username, True
    )
    db.refresh(customer)
    return result


@router.post("/bom/generate", response_model=CustomerDocumentOut, status_code=status.HTTP_201_CREATED)
async def generate_bom(
    customer_id: int = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Build a Bill of Materials (Excel) from an uploaded AWS calculator CSV and store it for the customer."""
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Empty file")

    try:
        text = content.decode("utf-8-sig", errors="replace")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="Could not read CSV") from exc

    items, estimate_name, currency = _parse_aws_calc_csv(text)
    if not items:
        raise HTTPException(
            status_code=422,
            detail="Could not find any services in the CSV. Make sure it is an AWS Pricing Calculator CSV export.",
        )

    try:
        bom_bytes = _build_bom_xlsx(estimate_name, currency, items)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Could not build BOM workbook: {exc}") from exc

    backend = get_setting(db, "storage.backend", "local")
    onedrive_link = get_setting(db, "storage.onedrive_folder_link", "")

    dirpath = ensure_storage_dir()
    safe_name = f"{customer.customer_name or 'customer'}"
    for ch in ['"', "*", ":", "<", ">", "?", "/", "\\", "|"]:
        safe_name = safe_name.replace(ch, "_")
    base = f"BOM-{safe_name}-{uuid.uuid4().hex[:6]}"
    filename = f"{base}.xlsx"
    prefix = uuid.uuid4().hex[:8]
    stored_name = f"{customer.id}_{prefix}_{filename}"
    file_path = os.path.join(dirpath, stored_name)
    with open(file_path, "wb") as fh:
        fh.write(bom_bytes)

    doc = CustomerDocument(
        customer_id=customer.id,
        original_filename=filename,
        stored_filename=stored_name,
        file_path=file_path,
        storage_backend="onedrive" if backend == "onedrive" else "local",
        blob_url=onedrive_link if backend == "onedrive" else None,
        file_size_bytes=len(bom_bytes),
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        description=f"Bill of Materials from '{estimate_name}' ({len(items)} item(s), {currency})",
        uploaded_by=current_user.username,
        created_at=now(),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc