"""AWS Pricing Calculator access — estimate download + CSV export + PDF.

Estimates are fetched from AWS's public CDN API (the same one the calculator
web app uses), then rendered into the AWS-export CSV layout. A headless
browser is only used to render the estimate as a PDF.
"""

from __future__ import annotations

import asyncio
import csv as _csv
import io
import json
import logging
import re
import time
from pathlib import Path
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


def estimate_to_csv(estimate: dict, name_map: dict[str, str] | None = None) -> str:
    """Render an estimate dict as an AWS-style exported CSV string."""
    services = _flatten_estimate_services(estimate)
    meta = estimate.get("metaData") or {}
    currency = (meta.get("currency") or "USD").strip()
    name = (estimate.get("name") or "AWS Pricing Calculator Estimate").strip()
    name_map = name_map or {}
    total = estimate.get("totalCost") or {}
    total_monthly = _num(total.get("monthly"))
    total_upfront = _num(total.get("upfront"))

    buf = io.StringIO()
    writer = _csv.writer(buf, lineterminator="\n")
    writer.writerow(["Estimate name", name, "", "Currency", currency, "", ""])
    if meta.get("createdOn"):
        writer.writerow(["Saved on", meta.get("createdOn")])
    writer.writerow([])
    writer.writerow(["Service", "Service group", "Region", "Configuration", "Monthly cost", "Upfront cost"])

    for svc in services:
        code = (svc.get("serviceCode") or "").strip()
        svc_name = (svc.get("serviceName") or "").strip() or name_map.get(code) or code
        region = (svc.get("regionName") or svc.get("region") or "").strip()
        config = _summarize_components(svc.get("calculationComponents")).strip()
        if not config:
            raw_config = (svc.get("configSummary") or "").strip()
            raw_config = re.sub(r"\[object Object\]|undefined|null", "", raw_config)
            config = re.sub(r",\s*,", ",", raw_config).strip()
        sc = svc.get("serviceCost") or {}
        writer.writerow([
            svc_name,
            (svc.get("group") or "").strip(),
            region,
            config,
            f"{_num(sc.get('monthly')):.2f}",
            f"{_num(sc.get('upfront')):.2f}",
        ])
    writer.writerow(["TOTAL", "", "", "", f"{total_monthly:.2f}", f"{total_upfront:.2f}"])
    return buf.getvalue()


def download_estimate_csv(url_or_id: str, dest_dir: str | Path, timeout_sec: int = 30) -> str:
    """Fetch a shared estimate from the calculator API and save it as CSV.

    Returns the path to the saved CSV file.
    """
    estimate_id = parse_estimate_id(url_or_id)
    if not estimate_id:
        raise RuntimeError("Could not extract an estimate ID from the AWS Calculator link.")

    estimate = fetch_estimate(url_or_id, timeout_sec=timeout_sec)
    names = _service_names()
    csv_text = estimate_to_csv(estimate, names)

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    out_path = dest / f"AWS-Calculator-{estimate_id[:12]}.csv"
    out_path.write_text(csv_text, encoding="utf-8")
    logger.info("Estimate CSV saved → %s", out_path)
    return str(out_path)


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


async def _dismiss_modal(page) -> None:
    """Best-effort dismissal of cookie / modal banners that block interaction."""
    for dismiss_sel in [
        "button:has-text('Got it')",
        "button:has-text('Accept')",
        "button:has-text('Close')",
        "button:has-text('Dismiss')",
        "[aria-label='Close']",
        "[aria-label='Dismiss']",
    ]:
        try:
            btn = page.locator(dismiss_sel).first
            if await btn.is_visible(timeout=500):
                await btn.click()
                await page.wait_for_timeout(500)
        except Exception:
            pass


async def download_from_calculator(
    url: str,
    dest_dir: str | Path,
    timeout_sec: int = 90,
) -> str:
    """
    Open an AWS Calculator share link in a headless browser, trigger the
    Export → CSV action, and save the file to *dest_dir*.

    Returns the path to the downloaded CSV file.
    """
    from playwright.async_api import async_playwright

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    csv_path: str | None = None

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        try:
            ctx = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                accept_downloads=True,
            )
            page = await ctx.new_page()

            logger.info("Navigating to %s", url)
            await page.goto(url, wait_until="networkidle", timeout=timeout_sec * 1000)

            # Give the SPA time to hydrate and render the estimate
            await page.wait_for_timeout(5000)

            # Try to dismiss any modal / cookie banner that blocks interaction
            for dismiss_sel in [
                "button:has-text('Got it')",
                "button:has-text('Accept')",
                "button:has-text('Close')",
                "button:has-text('Dismiss')",
                "[aria-label='Close']",
                "[aria-label='Dismiss']",
            ]:
                try:
                    btn = page.locator(dismiss_sel).first
                    if await btn.is_visible(timeout=500):
                        await btn.click()
                        await page.wait_for_timeout(500)
                except Exception:
                    pass

            # ------------------------------------------------------------------
            # Find and click the Export / Download button
            # ------------------------------------------------------------------
            export_btn = None
            for sel in [
                "button:has-text('Export')",
                "button:has-text('Download')",
                "a:has-text('Export')",
                "a:has-text('Download')",
                "[data-testid='export-button']",
                "[data-testid='download-button']",
                "button:has-text('Share')",
            ]:
                try:
                    loc = page.locator(sel).first
                    if await loc.is_visible(timeout=1000):
                        export_btn = loc
                        break
                except Exception:
                    continue

            if not export_btn:
                # Last resort: scan all buttons for export-related text
                buttons = page.locator("button, a[role='button']")
                count = await buttons.count()
                for i in range(count):
                    try:
                        txt = (await buttons.nth(i).inner_text()).strip().lower()
                        if any(kw in txt for kw in ("export", "download", "save")):
                            export_btn = buttons.nth(i)
                            break
                    except Exception:
                        continue

            if not export_btn:
                raise RuntimeError(
                    "Could not find an Export / Download button on the page. "
                    "The estimate might be private or the page layout has changed."
                )

            # ------------------------------------------------------------------
            # Capture CSV download
            # ------------------------------------------------------------------
            logger.info("Triggering CSV export …")
            async with page.expect_download(timeout=30_000) as dl_info:
                await export_btn.click()
                await page.wait_for_timeout(1000)

                csv_loc = page.locator(
                    "button:has-text('CSV'), a:has-text('CSV'), "
                    "[data-testid='export-csv'], li:has-text('CSV')"
                ).first
                if await csv_loc.is_visible(timeout=3000):
                    await csv_loc.click()
                else:
                    # Fallback: click whatever menu item has "csv" text
                    items = page.locator("li, [role='menuitem'], [role='option']")
                    cnt = await items.count()
                    for j in range(cnt):
                        try:
                            t = (await items.nth(j).inner_text()).strip().lower()
                            if "csv" in t:
                                await items.nth(j).click()
                                break
                        except Exception:
                            continue

            download = await dl_info.value
            out_path = dest / (download.suggested_filename or "estimate.csv")
            await download.save_as(str(out_path))
            csv_path = str(out_path)
            logger.info("CSV saved → %s", out_path)

        finally:
            await browser.close()

    if not csv_path:
        raise RuntimeError(
            "Unable to download the CSV from the AWS Calculator link. "
            "Please verify the link is a valid public share link."
        )

    return csv_path


async def download_from_calculator_pdf(
    url: str,
    dest_dir: str | Path,
    timeout_sec: int = 90,
) -> str:
    """
    Open an AWS Calculator share link in a headless browser and produce a PDF.

    First tries the site's own Export → PDF action; if that is not available,
    falls back to rendering the page to PDF with headless Chromium printing.

    Returns the path to the downloaded PDF file.
    """
    from playwright.async_api import async_playwright

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    pdf_path: str | None = None

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        try:
            ctx = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                accept_downloads=True,
            )
            page = await ctx.new_page()

            logger.info("Navigating to %s (PDF)", url)
            await page.goto(url, wait_until="networkidle", timeout=timeout_sec * 1000)

            # Give the SPA time to hydrate and render the estimate
            await page.wait_for_timeout(5000)
            await _dismiss_modal(page)

            # ------------------------------------------------------------------
            # Try the site's own Export → PDF action
            # ------------------------------------------------------------------
            export_btn = None
            for sel in [
                "button:has-text('Export')",
                "button:has-text('Download')",
                "a:has-text('Export')",
                "a:has-text('Download')",
                "[data-testid='export-button']",
                "[data-testid='download-button']",
            ]:
                try:
                    loc = page.locator(sel).first
                    if await loc.is_visible(timeout=1000):
                        export_btn = loc
                        break
                except Exception:
                    continue

            if export_btn:
                logger.info("Triggering PDF export …")
                download = None
                try:
                    async with page.expect_download(timeout=15_000) as dl_info:
                        await export_btn.click()
                        await page.wait_for_timeout(1000)

                        pdf_loc = page.locator(
                            "button:has-text('PDF'), a:has-text('PDF'), "
                            "[data-testid='export-pdf'], [data-testid='download-pdf'], "
                            "li:has-text('PDF')"
                        ).first
                        try:
                            if await pdf_loc.is_visible(timeout=3000):
                                await pdf_loc.click()
                            else:
                                items = page.locator("li, [role='menuitem'], [role='option']")
                                cnt = await items.count()
                                for j in range(cnt):
                                    try:
                                        t = (await items.nth(j).inner_text()).strip().lower()
                                        if "pdf" in t:
                                            await items.nth(j).click()
                                            break
                                    except Exception:
                                        continue
                        except Exception:
                            pass

                    download = await dl_info.value
                except Exception:
                    download = None

                if download:
                    out_path = dest / (download.suggested_filename or "estimate.pdf")
                    await download.save_as(str(out_path))
                    pdf_path = str(out_path)
                    logger.info("PDF saved → %s", out_path)

            # ------------------------------------------------------------------
            # Fallback: print the rendered estimate page to a PDF
            # ------------------------------------------------------------------
            if not pdf_path:
                estimate_id = extract_estimate_id(url) or "estimate"
                out_path = dest / f"estimate-{estimate_id}.pdf"
                await page.pdf(path=str(out_path), format="A4", print_background=True)
                pdf_path = str(out_path)
                logger.info("PDF (print) saved → %s", out_path)

        finally:
            await browser.close()

    if not pdf_path:
        raise RuntimeError(
            "Unable to download the PDF from the AWS Calculator link. "
            "Please verify the link is a valid public share link."
        )

    return pdf_path


def download_from_calculator_pdf_sync(
    url: str,
    dest_dir: str | Path,
    timeout_sec: int = 90,
) -> str:
    """Synchronous wrapper around the async Playwright PDF downloader."""
    return asyncio.run(download_from_calculator_pdf(url, dest_dir, timeout_sec))


def download_from_calculator_sync(
    url: str,
    dest_dir: str | Path,
    timeout_sec: int = 90,
) -> str:
    """Synchronous wrapper around the async Playwright downloader."""
    return asyncio.run(download_from_calculator(url, dest_dir, timeout_sec))