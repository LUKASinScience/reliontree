"""Angular distribution from the particle table when RELION wrote no angdist.bild."""
import math

from reliontree.relion_orientation import has_orientation, job_orientation, orientation_from_particles

STAR = """data_optics

loop_
_rlnOpticsGroup #1
1

data_particles

loop_
_rlnAngleRot #1
_rlnAngleTilt #2
_rlnClassNumber #3
{rows}
"""


def _write(tmp_path, angles):
    rows = "\n".join("%g %g %d" % a for a in angles)
    (tmp_path / "run_data.star").write_text(STAR.format(rows=rows))


def test_gap_is_visible(tmp_path):
    # particles at every 12 degrees of rot, tilt 60..120 only: nothing near the poles
    _write(tmp_path, [(r, t, 1) for r in range(0, 360, 12) for t in range(60, 121, 12) for _ in range(3)])
    d = job_orientation(tmp_path)
    assert d and d["source"].startswith("run_data.star") and has_orientation(tmp_path)
    zs = [b[2] for b in d["bins"]]
    assert max(abs(z) for z in zs) < math.cos(math.radians(55))      # no pole bin
    assert max(b[3] for b in d["bins"]) == 1.0


def test_class_filter_and_missing_columns(tmp_path):
    _write(tmp_path, [(r, t, 1 if t < 90 else 2) for r in range(0, 360, 12) for t in range(6, 180, 12)])
    up = orientation_from_particles(tmp_path / "run_data.star", class_number=1)
    assert up and all(b[2] > 0 for b in up)
    (tmp_path / "run_data.star").write_text("data_particles\n\nloop_\n_rlnCoordinateX #1\n1.0\n2.0\n")
    assert job_orientation(tmp_path) is None


def test_too_few_particles(tmp_path):
    _write(tmp_path, [(10, 20, 1), (20, 30, 1)])
    assert job_orientation(tmp_path) is None
