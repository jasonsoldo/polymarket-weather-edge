import hashlib
import re
from dataclasses import replace
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .wunderground import WundergroundSnapshot, ADAPTER_VERSION


def parse_wunderground_html(html: str, station: str, target_date: str, unit: str, source_url: str = "") -> WundergroundSnapshot:
    lower = html.lower()
    if any(token in lower for token in ("captcha", "verify you are human", "access denied")):
        return WundergroundSnapshot("wu_unavailable", station, target_date, None, None, unit, source_url=source_url, raw_payload_hash=hashlib.sha256(html.encode()).hexdigest(), adapter_version=ADAPTER_VERSION, reason="CAPTCHA or access-control page")
    selected_date = _selected_date(html)
    if selected_date and selected_date != target_date:
        return WundergroundSnapshot("wu_source_mismatch", station, target_date, None, None, unit, source_url=source_url, raw_payload_hash=hashlib.sha256(html.encode()).hexdigest(), adapter_version=ADAPTER_VERSION, reason=f"page selected date {selected_date} does not match target date")
    requested = unit.upper().replace("°", "")
    summary_start = lower.find('class="summary-title"')
    summary_end = lower.find('class="observation-title"', summary_start)
    summary = html[summary_start:summary_end] if summary_start >= 0 and summary_end > summary_start else html
    summary_text = re.sub(r"<[^>]+>", " ", summary)
    summary_lower = summary_text.lower()
    displayed = "F" if "°f" in summary_lower or "掳f" in summary_lower else "C" if "°c" in summary_lower or "掳c" in summary_lower else requested
    def find(label):
        summary_label = "High Temp" if label == "high" else "Low Temp"
        match = re.search(rf"\b{summary_label}\b\s*(-?\d+(?:\.\d+)?)", summary_text, re.I)
        if match:
            return float(match.group(1))
        match = re.search(rf"\b{label}\b[^\d-]{{0,80}}(-?\d+(?:\.\d+)?)\s*°?\s*([CF])\b", summary_text, re.I)
        return float(match.group(1)) if match and match.group(2).upper() == displayed else None
    high, low = find("high"), find("low")
    if high is not None and displayed != requested:
        convert = lambda value: (value - 32.0) * 5.0 / 9.0 if displayed == "F" else value * 9.0 / 5.0 + 32.0
        high, low = convert(high), convert(low) if low is not None else None
    return WundergroundSnapshot("wu_browser_supported" if high is not None or low is not None else "wu_unavailable", station.upper(), target_date, high, low, unit.upper(), source_url=source_url, raw_payload_hash=hashlib.sha256(html.encode()).hexdigest(), adapter_version=ADAPTER_VERSION, reason="page structure changed or daily values missing" if high is None and low is None else "")


def _selected_date(html: str):
    selected = re.findall(r'<option[^>]*selected="selected"[^>]*>([^<]+)', html, re.I)
    if len(selected) < 3:
        return ""
    try:
        month = list(__import__("calendar").month_name).index(selected[0].strip())
        return date(int(selected[2].strip()), month, int(selected[1].strip())).isoformat()
    except (ValueError, IndexError):
        return ""


def _history_url(url: str, target_date: str) -> str:
    parts = urlsplit(url)
    path = re.sub(r"/date/\d{4}-\d{1,2}-\d{1,2}/?$", "", parts.path.rstrip("/"))
    year, month, day = (int(value) for value in target_date.split("-"))
    return urlunsplit((parts.scheme, parts.netloc, f"{path}/date/{year}-{month}-{day}", "", ""))


def fetch_wunderground_browser(url: str, station: str, target_date: str, unit: str, artifact_dir: str = "data/wunderground_artifacts", timeout_ms: int = 30000, retries: int = 2) -> WundergroundSnapshot:
    url = _history_url(url, target_date)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return WundergroundSnapshot("wu_unavailable", station, target_date, None, None, unit, source_url=url, reason="Playwright is not installed")
    directory = Path(artifact_dir) / station.upper() / target_date
    directory.mkdir(parents=True, exist_ok=True)
    for _attempt in range(retries + 1):
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                response = page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                if response and response.status in (403, 429):
                    browser.close()
                    return WundergroundSnapshot("wu_unavailable", station, target_date, None, None, unit, source_url=url, reason=f"HTTP {response.status}")
                html = page.content()
                (directory / "page.html").write_text(html, encoding="utf-8")
                page.screenshot(path=str(directory / "page.png"), full_page=True)
                result = parse_wunderground_html(html, station, target_date, unit, url)
                browser.close()
                return result
        except Exception as exc:
            error = str(exc)
    return WundergroundSnapshot("wu_unavailable", station, target_date, None, None, unit, source_url=url, reason=error)
