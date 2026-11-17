#!/usr/bin/env python3
"""
The winget manifests of a release (ADR-0062): the three files Windows'
package manager reads to install the wizard with `winget install`, laid out
as microsoft/winget-pkgs wants them.

    python packaging/winget.py v4.2.0                       # SHA256SUMS from the release
    python packaging/winget.py v4.2.0 --sums dist/SHA256SUMS --out winget-out

They point at the release's per-user installer (ADR-0061),
iemod-fetch-gui-<os>-<arch>-setup.exe, with the sha256 SHA256SUMS gives for
it: the bytes the release published and attested, not a new download's. A
release without the installer has no manifests; the script says so.

This only writes the files. Sending them to microsoft/winget-pkgs is a pull
request there, made by the owner (docs/RELEASING.md); nothing here talks to
that repository.
"""
import argparse
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import windows_installer as installer  # noqa: E402

REPO = "gsamuele78/iemod-fetch"
IDENTIFIER = "gsamuele78.iemod-fetch"
MANIFEST_VERSION = "1.10.0"
LOCALE = "en-US"
SETUP = f"{installer.NAME}-windows-x86_64-setup.exe"
# [Setup] AppPublisher and UninstallDisplayName: winget matches what it
# installed to the "Installed apps" entry by these, and by the ProductCode
PUBLISHER = "iemod-fetch contributors"
DISPLAY_NAME = "iemod-fetch"
PRODUCT_CODE = installer.APP_ID + "_is1"
# the README's banner, in winget's 256 characters
SHORT = ("Infinity Engine mods for EET, BGEE and BG2EE: fetched, verified, ordered, "
         "conflict-checked and installed from a WeiDU log.")


def schema_line(kind: str) -> str:
    return ("# yaml-language-server: $schema=https://aka.ms/winget-manifest."
            f"{kind}.{MANIFEST_VERSION}.schema.json")


def tag_version(tag: str) -> str:
    """v4.2.0 -> 4.2.0; the tag is what the release URL names."""
    found = re.fullmatch(r"v(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)", tag)
    if not found:
        raise SystemExit(f"{tag!r} is not a release tag like v4.2.0")
    return found.group(1)


def installer_sha256(sums: str) -> str:
    """The setup.exe's line of a SHA256SUMS text, upper case as winget writes it."""
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == SETUP:
            if not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
                raise SystemExit(f"SHA256SUMS: {parts[0]!r} is not a sha256")
            return parts[0].upper()
    raise SystemExit(f"SHA256SUMS names no {SETUP}: this release has no installer "
                     "(ADR-0061), so it has no winget manifests")


def manifests(tag: str, sha256: str, repo: str = REPO) -> dict[str, dict]:
    """The three manifests, by file name, as data."""
    version = tag_version(tag)
    base = f"https://github.com/{repo}"
    common = {"PackageIdentifier": IDENTIFIER, "PackageVersion": version}
    return {
        f"{IDENTIFIER}.yaml": {
            **common,
            "DefaultLocale": LOCALE,
            "ManifestType": "version",
            "ManifestVersion": MANIFEST_VERSION,
        },
        f"{IDENTIFIER}.installer.yaml": {
            **common,
            "InstallerType": "inno",
            "Scope": "user",
            "UpgradeBehavior": "install",
            "ProductCode": PRODUCT_CODE,
            "AppsAndFeaturesEntries": [{
                "DisplayName": DISPLAY_NAME,
                "Publisher": PUBLISHER,
                "ProductCode": PRODUCT_CODE,
            }],
            "Installers": [{
                "Architecture": "x64",
                "InstallerUrl": f"{base}/releases/download/{tag}/{SETUP}",
                "InstallerSha256": sha256,
            }],
            "ManifestType": "installer",
            "ManifestVersion": MANIFEST_VERSION,
        },
        f"{IDENTIFIER}.locale.{LOCALE}.yaml": {
            **common,
            "PackageLocale": LOCALE,
            "Publisher": PUBLISHER,
            "PublisherUrl": base,
            "PublisherSupportUrl": f"{base}/issues",
            "PackageName": "iemod-fetch",
            "PackageUrl": base,
            "License": "MIT",
            "LicenseUrl": f"{base}/blob/{tag}/LICENSE",
            "ShortDescription": SHORT,
            "ReleaseNotesUrl": f"{base}/releases/tag/{tag}",
            "ManifestType": "defaultLocale",
            "ManifestVersion": MANIFEST_VERSION,
        },
    }


def scalar(value: str) -> str:
    """A string as YAML, always double-quoted: JSON's string syntax, which
    YAML's double-quoted scalars share, so a ':', '#' or quote in it, or a
    value like 4.2.0 or yes, is read back as the same string. Not ASCII-only:
    the file is UTF-8, and JSON would write a character beyond the BMP (an
    emoji) as a surrogate pair, which YAML does not join back."""
    return json.dumps(value, ensure_ascii=False)


def emit(data: dict, indent: str = "") -> list[str]:
    """Block YAML of a mapping whose values are strings, lists of strings
    or lists of such mappings - all a manifest holds."""
    lines = []
    for key, value in data.items():
        if isinstance(value, str):
            lines.append(f"{indent}{key}: {scalar(value)}")
        elif isinstance(value, list):
            lines.append(f"{indent}{key}:")
            for item in value:
                if isinstance(item, dict):
                    body = emit(item, indent + "  ")
                    lines.append(f"{indent}- {body[0].lstrip()}")
                    lines.extend(body[1:])
                else:
                    lines.append(f"{indent}- {scalar(item)}")
        else:
            raise TypeError(f"{key}: {type(value).__name__} is not written")
    return lines


def render(data: dict) -> str:
    return "\n".join([schema_line(data["ManifestType"]), "", *emit(data), ""])


def write(tag: str, sha256: str, out: str, repo: str = REPO) -> str:
    """The manifests in `out`, under winget-pkgs' path for this version."""
    publisher, package = IDENTIFIER.split(".", 1)
    folder = os.path.join(out, "manifests", publisher[0].lower(), publisher, package,
                          tag_version(tag))
    os.makedirs(folder, exist_ok=True)
    for name, data in manifests(tag, sha256, repo).items():
        with open(os.path.join(folder, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render(data))
    return folder


def release_sums(tag: str, repo: str = REPO) -> str:
    url = f"https://github.com/{repo}/releases/download/{tag}/SHA256SUMS"
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 (https)
        return response.read().decode("utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tag", help="the release's tag, e.g. v4.2.0")
    parser.add_argument("--sums", help="its SHA256SUMS file (default: the release's own)")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY") or REPO)
    parser.add_argument("--out", default="winget-manifests")
    args = parser.parse_args(argv)
    tag_version(args.tag)
    if args.sums:
        with open(args.sums, encoding="utf-8") as fh:
            sums = fh.read()
    else:
        sums = release_sums(args.tag, args.repo)
    folder = write(args.tag, installer_sha256(sums), args.out, args.repo)
    sys.stdout.write(folder + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
