import math

from reliontree.relion_orientation import job_orientation, parse_bild


def _bild(dirs_and_counts, centre=(50.0, 60.0, 70.0), radius=20.0):
    lines = []
    for (x, y, z), n in dirs_and_counts:
        norm = math.sqrt(x * x + y * y + z * z)
        ux, uy, uz = x / norm, y / norm, z / norm
        s = [centre[0] + radius * ux, centre[1] + radius * uy, centre[2] + radius * uz]
        e = [s[0] + n * ux, s[1] + n * uy, s[2] + n * uz]
        lines += [".color 0 0 1", ".cylinder %g %g %g %g %g %g 2.3" % (*s, *e)]
    return "\n".join(lines)


DIRS = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1), (1, 1, 1), (-1, -1, 1)]


def test_parse_bild_recovers_directions_although_the_centre_is_not_given():
    bins = parse_bild(_bild([(d, 1 + i) for i, d in enumerate(DIRS)]))
    assert len(bins) == 8
    assert bins[0][:3] == (1.0, 0.0, 0.0) or all(abs(a - b) < 1e-4 for a, b in zip(bins[0][:3], (1.0, 0.0, 0.0)))
    assert max(b[3] for b in bins) == 1.0 and abs(bins[0][3] - 1 / 8) < 1e-4          # weights relative to the longest cylinder
    z = [b for b in bins if abs(b[2] - 1.0) < 1e-4][0]
    assert abs(z[3] - 5 / 8) < 1e-4


def test_one_sided_directions_do_not_bias_the_centre():
    hemi = [((x, y, abs(z) + 0.5), 3) for (x, y, z) in DIRS]                         # all on one side of the centre
    bins = parse_bild(_bild(hemi))
    for (d, _), b in zip(hemi, bins):
        n = math.sqrt(sum(v * v for v in d))
        assert all(abs(u / n - v) < 1e-4 for u, v in zip(d, b[:3]))


def test_job_orientation_picks_final_file_class_and_ignores_junk(tmp_path):
    (tmp_path / "run_it001_half1_class001_angdist.bild").write_text(_bild([(d, 1) for d in DIRS[:6]]))
    (tmp_path / "run_class001_angdist.bild").write_text(_bild([(d, 2) for d in DIRS]))
    (tmp_path / "run_it003_class002_angdist.bild").write_text(_bild([(d, 1) for d in DIRS[:5]]))
    (tmp_path / "other.bild").write_text("nonsense")
    got = job_orientation(tmp_path)
    assert got["classes"] == [1, 2] and got["class"] == 1 and got["source"] == "run_class001_angdist.bild" and len(got["bins"]) == 8
    assert job_orientation(tmp_path, 2)["source"] == "run_it003_class002_angdist.bild"
    assert job_orientation(tmp_path / "missing") is None
    assert parse_bild(".cylinder 1 2 3") == []
