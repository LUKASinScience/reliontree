"""Settings storage and the "start one ChimeraX, then reuse it" logic of chimerax_bridge (no real ChimeraX is started)."""
import json
import stat
import types

import pytest

from reliontree import chimerax_bridge as cb


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "HOME_DIR", tmp_path / ".reliontree")
    monkeypatch.setattr(cb, "SETTINGS_FILE", tmp_path / ".reliontree" / "settings.json")
    monkeypatch.setattr(cb, "QUEUE", tmp_path / ".reliontree" / "chimerax")
    monkeypatch.setattr(cb, "_launched", None)
    monkeypatch.setattr(cb, "_auto_chimerax", lambda: "/opt/ChimeraX app/ChimeraX")
    return tmp_path


def test_settings_roundtrip_and_permissions(home):
    assert cb.load_settings() == {"chimerax_cmd": "", "prelaunch": "", "figure_template": ""}
    cb.save_settings({"chimerax_cmd": " chimerax ", "prelaunch": "module load chimerax\n", "ignored": 1})
    assert cb.load_settings() == {"chimerax_cmd": "chimerax", "prelaunch": "module load chimerax", "figure_template": ""}
    assert stat.S_IMODE(cb.SETTINGS_FILE.stat().st_mode) == 0o600
    assert stat.S_IMODE(cb.HOME_DIR.stat().st_mode) == 0o700


def test_settings_validation(home):
    for bad in ({"chimerax_cmd": "a\nb"}, {"chimerax_cmd": "x" * 501}, {"prelaunch": "y" * 2001}, {"prelaunch": 5},
                {"chimerax_cmd": "a\x00b"}):
        with pytest.raises(ValueError):
            cb.save_settings(bad)
    assert not cb.SETTINGS_FILE.exists()


def test_garbage_settings_file_reads_as_empty(home):
    cb.HOME_DIR.mkdir()
    cb.SETTINGS_FILE.write_text("[1, 2")
    assert cb.load_settings() == {"chimerax_cmd": "", "prelaunch": "", "figure_template": ""}
    cb.SETTINGS_FILE.write_text(json.dumps({"chimerax_cmd": 7, "prelaunch": ["x"]}))
    assert cb.load_settings() == {"chimerax_cmd": "", "prelaunch": "", "figure_template": ""}


def test_shell_line(home):
    line = cb._shell_line({"chimerax_cmd": "", "prelaunch": "", "figure_template": ""}, "--version")
    assert line == "exec '/opt/ChimeraX app/ChimeraX' --version"          # auto-detected path is quoted
    line = cb._shell_line({"chimerax_cmd": "chimerax --nogui", "prelaunch": "module load chimerax"}, "--version")
    assert line.splitlines() == ["module load chimerax", "exec chimerax --nogui --version"]


def test_no_chimerax_gives_a_clear_error(home, monkeypatch):
    monkeypatch.setattr(cb, "_auto_chimerax", lambda: None)
    with pytest.raises(ValueError, match="Settings"):
        cb._shell_line({"chimerax_cmd": "", "prelaunch": "", "figure_template": ""}, "x")


class _FakePopen:
    calls = []

    def __init__(self, args, **kw):
        self.args, self.kw = args, kw
        _FakePopen.calls.append(self)

    def poll(self):
        return None


def _map(tmp_path, name="a.mrc"):
    f = tmp_path / name
    f.write_bytes(b"x")
    return f


def test_first_click_starts_chimerax_with_listen_then_clicks_are_queued(home, monkeypatch):
    _FakePopen.calls.clear()
    monkeypatch.setattr(cb.subprocess, "Popen", _FakePopen)
    cb.save_settings({"chimerax_cmd": "chimerax", "prelaunch": "module load chimerax", "figure_template": ""})
    a, b = _map(home, "a.mrc"), _map(home, "b.mrc")

    msg = cb.open_files([a, b], tile=True)
    assert "started ChimeraX" in msg and len(_FakePopen.calls) == 1
    args = _FakePopen.calls[0].args
    assert args[:2] == ["bash", "-lc"] and args[2].startswith("module load chimerax\nexec chimerax ") and "instantmap" not in args[2]
    assert _FakePopen.calls[0].kw["start_new_session"] is True
    cxc = next((cb.HOME_DIR / "launch").glob("*.cxc")).read_text().splitlines()
    assert cxc == ['runscript "%s"' % cb.LISTENER_SCRIPT, 'open "%s"' % a.resolve(), 'open "%s"' % b.resolve(), "tile"]
    assert cb.LISTENER_SCRIPT.is_file()                              # the script the launch file runs really ships with the package

    # a second click while that ChimeraX is still coming up must NOT start another one: it is queued for its listener
    msg2 = cb.open_files([_map(home, "c.mrc")])
    assert "still starting" in msg2 and len(_FakePopen.calls) == 1
    (req,) = cb.QUEUE.glob("req-*")
    assert json.loads(req.read_text())["action"] == "open"

    # once the listener is alive the answer changes, still no new process
    (cb.QUEUE / "alive").touch()
    assert "sent to the running" in cb.open_files([_map(home, "d.mrc")]) and len(_FakePopen.calls) == 1


def test_a_dead_or_old_launch_does_not_block_a_new_start(home, monkeypatch):
    _FakePopen.calls.clear()
    monkeypatch.setattr(cb.subprocess, "Popen", _FakePopen)
    dead = types.SimpleNamespace(poll=lambda: 1)
    monkeypatch.setattr(cb, "_launched", (dead, 0))
    assert "started ChimeraX" in cb.open_files([_map(home)])
    assert len(_FakePopen.calls) == 1


def test_paths_with_quotes_or_wrong_type_are_refused(home, monkeypatch):
    monkeypatch.setattr(cb.subprocess, "Popen", _FakePopen)
    _FakePopen.calls.clear()
    with pytest.raises(ValueError):
        cb.open_files([_map(home, 'we"ird.mrc')])
    with pytest.raises(ValueError):
        cb.open_files([_map(home, "notes.txt")])
    assert not _FakePopen.calls


def test_figure_template_setting(tmp_path, monkeypatch):
    import pytest
    from reliontree import chimerax_bridge as B
    monkeypatch.setattr(B, "HOME_DIR", tmp_path)
    monkeypatch.setattr(B, "SETTINGS_FILE", tmp_path / "settings.json")
    assert B.load_settings()["figure_template"] == ""
    B.save_settings({"chimerax_cmd": "cx", "figure_template": "Mask overlay"})
    B.save_settings({"chimerax_cmd": "cx2"})                 # older page: key absent -> kept
    assert B.load_settings()["figure_template"] == "Mask overlay" and B.load_settings()["chimerax_cmd"] == "cx2"
    with pytest.raises(ValueError):
        B.save_settings({"figure_template": 'x"; shell ls'})


def test_home_dir_is_owner_only_after_open(tmp_path, monkeypatch):
    import os
    from reliontree import chimerax_bridge as B
    home = tmp_path / ".reliontree"
    home.mkdir(mode=0o755)
    home.chmod(0o755)
    monkeypatch.setattr(B, "HOME_DIR", home)
    monkeypatch.setattr(B, "QUEUE", home / "chimerax")
    monkeypatch.setattr(B, "listener_alive", lambda: True)
    m = home / "m.mrc"
    m.write_bytes(b"x")
    B.open_files([m])
    assert (home.stat().st_mode & 0o777) == 0o700 and ((home / "chimerax").stat().st_mode & 0o777) == 0o700
