"""
A copy from elsewhere, a newer GitHub release: offered, and taken only when
asked (--take-newer; ADR-0039 amendment, ADR-0005).

Measured on 2026-10-23: with GitHub out of reach Ascension came from a Beamdog
thread as v1.5 BETA while krion64's daily scan names its release 2.1.0.
"""
import io
import json
import zipfile

from test_discovery_end_to_end import WEIDU, CATALOGUE, DiscoveryStub, make, run

FORUM = "https://forums.beamdog.com/uploads/FileUpload/2c/93c3.zip"
ASSET = "https://github.com/Gibberlings3/EndlessBG1/releases/download/v2.0/m.zip"
RELEASE = {"Gibberlings3/EndlessBG1": {
    "tag": "v2.0", "release_date": "2026-05-18",
    "release_url": "https://github.com/Gibberlings3/EndlessBG1/releases/tag/v2.0"}}


def mod_zip(version, folder="EndlessBG1"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{folder}/{folder}.tp2", f"BACKUP ~x~\nVERSION ~{version}~\n")
    return buf.getvalue()


def setup(tmp_path, monkeypatch, stub, cache=RELEASE,
          repo="https://github.com/Gibberlings3/EndlessBG1"):
    make(tmp_path, monkeypatch, stub, WEIDU, CATALOGUE)
    (tmp_path / "lcc.json").write_text(json.dumps({"mods": [
        {"tp2": "EndlessBG1", "name": "Endless BG1", "urls": [FORUM, repo]}]}))
    (tmp_path / "vc.json").write_text(json.dumps(cache))


ARGS = ["-w", "WeiDU.log", "-t", "Mods", "-c", "lcc.json", "--releases", "vc.json",
        "--no-discovery", "--json-report", "r.json"]


def record(tmp_path):
    return json.loads((tmp_path / "r.json").read_text())["records"][0]


def installed_version(tmp_path):
    return (tmp_path / "Mods" / "EndlessBG1" / "EndlessBG1.tp2").read_text()


def test_a_newer_github_release_is_offered_not_taken(tmp_path, monkeypatch):
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("v1.5 BETA")})
    setup(tmp_path, monkeypatch, stub)

    code, out = run(ARGS)

    assert code == 0, out
    assert "v1.5 BETA" in installed_version(tmp_path)
    rec = record(tmp_path)
    assert rec["newer"]["version"] == "v2.0"
    assert rec["newer"]["installed"] == "v1.5 BETA"
    assert rec["newer"]["repo"] == "Gibberlings3/EndlessBG1"
    assert "--take-newer EndlessBG1" in out
    assert stub.downloaded == [FORUM]                  # nothing taken unasked


def test_take_newer_replaces_the_copy_and_keeps_the_old_one(tmp_path, monkeypatch):
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("v1.5 BETA")})
    setup(tmp_path, monkeypatch, stub)
    assert run(ARGS)[0] == 0

    # GitHub answers on the second run, the one the player asked for
    stub.releases = {"Gibberlings3/EndlessBG1": {"tag_name": "v2.0", "assets": [
        {"name": "m.zip", "browser_download_url": ASSET}]}}
    stub.blobs[ASSET] = mod_zip("v2.0")
    code, out = run([*ARGS, "--take-newer", "EndlessBG1"])

    assert code == 0, out
    assert "VERSION ~v2.0~" in installed_version(tmp_path)
    assert stub.downloaded == [FORUM, ASSET]
    rec = record(tmp_path)
    assert rec["status"] == "ok" and "as asked" in rec["detail"]
    assert "previous copy kept" in rec["detail"]
    assert not rec["newer"]


def test_take_newer_all_takes_what_was_offered(tmp_path, monkeypatch):
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("v1.5 BETA")})
    setup(tmp_path, monkeypatch, stub)
    assert run(ARGS)[0] == 0
    stub.releases = {"Gibberlings3/EndlessBG1": {"tag_name": "v2.0", "assets": [
        {"name": "m.zip", "browser_download_url": ASSET}]}}
    stub.blobs[ASSET] = mod_zip("v2.0")

    code, out = run([*ARGS, "--take-newer", "all"])

    assert code == 0, out
    assert "VERSION ~v2.0~" in installed_version(tmp_path)


def test_without_github_the_copy_on_disk_is_kept(tmp_path, monkeypatch):
    """Asked for, unreachable: nothing changes, and never the forum copy again."""
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("v1.5 BETA")})
    setup(tmp_path, monkeypatch, stub)
    assert run(ARGS)[0] == 0

    code, out = run([*ARGS, "--take-newer", "EndlessBG1", "--allow-manual"])

    assert code == 0, out
    assert "v1.5 BETA" in installed_version(tmp_path)
    assert stub.downloaded == [FORUM]
    rec = record(tmp_path)
    assert rec["status"] == "manual" and "copy on disk is kept" in rec["detail"]


def test_the_take_still_passes_the_tp2_check(tmp_path, monkeypatch):
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("v1.5 BETA")})
    setup(tmp_path, monkeypatch, stub)
    assert run(ARGS)[0] == 0
    stub.releases = {"Gibberlings3/EndlessBG1": {"tag_name": "v2.0", "assets": [
        {"name": "m.zip", "browser_download_url": ASSET}]}}
    stub.blobs[ASSET] = mod_zip("v2.0", folder="SomeOtherMod")

    code, out = run([*ARGS, "--take-newer", "EndlessBG1"])

    assert code == 1
    assert "v1.5 BETA" in installed_version(tmp_path)


def test_no_offer_when_the_versions_cannot_be_ranked(tmp_path, monkeypatch):
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("EAOB.9")})
    setup(tmp_path, monkeypatch, stub, cache={"Gibberlings3/EndlessBG1": {
        "tag": "v1_Beta260923"}})

    code, out = run(ARGS)

    assert code == 0, out
    assert not record(tmp_path)["newer"]
    assert "--take-newer" not in out


def test_no_offer_from_a_repository_named_otherwise(tmp_path, monkeypatch):
    """
    Measured: finchnpc's sources name Pocket-Plane-Group/Finch_NPC and
    RoxanneSHS/Finch, and only the second is in the release scan (v53). A
    repository not named like the mod is not offered.
    """
    stub = DiscoveryStub(owners={}, releases={}, blobs={FORUM: mod_zip("v4.0")})
    setup(tmp_path, monkeypatch, stub, repo="https://github.com/RoxanneSHS/Endless",
          cache={"RoxanneSHS/Endless": {"tag": "v53"}})

    code, out = run(ARGS)

    assert code == 0, out
    assert not record(tmp_path)["newer"]


def test_a_copy_from_github_is_not_offered_its_own_release(tmp_path, monkeypatch):
    stub = DiscoveryStub(
        owners={},
        releases={"Gibberlings3/EndlessBG1": {"tag_name": "v1.0", "assets": [
            {"name": "m.zip", "browser_download_url": ASSET}]}},
        blobs={ASSET: mod_zip("v1.0")})
    setup(tmp_path, monkeypatch, stub)

    code, out = run(ARGS)

    assert code == 0, out
    assert stub.downloaded == [ASSET]
    assert not record(tmp_path)["newer"]
