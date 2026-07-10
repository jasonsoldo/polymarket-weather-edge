import hashlib
import re
from dataclasses import replace
from pathlib import Path

from .wunderground import WundergroundSnapshot, ADAPTER_VERSION


def parse_wunderground_html(html: str, station: str, target_date: str, unit: str, source_url: str = "") -> WundergroundSnapshot:
    lower = html.lower()
    if any(token in lower for token in ("captcha", "verify you are human", "access denied")):
        return WundergroundSnapshot("wu_unavailable", station, target_date, None, None, unit, source_url=source_url, raw_payload_hash=hashlib.sha256(html.encode()).hexdigest(), adapter_version=ADAPTER_VERSION, reason="CAPTCHA or access-control page")
    requested = unit.upper().replace("°", "")
    if requested == "C" and "°f" in lower and "°c" not in lower:
        return WundergroundSnapshot("wu_source_mismatch", station, target_date, None, None, unit, source_url=source_url, raw_payload_hash=hashlib.sha256(html.encode()).hexdigest(), adapter_version=ADAPTER_VERSION, reason="page is displaying Fahrenheit")
    if requested == "F" and "°c" in lower and "°f" not in lower:
        return WundergroundSnapshot("wu_source_mismatch", station, target_date, None, None, unit, source_url=source_url, raw_payload_hash=hashlib.sha256(html.encode()).hexdigest(), adapter_version=ADAPTER_VERSION, reason="page is displaying Celsius")
    def find(label):
        match = re.search(rf"{label}\s*[:<\s][^0-9-]*(-?\d+(?:\.\d+)?)", html, re.I)
        return float(match.group(1)) if match else None
    high, low = find("high"), find("low")
    return WundergroundSnapshot("wu_browser_supported" if high is not None or low is not None else "wu_unavailable", station.upper(), target_date, high, low, unit.upper(), source_url=source_url, raw_payload_hash=hashlib.sha256(html.encode()).hexdigest(), adapter_version=ADAPTER_VERSION, reason="page structure changed or daily values missing" if high is None and low is None else "")


def fetch_wunderground_browser(url: str, station: str, target_date: str, unit: str, artifact_dir: str = "data/wunderground_artifacts", timeout_ms: int = 30000, retries: int = 2) -> WundergroundSnapshot:
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
