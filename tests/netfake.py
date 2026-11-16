"""A fake network for tests: routes requests by URL to canned answers. No real HTTP is ever made."""
from __future__ import annotations

import gzip
import json
import sys


class FakeNet:
    def __init__(self):
        self.routes: list[tuple[str, object]] = []
        self.calls: list[tuple[str, str, bytes | None, dict]] = []  # (method, url, body, headers)

    def add(self, url_part: str, answer) -> "FakeNet":
        """answer: dict/list (JSON 200), str/bytes (200 body), (status, headers, body), or a callable(req)."""
        self.routes.append((url_part, answer))
        return self

    def __call__(self, req, timeout):
        url = req.full_url
        self.calls.append((req.get_method(), url, req.data, dict(req.header_items())))
        for part, answer in reversed(self.routes):  # later routes override earlier ones
            if part in url:
                if callable(answer):
                    answer = answer(req)
                if isinstance(answer, tuple):
                    status, headers, body = answer
                    return status, headers, body if isinstance(body, bytes) else str(body).encode()
                if isinstance(answer, (dict, list)):
                    return 200, {"content-type": "application/json"}, json.dumps(answer).encode()
                return 200, {}, answer if isinstance(answer, bytes) else str(answer).encode()
        return 404, {}, b"no fake route for " + url.encode()

    def count(self, url_part: str) -> int:
        return sum(1 for _, url, _, _ in self.calls if url_part in url)


def gz(text: str) -> bytes:
    return gzip.compress(text.encode())


def install(monkeypatch, tmp_path) -> FakeNet:
    """Use a fresh toolkit home and the fake transport for every loaded copy of netlib."""
    monkeypatch.setenv("TOOLKIT_HOME", str(tmp_path / "toolkit-home"))
    for var in ("TOOLKIT_CONTACT", "FINNHUB_API_KEY", "TIINGO_API_KEY", "COINGECKO_DEMO_KEY"):
        monkeypatch.delenv(var, raising=False)
    fake = FakeNet()
    for name, mod in list(sys.modules.items()):
        if name == "netlib" or name.endswith(".netlib"):
            monkeypatch.setattr(mod, "transport", fake)
            monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    return fake


def write_config(tmp_path, cfg: dict) -> None:
    home = tmp_path / "toolkit-home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
