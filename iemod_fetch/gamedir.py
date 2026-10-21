"""
Game folders, verified before a plan is installed onto them (ADR-0026).

Which game a folder holds is decided exactly as WeiDU's GAME_IS decides it
(WeiDU src/tppe.ml, PE_GameIs): by whether a marker resource exists, looked up
in override/ first and then in chitin.key -

    BGEE   oh1000.are, and not oh6000.are, and not eet.flag
    BG2EE  oh6000.are, and not eet.flag
    EET    eet.flag  (written to override/ by the EET core, EET.tp2:2797)

EET's own requirements come from its readme (readme-EET.html): the core needs
"a clean BG2:EE installation"; the BG:EE side needs Siege of Dragonspear, which
EET verifies through `movies/sodcin05.wbm`, and which GOG and Steam ship as a
DLC archive that DlcMerger must merge before any other mod. DlcMerger looks for
`sod-dlc.zip` in the game folder, `dlc/` and `workshop/` (as `.mod`) - and in
the user's documents folder, which is not looked at here.

Not checked, and said so: the patch level (EET asks for v2.6.6.0), and whether
the game data is intact.
"""
import os
import struct
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

_MAX_KEY_BYTES = 64 * 1024 * 1024
_TYPES = {"are": 0x3F2, "2da": 0x3F4}
MARKERS = {"bgee": "oh1000.are", "bg2ee": "oh6000.are", "eet": "eet.flag"}
SOD_MOVIE = os.path.join("movies", "sodcin05.wbm")
SOD_ARCHIVES = (("sod-dlc.zip",), ("dlc", "sod-dlc.zip"), ("workshop", "sod-dlc.mod"))


def _find(root: str, *parts: str) -> Optional[str]:
    """A path under `root`, each part matched case-insensitively (Linux)."""
    current = root
    for part in parts:
        direct = os.path.join(current, part)
        if os.path.exists(direct):
            current = direct
            continue
        try:
            match = next((e for e in os.listdir(current) if e.lower() == part.lower()),
                         None)
        except OSError:
            return None
        if match is None:
            return None
        current = os.path.join(current, match)
    return current


def key_resources(game_dir: str) -> Set[Tuple[str, int]]:
    """(resref, type) of every resource chitin.key lists; empty if unreadable."""
    path = _find(game_dir, "chitin.key")
    if path is None or os.path.getsize(path) > _MAX_KEY_BYTES:
        return set()
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) < 24 or data[:8] != b"KEY V1  ":
        return set()
    _bifs, count, _bif_offset, offset = struct.unpack_from("<IIII", data, 8)
    out: Set[Tuple[str, int]] = set()
    for i in range(count):
        start = offset + 14 * i
        if start + 14 > len(data):
            break
        name = data[start:start + 8].split(b"\0", 1)[0].decode("latin-1").lower()
        (kind,) = struct.unpack_from("<H", data, start + 8)
        out.add((name, kind))
    return out


def _exists(game_dir: str, resource: str, keys: Set[Tuple[str, int]]) -> bool:
    if _find(game_dir, "override", resource):
        return True
    name, _dot, ext = resource.lower().rpartition(".")
    return ext in _TYPES and (name, _TYPES[ext]) in keys


def identify(game_dir: str) -> Optional[str]:
    """BGEE, BG2EE, EET, or None - WeiDU's GAME_IS rules, nothing else."""
    if not os.path.isdir(game_dir) or _find(game_dir, "chitin.key") is None:
        return None
    keys = key_resources(game_dir)
    has = {game: _exists(game_dir, marker, keys) for game, marker in MARKERS.items()}
    if has["eet"]:
        return "EET"
    if has["bg2ee"]:
        return "BG2EE"
    if has["bgee"]:
        return "BGEE"
    return None


def installed_components(game_dir: str) -> int:
    path = _find(game_dir, "WeiDU.log")
    if path is None:
        return 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        return sum(1 for line in fh if line.startswith("~"))


def sod_state(bgee_dir: str) -> str:
    """'merged' (EET's own check passes), 'dlc' (an archive to merge), 'none'."""
    if _find(bgee_dir, *SOD_MOVIE.split(os.sep)):
        return "merged"
    if any(_find(bgee_dir, *parts) for parts in SOD_ARCHIVES):
        return "dlc"
    return "none"


@dataclass
class GameReport:
    bgee: str
    bg2ee: str
    games: Tuple[Optional[str], Optional[str]] = (None, None)
    sod: str = "none"
    problems: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [("GAME FOLDERS (identified as WeiDU's GAME_IS does; EET's readme "
                 "for what it needs)"),
                 (f"  BGEE_DIR  {self.bgee}: {self.games[0] or 'not a known game'}"
                 f", Siege of Dragonspear {self.sod}"),
                 f"  BG2EE_DIR {self.bg2ee}: {self.games[1] or 'not a known game'}"]
        lines += [f"  PROBLEM  {p}" for p in self.problems]
        lines += [f"  not checked: {n}" for n in self.notes]
        if not self.problems:
            lines.append("  both folders are what an EET install needs")
        return "\n".join(lines)


def verify_eet(bgee_dir: str, bg2ee_dir: str, plan_mods: Set[str]) -> GameReport:
    """The two folders an EET plan installs onto, against EET's requirements."""
    report = GameReport(bgee_dir, bg2ee_dir,
                        games=(identify(bgee_dir), identify(bg2ee_dir)))
    for label, folder, wanted, found in (("BGEE_DIR", bgee_dir, "BGEE", report.games[0]),
                                         ("BG2EE_DIR", bg2ee_dir, "BG2EE",
                                          report.games[1])):
        if not os.path.isdir(folder):
            report.problems.append(f"{label} {folder} does not exist")
        elif _find(folder, "chitin.key") is None:
            report.problems.append(f"{label} {folder} has no chitin.key: not a game folder")
        elif found == "EET":
            report.problems.append(f"{label} {folder} is already EET (override/EET.flag): "
                                   f"EET installs onto a clean BG2:EE")
        elif found != wanted:
            report.problems.append(f"{label} {folder} is {found or 'no known game'}, "
                                   f"not {wanted}")
    if os.path.realpath(bgee_dir) == os.path.realpath(bg2ee_dir):
        report.problems.append("BGEE_DIR and BG2EE_DIR are the same folder: EET needs "
                               "two separate games")
    if report.games[1] == "BG2EE" and installed_components(bg2ee_dir):
        report.problems.append(f"BG2EE_DIR already has {installed_components(bg2ee_dir)} "
                               f"component(s) in its WeiDU.log: EET's core requires a "
                               f"clean BG2:EE (EET readme)")
    if report.games[0] == "BGEE":
        report.sod = sod_state(bgee_dir)
        if report.sod == "dlc" and "dlcmerger" not in plan_mods:
            report.problems.append("Siege of Dragonspear is a DLC archive here (GOG/Steam): "
                                   "DlcMerger #1 must be the first mod of the BGEE plan")
        elif report.sod == "none":
            report.problems.append(f"no Siege of Dragonspear in {bgee_dir} "
                                   f"({SOD_MOVIE} missing, no sod-dlc archive): EET "
                                   f"needs BG:EE with SoD")
    report.notes.append("the patch level (EET asks for v2.6.6.0 of both games)")
    report.notes.append("whether the game data itself is intact")
    return report
