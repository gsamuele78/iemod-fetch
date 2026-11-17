"""
The winget manifests of a release (ADR-0062): valid against winget's own
schemas (v1.10.0, tests/data/winget), pointing at the release's installer
with the sha256 SHA256SUMS gives, matching what the installer registers in
"Installed apps", and written as YAML that reads back as the same data.
"""
import importlib.util
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGING = os.path.join(HERE, os.pardir, "packaging")
SCHEMAS = os.path.join(HERE, "data", "winget")
sys.path.insert(0, PACKAGING)
SPEC = importlib.util.spec_from_file_location("winget", os.path.join(PACKAGING, "winget.py"))
assert SPEC and SPEC.loader
winget = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(winget)

DIGEST = "ab" * 32
SUMS = f"""{"cd" * 32}  iemod-fetch.pyz
{"ef" * 32}  iemod-fetch-gui-windows-x86_64.zip
{DIGEST}  iemod-fetch-gui-windows-x86_64-setup.exe
"""
KINDS = {"version", "installer", "defaultLocale"}


def schema(kind: str) -> dict:
    with open(os.path.join(SCHEMAS, f"manifest.{kind}.1.10.0.json"), encoding="utf-8") as fh:
        return json.load(fh)


def built(tag="v4.2.0"):
    return winget.manifests(tag, winget.installer_sha256(SUMS))


def test_every_manifest_is_valid_against_wingets_schema():
    # a test extra: the job that runs the suite with pytest alone skips this
    jsonschema = pytest.importorskip("jsonschema")
    found = set()
    for name, data in built().items():
        kind = data["ManifestType"]
        found.add(kind)
        jsonschema.Draft7Validator(schema(kind)).validate(data)
        assert name.startswith(winget.IDENTIFIER + ".") and name.endswith(".yaml")
    assert found == KINDS


def test_the_installer_is_the_releases_with_its_published_sha256():
    data = built()[f"{winget.IDENTIFIER}.installer.yaml"]
    (entry,) = data["Installers"]
    assert entry["InstallerUrl"] == ("https://github.com/gsamuele78/iemod-fetch/releases/"
                                     "download/v4.2.0/iemod-fetch-gui-windows-x86_64-setup.exe")
    assert entry["InstallerSha256"] == DIGEST.upper()
    assert entry["Architecture"] == "x64"
    assert data["InstallerType"] == "inno" and data["Scope"] == "user"


def test_the_version_is_the_tags():
    for data in built("v4.2.0").values():
        assert data["PackageVersion"] == "4.2.0"
    assert winget.tag_version("v5.0.0-rc.1") == "5.0.0-rc.1"


@pytest.mark.parametrize("tag", ["4.2.0", "v4.2", "latest", "v4.2.0/../x"])
def test_a_tag_that_is_not_a_release_is_refused(tag):
    with pytest.raises(SystemExit, match="release tag"):
        winget.tag_version(tag)


def test_a_release_without_the_installer_has_no_manifests():
    with pytest.raises(SystemExit, match="no installer"):
        winget.installer_sha256(SUMS.replace("-setup.exe", ".exe"))


def test_a_malformed_digest_is_refused():
    with pytest.raises(SystemExit, match="not a sha256"):
        winget.installer_sha256(f"xyz  {winget.SETUP}\n")


def test_a_binary_mode_sums_line_is_read():
    assert winget.installer_sha256(f"{DIGEST} *{winget.SETUP}\n") == DIGEST.upper()


def iss() -> dict:
    values = {}
    with open(os.path.join(PACKAGING, "windows", "iemod-fetch-gui.iss"), encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if "=" in line and not line.startswith((";", "#", "Name:", "Source:", "Filename:",
                                                     "Type:")):
                key, value = line.split("=", 1)
                values[key] = value
    return values


def test_it_names_the_entry_the_installer_registers():
    # winget finds what it installed in "Installed apps" by these
    setup = iss()
    data = built()[f"{winget.IDENTIFIER}.installer.yaml"]
    (entry,) = data["AppsAndFeaturesEntries"]
    assert entry["DisplayName"] == setup["UninstallDisplayName"] == "iemod-fetch"
    assert entry["Publisher"] == setup["AppPublisher"]
    assert setup["AppId"] == "{" + winget.installer.APP_ID       # {{ escapes { in Inno
    assert data["ProductCode"] == entry["ProductCode"] == winget.installer.APP_ID + "_is1"
    locale = built()[f"{winget.IDENTIFIER}.locale.en-US.yaml"]
    assert locale["Publisher"] == setup["AppPublisher"]


def test_the_identifier_and_layout_are_winget_pkgs(tmp_path):
    folder = winget.write("v4.2.0", DIGEST.upper(), str(tmp_path))
    assert os.path.relpath(folder, tmp_path).split(os.sep) == [
        "manifests", "g", "gsamuele78", "iemod-fetch", "4.2.0"]
    assert sorted(os.listdir(folder)) == sorted(built())


def read_back(text: str) -> dict:
    """The YAML subset emit() writes, read without a YAML library: the
    first line is the schema comment, then `key: scalar`, `key:` followed by
    `- scalar` items or `- key: scalar` mappings indented by two."""
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]

    def value(raw: str) -> str:
        return json.loads(raw) if raw.startswith('"') else raw

    data: dict = {}
    i = 0
    while i < len(lines):
        key, _, rest = lines[i].partition(":")
        assert not key.startswith(" ") and re.fullmatch(r"[A-Za-z]+", key), lines[i]
        i += 1
        if rest:
            data[key] = value(rest[1:])
            continue
        items: list = []
        while i < len(lines) and lines[i].startswith("- "):
            head = lines[i][2:]
            i += 1
            if re.match(r"[A-Za-z]+: ", head):
                k, _, v = head.partition(": ")
                item = {k: value(v)}
                while i < len(lines) and lines[i].startswith("  "):
                    k, _, v = lines[i].strip().partition(": ")
                    item[k] = value(v)
                    i += 1
                items.append(item)
            else:
                items.append(value(head))
        data[key] = items
    return data


def test_the_yaml_reads_back_as_the_same_data():
    for data in built().values():
        text = winget.render(data)
        assert text.startswith(winget.schema_line(data["ManifestType"]) + "\n")
        assert read_back(text) == data


def test_the_yaml_reads_back_with_a_yaml_library():
    yaml = pytest.importorskip("yaml")
    for data in built().values():
        assert yaml.safe_load(winget.render(data)) == data


@pytest.mark.parametrize("text", ["4.2.0", "yes", "a: b", "{x}", "x #y", "true", "Null",
                                  "-x", "it's", "x:"])
def test_a_scalar_that_could_be_read_as_something_else_is_quoted(text):
    out = winget.scalar(text)
    if out != text:
        assert json.loads(out) == text
    else:
        assert text == "it's"


def test_main_writes_from_a_sums_file(tmp_path, capsys):
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(SUMS)
    assert winget.main(["v4.2.0", "--sums", str(sums), "--out", str(tmp_path / "out"),
                        "--repo", "gsamuele78/iemod-fetch"]) == 0
    folder = capsys.readouterr().out.strip()
    with open(os.path.join(folder, f"{winget.IDENTIFIER}.installer.yaml"), encoding="utf-8") as fh:
        assert DIGEST.upper() in fh.read()
