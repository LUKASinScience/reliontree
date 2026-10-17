"""/open-3d takes file basenames of one job, builds the paths itself and refuses anything else."""
import json

from reliontree import chimerax_bridge, cli


def _project(tmp_path):
    job = tmp_path / "proj" / "Class3D" / "job001"
    job.mkdir(parents=True)
    for n in ("run_it025_class001.mrc", "run_it025_class002.mrc", "run_class001_angdist.bild"):
        (job / n).write_bytes(b"x")
    return tmp_path / "proj"


def test_open_3d_queues_validated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(chimerax_bridge, "QUEUE", tmp_path / "q")
    monkeypatch.setattr(chimerax_bridge, "listener_alive", lambda: True)
    proj = _project(tmp_path)

    ok = cli._open_3d({"job": ["Class3D/job001"], "f": ["run_it025_class001.mrc", "run_it025_class002.mrc"], "tile": ["1"]}, proj)
    assert "ok" in ok
    (req,) = (tmp_path / "q").glob("req-*")
    data = json.loads(req.read_text())
    assert data["action"] == "tile" and len(data["paths"]) == 2

    assert "ok" in cli._open_3d({"job": ["Class3D/job001"], "f": ["run_class001_angdist.bild"]}, proj)


def test_open_3d_rejects_escapes_and_junk(tmp_path, monkeypatch):
    monkeypatch.setattr(chimerax_bridge, "QUEUE", tmp_path / "q")
    monkeypatch.setattr(chimerax_bridge, "listener_alive", lambda: True)
    proj = _project(tmp_path)
    for q in ({"job": ["../../etc"], "f": ["run_it025_class001.mrc"]},         # job id escape
              {"job": ["Class3D/job001"], "f": ["../../x.mrc"]},               # path in file name
              {"job": ["Class3D/job001"], "f": ["run_it026_class001.mrc"]},    # missing file
              {"job": ["Class3D/job001"], "f": ["notes.txt"]},                 # wrong type
              {"job": ["Class3D/job001"], "f": []},                            # nothing asked
              {"job": ["Class3D/job001"]}):
        assert "error" in cli._open_3d(q, proj), q
    assert not list((tmp_path / "q").glob("req-*"))
