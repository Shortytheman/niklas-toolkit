import json
import struct
import sys
import zipfile

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "packs" / "godot" / "scripts"))
import pck_size  # noqa: E402


def make_pck(files: dict[str, bytes], fmt: int = 4, flags: int = 2, prefix: str = "") -> bytes:
    """A Godot 4 pack as the engine writes it: format 2 has the file table after the header, 3+ at the end."""
    def table(offsets):
        out = struct.pack("<I", len(files))
        for (path, data), off in zip(files.items(), offsets):
            raw = (prefix + path).encode()
            raw += b"\0" * (-len(raw) % 4)
            out += struct.pack("<I", len(raw)) + raw + struct.pack("<QQ", off, len(data)) + b"\0" * 16
            out += struct.pack("<I", 0)
        return out

    head = b"GDPC" + struct.pack("<5I", fmt, 4, 7, 2, flags)
    offsets, pos = [], 0
    for data in files.values():
        offsets.append(pos)
        pos += len(data)
    blob = b"".join(files.values())
    if fmt >= 3:
        file_base = len(head) + 16 + 64
        dir_offset = file_base + len(blob)
        return head + struct.pack("<QQ", file_base, dir_offset) + b"\0" * 64 + blob + table(offsets)
    tbl = table(offsets)
    file_base = len(head) + 8 + 64 + len(tbl)
    return head + struct.pack("<Q", file_base) + b"\0" * 64 + tbl + blob


FILES = {
    "art/hero.png.import": b'[remap]\nimporter="texture"\npath.s3tc="res://.godot/imported/hero.png-abc.s3tc.ctex"\n',
    ".godot/imported/hero.png-abc.s3tc.ctex": b"T" * 5000,
    "scenes/main.tscn.remap": b'[remap]\n\npath="res://.godot/exported/1/export-ff-main.scn"\n',
    ".godot/exported/1/export-ff-main.scn": b"S" * 700,
    "src/player.gdc": b"G" * 300,
    "project.binary": b"P" * 40,
}


@pytest.mark.parametrize("fmt,prefix", [(4, ""), (3, ""), (2, "res://")])
def test_reads_pack_and_names_sources(tmp_path, fmt, prefix):
    path = tmp_path / "game.pck"
    path.write_bytes(make_pck(FILES, fmt, prefix=prefix))
    pack = pck_size.open_target(path)
    assert pack.version == "4.7.2" and pack.format == fmt and len(pack.entries) == 6
    sources = {e.path: e.source for e in pack.entries}
    assert sources[".godot/imported/hero.png-abc.s3tc.ctex"] == "art/hero.png"
    assert sources[".godot/exported/1/export-ff-main.scn"] == "scenes/main.tscn"
    assert sources["src/player.gdc"] == "src/player.gd"
    r = pck_size.report(pack, top=3, depth=1)
    assert r["largest"][0] == {"source": "art/hero.png", "bytes": 5000 + len(FILES["art/hero.png.import"])}
    assert r["folders"][0]["folder"] == "art" and r["kinds"][0]["kind"] == "texture"


def test_embedded_pack_and_zip(tmp_path):
    pck = make_pck(FILES)
    exe = b"MZ" + b"\0" * 1000 + pck + struct.pack("<Q", len(pck)) + b"GDPC"
    (tmp_path / "game.exe").write_bytes(exe)
    assert len(pck_size.open_target(tmp_path / "game.exe").entries) == 6

    builds = tmp_path / "proj" / "export" / "builds"
    builds.mkdir(parents=True)
    with zipfile.ZipFile(builds / "game 1.0 windows.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("game/game.exe", exe)                   # embedded: found without a .pck member
        z.writestr("game/readme.txt", "hi")
    pack = pck_size.open_target(tmp_path / "proj")       # project folder: newest build in export/builds
    assert pack.label == "game 1.0 windows.zip > game/game.exe"
    assert {e.source for e in pack.entries} >= {"art/hero.png", "scenes/main.tscn"}


def test_compare_and_cli(tmp_path, capsys):
    old = tmp_path / "old.pck"
    new = tmp_path / "new.pck"
    old.write_bytes(make_pck(FILES))
    grown = dict(FILES)
    grown[".godot/imported/hero.png-abc.s3tc.ctex"] = b"T" * 9000
    grown["src/extra.gdc"] = b"E" * 100
    del grown["project.binary"]
    new.write_bytes(make_pck(grown))
    c = pck_size.compare(pck_size.open_target(new), pck_size.open_target(old), top=10, depth=1)
    assert c["files"][0] == {"source": "art/hero.png", "change_bytes": 4000, "status": "changed"}
    assert {f["source"]: f["status"] for f in c["files"]}["src/extra.gd"] == "new"
    assert c["added"] == 1 and c["removed"] == 1

    assert pck_size.main([str(new), "--compare", str(old)]) == 0
    assert "+3.9 KB  art/hero.png" in capsys.readouterr().out
    assert pck_size.main([str(new), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["files"] == 6


def test_unreadable_targets(tmp_path, capsys):
    (tmp_path / "x.pck").write_bytes(b"not a pack at all")
    assert pck_size.main([str(tmp_path / "x.pck")]) == 2
    assert "not a Godot pack" in capsys.readouterr().err
    (tmp_path / "enc.pck").write_bytes(make_pck(FILES, flags=3))
    assert pck_size.main([str(tmp_path / "enc.pck")]) == 2
    assert "encrypted" in capsys.readouterr().err
    assert pck_size.main([str(tmp_path)]) == 2            # a folder without export/builds
    assert "export first" in capsys.readouterr().err
