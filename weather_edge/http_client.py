import json
import time
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


USER_AGENT = "polymarket-weather-edge/0.1 contact=local"


def get_json(url: str, params: Optional[dict] = None, timeout: int = 20, retries: int = 2, headers: Optional[dict] = None):
    if params:
        url = f"{url}?{urlencode(params)}"
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    request_headers.update(headers or {})
    request = Request(url, headers=request_headers)
    last_error = None
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            last_error = RuntimeError(f"HTTP {exc.code} for {url}")
            if exc.code < 500 and exc.code != 429:
                raise last_error from exc
        except URLError as exc:
            last_error = RuntimeError(f"request failed for {url}: {exc.reason}")
        if attempt < retries:
            time.sleep(0.25 * (2 ** attempt))
    raise last_error


def get_text(url: str, timeout: int = 20, retries: int = 2) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/csv,text/plain"})
    last_error = None
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8-sig")
        except HTTPError as exc:
            last_error = RuntimeError(f"HTTP {exc.code} for {url}")
            if exc.code < 500 and exc.code != 429:
                raise last_error from exc
        except URLError as exc:
            last_error = RuntimeError(f"request failed for {url}: {exc.reason}")
        if attempt < retries:
            time.sleep(0.25 * (2 ** attempt))
    raise last_error
