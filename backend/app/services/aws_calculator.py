"""AWS Pricing Calculator access — estimate download, CSV export, BOM and PDF.

Estimates are fetched from AWS's public CDN API (the same one the calculator
web app uses), then rendered into the AWS-export CSV layout, a Bill of
Materials workbook and a print-ready PDF. No browser is used to read the
estimate: headless Chromium only prints our own HTML, so the PDF always
paginates properly instead of capturing a single screenful of the web UI.
"""

from __future__ import annotations

import asyncio
import csv as _csv
import html
import io
import json
import logging
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────
# Estimate data API (no browser required — same endpoints the calculator app
# uses). These mirrors the approach of the AWS calculator community tooling
# (e.g. github.com/timorunge/aws-calculator).
# ──────────────────────────────────────────────────────────────────────────
CALCULATOR_BASE_URL = "https://calculator.aws/"
FALLBACK_ESTIMATE_API = "https://d3knqfixx3sbls.cloudfront.net/{estimateKey}"
SERVICE_MANIFEST_URL = "https://d1qsjq9pzbk1k6.cloudfront.net/manifest/en_US.json"

_ESTIMATE_ID_RE = re.compile(r"^[0-9a-fA-F]{20,64}$")
_CONFIG_JS_RE = re.compile(r'src="([^"]*config\.js)"')

_api_url_cache: str | None = None
_api_url_cached_at: float = 0.0
_manifest_cache: dict[str, str] | None = None
_manifest_cached_at: float = 0.0
_NAMES_TTL_SEC = 6 * 3600


def parse_estimate_id(url_or_id: str) -> str | None:
    """Extract the estimate ID from a calculator URL or a bare hex ID."""
    s = (url_or_id or "").strip()
    if not s:
        return None
    if _ESTIMATE_ID_RE.match(s):
        return s

    parsed = urlparse(s)
    candidates: list[str] = []
    fragment = parsed.fragment
    if fragment:
        frag_parsed = urlparse(f"http://x{fragment}")
        candidates.append(frag_parsed.path)
        if frag_parsed.query:
            candidates.append(frag_parsed.query)
    if parsed.query:
        candidates.append(parsed.query)
    for cand in candidates:
        qs = parse_qs(cand)
        if "id" in qs and qs["id"]:
            return qs["id"][0]
        m = re.search(r"/estimate/id/([0-9a-fA-F]{20,64})", cand)
        if m:
            return m.group(1)

    return extract_estimate_id(s) or (s if _ESTIMATE_ID_RE.match(s) else None)


def _extract_balanced_braces(text: str, start: int) -> str | None:
    """Extract a balanced {...} block from *text* starting at *start*."""
    depth = 0
    string_char: str | None = None
    escape_next = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch in ('"', "'"):
            if string_char is None:
                string_char = ch
            elif string_char == ch:
                string_char = None
            continue
        if string_char is not None:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _find_nested_value(obj: Any, target: str) -> str | None:
    """Recursively search a nested dict/list for a key with a string value."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == target and isinstance(v, str):
                return v
            result = _find_nested_value(v, target)
            if result is not None:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _find_nested_value(item, target)
            if result is not None:
                return result
    return None


def _discover_estimate_api_url(timeout_sec: float = 15.0) -> str | None:
    """Discover GET_SAVED_ESTIMATES_API from the calculator's config.js."""
    global _api_url_cache, _api_url_cached_at
    if _api_url_cache and (time.time() - _api_url_cached_at) < _NAMES_TTL_SEC:
        return _api_url_cache

    discovered = FALLBACK_ESTIMATE_API
    try:
        resp = httpx.get(CALCULATOR_BASE_URL, timeout=timeout_sec, follow_redirects=True)
        resp.raise_for_status()
        m = _CONFIG_JS_RE.search(resp.text)
        if m:
            config_url = urljoin(CALCULATOR_BASE_URL, m.group(1))
            config_js = httpx.get(config_url, timeout=timeout_sec, follow_redirects=True).text
            idx = config_js.find("window.PRC_CONFIG")
            if idx != -1:
                brace_start = config_js.find("{", idx)
                if brace_start != -1:
                    block = _extract_balanced_braces(config_js, brace_start)
                    if block:
                        config = json.loads(block)
                        api = _find_nested_value(config, "GET_SAVED_ESTIMATES_API")
                        if api:
                            discovered = urljoin(CALCULATOR_BASE_URL, api)
    except Exception:  # noqa: BLE001
        logger.warning("estimate API discovery failed; using fallback URL", exc_info=True)

    _api_url_cache = discovered
    _api_url_cached_at = time.time()
    logger.info("AWS Calculator estimate API → %s", discovered)
    return discovered


def fetch_estimate(url_or_id: str, timeout_sec: int = 30) -> dict:
    """Fetch a shared AWS Pricing Calculator estimate as a JSON dict."""
    estimate_id = parse_estimate_id(url_or_id)
    if not estimate_id:
        raise RuntimeError("Could not extract an estimate ID from the AWS Calculator link.")

    def _get(api_url: str) -> httpx.Response:
        url = api_url.replace("{estimateKey}", estimate_id)
        return httpx.get(url, timeout=timeout_sec, follow_redirects=True)

    response = _get(_discover_estimate_api_url() or FALLBACK_ESTIMATE_API)
    if response.status_code in (403, 404):
        # API endpoint may have rotated — try a fresh discovery once
        global _api_url_cache
        _api_url_cache = None
        response = _get(_discover_estimate_api_url() or FALLBACK_ESTIMATE_API)

    if response.status_code == 404:
        raise RuntimeError(
            "The AWS Calculator estimate was not found. It may have expired "
            "(shared estimates are valid ~1 year) or the link may be wrong."
        )
    if not response.is_success:
        raise RuntimeError(
            f"AWS Calculator request failed (HTTP {response.status_code}). "
            "Please try again later."
        )
    try:
        data = response.json()
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("Invalid JSON returned by the AWS Calculator API.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected response from the AWS Calculator API.")
    return data


def _service_names() -> dict[str, str]:
    """serviceCode → display name map from the calculator service manifest."""
    global _manifest_cache, _manifest_cached_at
    if _manifest_cache is not None and (time.time() - _manifest_cached_at) < _NAMES_TTL_SEC:
        return _manifest_cache
    mapping: dict[str, str] = {}
    try:
        resp = httpx.get(SERVICE_MANIFEST_URL, timeout=20.0, follow_redirects=True)
        resp.raise_for_status()
        entries = resp.json().get("awsServices", [])
        mapping = {
            e["serviceCode"].strip(): (e.get("name") or "").strip()
            for e in entries
            if e.get("serviceCode")
        }
    except Exception:  # noqa: BLE001
        logger.warning("could not load AWS Calculator service manifest", exc_info=True)
    _manifest_cache = mapping
    _manifest_cached_at = time.time()
    return mapping


def _flatten_estimate_services(estimate: dict) -> list[dict]:
    """Flatten services from the top level and from any nested groups."""
    flattened: list[dict] = []
    for key, svc in (estimate.get("services") or {}).items():
        if isinstance(svc, dict):
            flattened.append({**svc, "_key": key})

    def walk(groups: Any, inherited_group: str | None = None) -> None:
        if not isinstance(groups, dict):
            return
        for gk, gv in groups.items():
            if not isinstance(gv, dict):
                continue
            group_name = inherited_group or (gv.get("name") or gk)
            for key, svc in (gv.get("services") or {}).items():
                if isinstance(svc, dict):
                    svc = {**svc, "_key": key}
                    if group_name and not svc.get("group"):
                        svc["group"] = group_name
                    flattened.append(svc)
            walk(gv.get("groups"), group_name)

    walk(estimate.get("groups"))
    return flattened


def _component_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, dict):
        if "selectedOption" in value:
            return str(value["selectedOption"])
        if "value" in value and not isinstance(value["value"], (dict, list)):
            return str(value["value"])
        return " ".join(f"{k}={v}" for k, v in value.items() if not isinstance(v, (dict, list)))
    if isinstance(value, list):
        parts = []
        for it in value:
            if isinstance(it, dict):
                inner = " ".join(
                    str(v) for k, v in it.items() if v not in ("", None) and not isinstance(v, (dict, list))
                )
                if inner:
                    parts.append(inner)
            elif it not in ("", None):
                parts.append(str(it))
        return "; ".join(parts)
    return str(value)


def _summarize_components(components: Any) -> str:
    if not isinstance(components, dict):
        return ""
    parts = []
    ignore = {"templateId", "isQuickEstimate"}
    for key, comp in components.items():
        if key in ignore:
            continue
        if isinstance(comp, dict):
            value = comp.get("value")
            unit = comp.get("unit")
        else:
            value = comp
            unit = None
        text = _component_to_text(value)
        if text:
            parts.append(f"{key}: {text}{(' ' + unit) if unit and str(unit).strip() else ''}")
    return ", ".join(parts[:12])


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def service_names() -> dict[str, str]:
    """Public accessor for the cached serviceCode → display name map."""
    return _service_names()


def estimate_to_bom_items(
    estimate: dict, name_map: dict[str, str] | None = None
) -> tuple[list[dict], str, str]:
    """Extract (line items, estimate name, currency) straight from an estimate dict.

    This is the source of truth for Bill of Materials generation. The estimate is
    read from the AWS Pricing Calculator share link, so the line items never make
    a round trip through a CSV export and nothing here depends on the column
    layout of a downloaded file.
    """
    services = _flatten_estimate_services(estimate)
    meta = estimate.get("metaData") or {}
    currency = (meta.get("currency") or "USD").strip() or "USD"
    estimate_name = (estimate.get("name") or "AWS Pricing Calculator Estimate").strip()
    name_map = name_map or {}

    items: list[dict] = []
    for svc in services:
        code = (svc.get("serviceCode") or "").strip()
        svc_name = (svc.get("serviceName") or "").strip() or name_map.get(code) or code
        if not svc_name:
            continue
        region = (svc.get("regionName") or svc.get("region") or "").strip()
        config = _summarize_components(svc.get("calculationComponents")).strip()
        if not config:
            raw_config = (svc.get("configSummary") or "").strip()
            raw_config = re.sub(r"\[object Object\]|undefined|null", "", raw_config)
            config = re.sub(r",\s*,", ",", raw_config).strip()
        cost = svc.get("serviceCost") or {}
        items.append(
            {
                "group": (svc.get("group") or "").strip(),
                "service": svc_name,
                "region": region,
                "configuration": config,
                "monthly": _num(cost.get("monthly")),
                "upfront": _num(cost.get("upfront")),
            }
        )
    return items, estimate_name, currency


def estimate_from_link(url_or_id: str, timeout_sec: int = 30) -> dict:
    """Fetch a shared estimate from an AWS Calculator link, validating the id first."""
    if not parse_estimate_id(url_or_id):
        raise RuntimeError("Could not extract an estimate ID from the AWS Calculator link.")
    return fetch_estimate(url_or_id, timeout_sec=timeout_sec)


def bom_items_from_link(url_or_id: str, timeout_sec: int = 30) -> tuple[list[dict], str, str]:
    """Read an AWS Calculator share link and return its BOM line items."""
    estimate = estimate_from_link(url_or_id, timeout_sec=timeout_sec)
    return estimate_to_bom_items(estimate, _service_names())


def estimate_to_csv(estimate: dict, name_map: dict[str, str] | None = None) -> str:
    """Render an estimate dict as an AWS-style exported CSV string.

    This is a customer-facing artefact only - the Bill of Materials is built from
    `estimate_to_bom_items` instead, so the CSV is never a dependency.
    """
    items, estimate_name, currency = estimate_to_bom_items(estimate, name_map)
    total = estimate.get("totalCost") or {}
    total_monthly = _num(total.get("monthly"))
    total_upfront = _num(total.get("upfront"))

    buf = io.StringIO()
    writer = _csv.writer(buf, lineterminator="\n")
    writer.writerow(["Estimate name", estimate_name, "", "Currency", currency, "", ""])
    created_on = (estimate.get("metaData") or {}).get("createdOn")
    if created_on:
        writer.writerow(["Saved on", created_on])
    writer.writerow([])
    writer.writerow(["Service", "Service group", "Region", "Configuration", "Monthly cost", "Upfront cost"])
    for it in items:
        writer.writerow(
            [
                it["service"],
                it["group"],
                it["region"],
                it["configuration"],
                f"{it['monthly']:.2f}",
                f"{it['upfront']:.2f}",
            ]
        )
    writer.writerow(["TOTAL", "", "", "", f"{total_monthly:.2f}", f"{total_upfront:.2f}"])
    return buf.getvalue()


def estimate_to_pdf_html(
    estimate: dict,
    name_map: dict[str, str] | None = None,
    sr_no: int | None = None,
) -> str:
    """Render an estimate dict as print-optimised HTML for the PDF artefact.

    The PDF is produced from the estimate itself rather than by printing the
    calculator's single-page web app, which yields nav chrome and only the
    visible slice of the estimate. This layout paginates properly, repeats the
    table header on every page and never drops rows off the bottom.
    """
    items, estimate_name, currency = estimate_to_bom_items(estimate, name_map)
    esc = html.escape
    total = sum(it["monthly"] for it in items)

    rows = []
    for it in sorted(items, key=lambda it: (it["group"] or "", it["service"] or "")):
        rows.append(
            "<tr>"
            f"<td class='sr'>{esc(str(sr_no)) if sr_no is not None else ''}</td>"
            f"<td class='svc'>{esc(it['service'])}</td>"
            f"<td>{esc(it['region'])}</td>"
            f"<td class='cfg'>{esc(it['configuration'])}</td>"
            f"<td class='num'>1</td>"
            f"<td class='num'>{it['monthly']:,.2f}</td>"
            "</tr>"
        )
    if not rows:
        rows.append(
            "<tr><td colspan='6' class='empty'>This estimate contains no services.</td></tr>"
        )

    sr_head = "<th class='sr'>Sr. No</th>" if sr_no is not None else ""
    sr_total = f"<td class='sr'>{esc(str(sr_no))}</td>" if sr_no is not None else "<td></td>"

    generated = datetime.now().strftime("%d %b %Y %H:%M")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{esc(estimate_name)}</title>
<style>
  @page {{ size: A4; margin: 12mm 10mm 14mm; }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{
    font-family: "Segoe UI", Arial, Helvetica, sans-serif;
    font-size: 8.5pt; color: #1e293b; line-height: 1.35;
    -webkit-print-color-adjust: exact; print-color-adjust: exact;
  }}
  h1 {{ font-size: 15pt; margin: 0 0 2px; letter-spacing: -0.2px; }}
  .sub {{ font-size: 8pt; color: #64748b; margin-bottom: 10px; }}
  .meta {{ font-size: 8pt; color: #475569; margin-bottom: 12px; }}
  .meta span {{ margin-right: 14px; }}
  table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
  thead {{ display: table-header-group; }}
  tr {{ page-break-inside: avoid; }}
  th {{
    background: #1e293b; color: #fff; font-size: 8pt; font-weight: 600;
    text-align: left; padding: 5px 6px; border: 1px solid #1e293b;
  }}
  td {{ padding: 4px 6px; border: 1px solid #e2e8f0; vertical-align: top; }}
  th.sr, td.sr {{ width: 46px; text-align: center; }}
  th.svc, td.svc {{ width: 132px; font-weight: 600; }}
  th:nth-child(3), td:nth-child(3) {{ width: 96px; }}
  td.cfg {{ color: #475569; word-break: break-word; }}
  th.num, td.num {{ width: 58px; text-align: right; white-space: nowrap; }}
  tfoot td {{ background: #ecfdf5; font-weight: 700; font-size: 8.5pt; border-top: 2px solid #0d9488; }}
  td.empty {{ text-align: center; color: #94a3b8; font-style: italic; padding: 14px; }}
  .foot {{ margin-top: 10px; font-size: 7pt; color: #94a3b8; }}
</style></head>
<body>
  <h1>{esc(estimate_name)}</h1>
  <div class="sub">AWS Pricing Calculator estimate</div>
  <div class="meta">
    <span><b>Currency:</b> {esc(currency)}</span>
    <span><b>Line items:</b> {len(items)}</span>
    <span><b>Total monthly:</b> {total:,.2f} {esc(currency)}</span>
    <span><b>Generated:</b> {esc(generated)}</span>
  </div>
  <table>
    <thead><tr>{sr_head}<th>Service</th><th>Region</th><th>Description (configuration)</th>
      <th class="num">Qty</th><th class="num">Monthly</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
    <tfoot><tr>{sr_total}<td colspan='3'>TOTAL</td>
      <td class='num'>{len(items)}</td><td class='num'>{total:,.2f}</td></tr></tfoot>
  </table>
  <div class="foot">Generated from the AWS Pricing Calculator share link on the customer
    record. Costs are estimates in {esc(currency)} and exclude taxes, support and
    any negotiated discounts.</div>
</body></html>"""


async def html_to_pdf(html_doc: str, timeout_sec: int = 60) -> bytes:
    """Print an HTML document to PDF bytes with headless Chromium."""
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            page = await browser.new_page()
            await page.set_content(html_doc, wait_until="load", timeout=timeout_sec * 1000)
            return await page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "12mm", "bottom": "14mm", "left": "10mm", "right": "10mm"},
            )
        finally:
            await browser.close()


def html_to_pdf_sync(html_doc: str, timeout_sec: int = 60) -> bytes:
    """Synchronous wrapper around :func:`html_to_pdf`."""
    return asyncio.run(html_to_pdf(html_doc, timeout_sec))


def extract_estimate_id(url: str) -> str | None:
    """Pull the estimate ID from various AWS Calculator URL formats."""
    patterns = [
        r"/estimate/id/([A-Za-z0-9_-]+)",
        r"[?&]estimateId=([A-Za-z0-9_-]+)",
        r"/#/estimate/([A-Za-z0-9_-]+)",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


