import json
import subprocess
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "shared"))
import netlib  # noqa: E402
from netfake import gz, install, write_config  # noqa: E402


@pytest.fixture
def net(monkeypatch, tmp_path):
    return install(monkeypatch, tmp_path)


def test_copies_in_packs_match_master():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "sync_shared.py"), "--check"], capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stdout


def test_user_agent_and_json(net, tmp_path):
    write_config(tmp_path, {"contact": "me@example.com"})
    net.add("api.test/x", {"ok": 1})
    assert netlib.get_json("https://api.test/x", params={"a": 1, "skip": None}) == {"ok": 1}
    method, url, _, headers = net.calls[0]
    assert url == "https://api.test/x?a=1"
    assert "me@example.com" in headers["User-agent"] and headers["User-agent"].startswith("niklas-toolkit/")


def test_ttl_cache_avoids_second_request(net):
    net.add("api.test/c", {"n": 1})
    netlib.get_json("https://api.test/c", ttl=60)
    netlib.get_json("https://api.test/c", ttl=60)
    assert net.count("api.test/c") == 1


def test_etag_revalidation_uses_304(net):
    net.add("api.test/e", (200, {"etag": '"v1"'}, b'{"v": 1}'))
    assert netlib.get_json("https://api.test/e") == {"v": 1}
    net.add("api.test/e", lambda req: (304, {}, b"") if req.get_header("If-none-match") == '"v1"' else (500, {}, b""))
    assert netlib.get_json("https://api.test/e") == {"v": 1}


def test_retry_on_503_then_success(net):
    answers = iter([(503, {"retry-after": "0"}, b""), (200, {}, b'{"ok": true}')])
    net.add("api.test/r", lambda req: next(answers))
    assert netlib.get_json("https://api.test/r") == {"ok": True}
    assert net.count("api.test/r") == 2


def test_errors_name_the_source_and_hint(net):
    net.add("api.test/k", (401, {}, b"bad key"))
    with pytest.raises(netlib.NetError, match=r"Thing answered HTTP 401 \(the API key is missing or wrong\)"):
        netlib.request("https://api.test/k", source="Thing")


def test_gzip_body(net):
    net.add("api.test/g", (200, {"content-encoding": "gzip"}, gz('{"z": 2}')))
    assert netlib.get_json("https://api.test/g") == {"z": 2}


def test_offline_falls_back_to_cache(net, monkeypatch):
    net.add("api.test/o", {"cached": True})
    netlib.get_json("https://api.test/o", ttl=1)

    def down(req, timeout):
        raise OSError("network down")
    monkeypatch.setattr(netlib, "transport", down)
    monkeypatch.setattr(netlib.time, "time", lambda: 10 ** 10)  # cache expired
    assert netlib.get_json("https://api.test/o", ttl=1) == {"cached": True}


def test_keys_from_env_then_config(net, tmp_path, monkeypatch):
    write_config(tmp_path, {"keys": {"X_KEY": "from-config"}})
    assert netlib.get_key("X_KEY") == "from-config"
    monkeypatch.setenv("X_KEY", "from-env")
    assert netlib.get_key("X_KEY") == "from-env"
    assert netlib.get_key("MISSING") is None


def test_post_json(net):
    net.add("api.test/p", lambda req: (200, {}, json.dumps({"echo": json.loads(req.data)}).encode()))
    assert netlib.post_json("https://api.test/p", {"q": 1}) == {"echo": {"q": 1}}
