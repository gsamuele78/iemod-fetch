"""
The GUI and the CLI share one community-data folder (GUI-AUDIT M6 item 39).

A refresh downloads into `<source>.new`, swaps it in, and saves the manifest
that says which commit the folder holds. Two refreshes of the same folder at
once - the wizard refreshing at start while `iemod-fetch --update-data` runs -
used the same staging folder: one wiped the other's download, and the manifest
saved last could name a commit the files on disk are not. Refreshes of one
folder now take turns.
"""
import subprocess
import sys
import threading

from iemod_fetch.datasync import load_manifest, refresh
from test_datasync import LCC, FakeGitHub, blob_sha


class Paused(FakeGitHub):
    """Stops inside the first file download until told to go on."""

    def __init__(self):
        super().__init__()
        self.inside = threading.Event()
        self.go = threading.Event()

    def read_bytes(self, url, limit=None):
        if not self.inside.is_set():
            self.inside.set()
            assert self.go.wait(10)
        return super().read_bytes(url, limit)


def _run(results, key, *args, **kw):
    results[key] = refresh(*args, **kw)


def test_two_refreshes_of_one_folder_take_turns(tmp_path):
    data = str(tmp_path / "data")
    first, second = Paused(), FakeGitHub()
    first.publish("o/lcc", {"db/mods.json": b'{"mods": [1]}'})
    second.publish("o/lcc", {"db/mods.json": b'{"mods": [1, 2]}'})

    results = {}
    a = threading.Thread(target=_run, args=(results, "a", first, data, (LCC,)),
                         kwargs={"force": True})
    a.start()
    assert first.inside.wait(10)
    b = threading.Thread(target=_run, args=(results, "b", second, data, (LCC,)),
                         kwargs={"force": True})
    b.start()
    b.join(0.5)                 # the second refresh would run to the end here
    first.go.set()
    a.join(10)
    b.join(10)

    assert [r.status for r in results["a"]] == ["updated"]
    assert [r.status for r in results["b"]] == ["updated"]
    entry = load_manifest(data)["lcc-docs"]
    with open(tmp_path / "data" / "lcc-docs" / "db" / "mods.json", "rb") as fh:
        on_disk = fh.read()
    assert entry["files"] == {"db/mods.json": blob_sha(on_disk)}


HOLDER = """
import sys
from filelock import FileLock
with FileLock(sys.argv[1]):
    print("held", flush=True)
    sys.stdin.read()
"""


def test_a_refresh_held_by_another_process_waits_then_keeps_the_last_copy(tmp_path):
    """The other refresh is another program (the CLI beside the wizard): the
    lock is the operating system's. Past the wait, nothing is touched, every
    source says why, and the lock is free again once that program ends."""
    data = tmp_path / "data"
    hub = FakeGitHub()
    hub.publish("o/lcc", {"db/mods.json": b'{"mods": [1]}'})
    assert [r.status for r in refresh(hub, str(data), (LCC,))] == ["updated"]
    hub.publish("o/lcc", {"db/mods.json": b'{"mods": [1, 2]}'})

    holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(data / ".lock")],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        calls = len(hub.calls)
        (result,) = refresh(hub, str(data), (LCC,), force=True, wait=0.2)
        assert result.status == "failed"
        assert "another refresh" in result.detail
        assert result.commit == load_manifest(str(data))["lcc-docs"]["commit"]
        assert len(hub.calls) == calls          # it waited: it asked GitHub nothing
    finally:
        holder.communicate(timeout=10)          # closes its stdin: it lets go and ends

    (result,) = refresh(hub, str(data), (LCC,), force=True, wait=5)
    assert result.status == "updated"
    assert (data / "lcc-docs" / "db" / "mods.json").read_bytes() == b'{"mods": [1, 2]}'
