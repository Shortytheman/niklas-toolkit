# GENERATED from shared/netlib.py by tools/sync_shared.py; edit the master copy, not this file.
"""Small HTTP layer for toolkit scripts: standard library only.

The master copy lives in shared/netlib.py; tools/sync_shared.py copies it into every pack that needs it (packs
are installed separately, so they cannot import from each other). Edit the master copy, then run the sync.

What it does for every request:
- an identifying User-Agent ("niklas-toolkit/<version> (<contact>)"); several free APIs require contact details
  (MET Norway, SEC EDGAR, Wikimedia) and block generic agents
- gzip decoding, a timeout, and up to 2 retries on 429/502/503/504 that honour Retry-After
- an on-disk cache with a time-to-live per call, plus ETag / Last-Modified revalidation, so repeated questions
  do not spend rate limits
- API keys from environment variables or the user's config file, never printed

Settings live in the user's config file (see config_path()):
    {"contact": "you@example.com", "keys": {"TIINGO_API_KEY": "..."}, "location": {...}, ...}
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import platform
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = "0.12.0"
DEFAULT_TIMEOUT = 20
RETRY_STATUSES = {429, 502, 503, 504}


class NetError(Exception):
    """A request failed after retries; the message says what to tell the user."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- config

def app_dir() -> Path:
    """%LOCALAPPDATA%/niklas-toolkit on Windows, ~/.config/niklas-toolkit elsewhere (override: TOOLKIT_HOME)."""
    if os.environ.get("TOOLKIT_HOME"):
        return Path(os.environ["TOOLKIT_HOME"])
    if platform.system() == "Windows" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "niklas-toolkit"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "niklas-toolkit"


def config_path() -> Path:
    return app_dir() / "config.json"


def load_config() -> dict:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise NetError(f"{path} is not valid JSON: {e}") from e


def get_key(name: str) -> str | None:
    """An API key from the environment, else from config.json "keys". Never log the value."""
    return os.environ.get(name) or load_config().get("keys", {}).get(name) or None


def user_agent() -> str:
    contact = os.environ.get("TOOLKIT_CONTACT") or load_config().get("contact")
    base = f"niklas-toolkit/{VERSION} (+https://github.com/Shortytheman/niklas-toolkit"
    return base + (f"; {contact})" if contact else ")")


# ---------------------------------------------------------------- cache

def _cache_file(key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    return app_dir() / "cache" / f"{digest}.json"


def _cache_read(key: str) -> dict | None:
    f = _cache_file(key)
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _cache_write(key: str, entry: dict) -> None:
    f = _cache_file(key)
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry), encoding="utf-8")
        os.replace(tmp, f)
    except OSError:
        pass  # a cache that cannot be written is not an error


# ---------------------------------------------------------------- requests

# Tests replace this with a fake: (urllib.request.Request, timeout) -> (status, headers dict, body bytes)
def _default_transport(req: urllib.request.Request, timeout: float) -> tuple[int, dict, bytes]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read() or b""


transport = _default_transport


def request(url: str, *, params: dict | None = None, data: bytes | None = None, headers: dict | None = None,
            ttl: float = 0, timeout: float = DEFAULT_TIMEOUT, retries: int = 2, source: str = "") -> bytes:
    """GET (or POST when data is given) and return the body. ttl > 0 caches the answer for that many seconds.

    `source` names the service in error messages ("CoinGecko"), so the user knows which one failed.
    """
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None})
    key = url + ("\n" + hashlib.sha256(data).hexdigest() if data else "")
    cached = _cache_read(key) if ttl > 0 or data is None else None
    if cached and ttl > 0 and time.time() - cached.get("time", 0) < ttl:
        return cached["body"].encode("latin-1")

    hdrs = {"User-Agent": user_agent(), "Accept-Encoding": "gzip"}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    if cached and data is None:
        if cached.get("etag"):
            hdrs["If-None-Match"] = cached["etag"]
        if cached.get("last_modified"):
            hdrs["If-Modified-Since"] = cached["last_modified"]
    hdrs.update(headers or {})

    name = source or urllib.parse.urlsplit(url).netloc
    attempt = 0
    while True:
        req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if data is not None else "GET")
        try:
            status, resp_headers, body = transport(req, timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            permanent = "CERTIFICATE_VERIFY_FAILED" in str(getattr(e, "reason", e))  # retrying will not help
            if attempt < retries and not permanent:
                attempt += 1
                time.sleep(1.5 * attempt)
                continue
            if cached:
                return cached["body"].encode("latin-1")  # offline: an old answer beats none
            reason = getattr(e, "reason", e)
            if "CERTIFICATE_VERIFY_FAILED" in str(reason):
                raise NetError(f"{name}: its HTTPS certificate could not be verified by this Python "
                               "(often a missing intermediate certificate; a newer Python or OS update can fix it)") from e
            raise NetError(f"{name} could not be reached: {reason}") from e
        if status == 304 and cached:
            cached["time"] = time.time()
            _cache_write(key, cached)
            return cached["body"].encode("latin-1")
        if status in RETRY_STATUSES and attempt < retries:
            attempt += 1
            time.sleep(_retry_after(resp_headers.get("retry-after"), attempt))
            continue
        break

    if resp_headers.get("content-encoding") == "gzip":
        body = gzip.decompress(body)
    if status >= 400:
        detail = body[:300].decode("utf-8", "replace").strip()
        hint = {401: "the API key is missing or wrong", 403: "access refused (key, plan or region)",
                404: "not found", 429: "rate limit reached; try again later",
                451: "not available from this region"}.get(status, "")
        raise NetError(f"{name} answered HTTP {status}" + (f" ({hint})" if hint else "") +
                       (f": {detail}" if detail and status != 404 else ""), status)
    if ttl > 0 or resp_headers.get("etag") or resp_headers.get("last-modified"):
        _cache_write(key, {"time": time.time(), "etag": resp_headers.get("etag"),
                           "last_modified": resp_headers.get("last-modified"), "body": body.decode("latin-1")})
    return body


def _retry_after(value: str | None, attempt: int) -> float:
    try:
        return min(float(value), 30.0) if value else 2.0 * attempt
    except ValueError:
        return 2.0 * attempt


def get_json(url: str, **kwargs) -> object:
    body = request(url, **kwargs)
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise NetError(f"{kwargs.get('source') or url} did not return JSON") from e


def post_json(url: str, payload: object, **kwargs) -> object:
    return get_json(url, data=json.dumps(payload).encode("utf-8"), **kwargs)


def get_text(url: str, **kwargs) -> str:
    return request(url, **kwargs).decode("utf-8", "replace")


# ---------------------------------------------------------------- output

def force_utf8_output() -> None:
    """Windows consoles default to a legacy code page; make print() safe for any text."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
