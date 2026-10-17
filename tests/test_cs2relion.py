"""CryoSPARC -> RELION helper: validator, safe extension fix, external-tool call."""
import importlib.util
import stat
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("cs2relion", Path(__file__).parent.parent / "contrib" / "cryosparc" / "cs2relion.py")
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)

GOOD = """data_optics

loop_
_rlnOpticsGroup #1
_rlnImagePixelSize #2
_rlnVoltage #3
_rlnSphericalAberration #4
_rlnAmplitudeContrast #5
1 1.05 300 2.7 0.1

data_particles

loop_
_rlnImageName #1
_rlnMicrographName #2
_rlnOpticsGroup #3
_rlnAngleRot #4
_rlnAngleTilt #5
_rlnAnglePsi #6
{rows}
"""


def star(tmp_path, rows, name="p.star"):
    p = tmp_path / name
    p.write_text(GOOD.format(rows="\n".join(rows)))
    return p


def levels(findings):
    return [(f["level"], f["what"]) for f in findings]


def test_good_file(tmp_path):
    (tmp_path / "Ext").mkdir()
    (tmp_path / "Ext/a.mrcs").write_bytes(b"x")
    f = cs.validate(star(tmp_path, ["1@Ext/a.mrcs mic_doseweighted.mrc 1 0 0 0"]), tmp_path)
    assert not [x for x in f if x["level"] == "error"], f


def test_findings(tmp_path):
    rows = ["1@Ext/a.mrc m1.mrc 1 0 0 0", "2@Ext/a.mrcss m1.mrc 2 0 0 0", "garbage m1.mrc 1 0 0 0"]
    f = levels(cs.validate(star(tmp_path, rows), tmp_path))
    text = " | ".join(w for _, w in f)
    assert "do not end in .mrcs" in text and ".mrcss" in text and "not of the form" in text
    assert "optics group(s) ['2']" in text and "not found under" in text
    old = tmp_path / "old.star"
    old.write_text("data_\n\nloop_\n_rlnImageName #1\n1@a.mrcs\n")
    assert "no data_optics" in " ".join(w for _, w in levels(cs.validate(old)))
    odd = GOOD.replace("1.05", "105")
    (tmp_path / "odd.star").write_text(odd.format(rows="1@a.mrcs m 1 0 0 0"))
    assert any(lv == "warn" and "pixel size" in w for lv, w in levels(cs.validate(tmp_path / "odd.star")))


def test_fix_ext_touches_only_the_image_name(tmp_path):
    (tmp_path / "Ext").mkdir()
    (tmp_path / "Ext/a.mrc").write_bytes(b"stack")
    p = star(tmp_path, ["1@Ext/a.mrc Ext/mic.mrcs 1 0 0 0", "2@Ext/a.mrc Ext/mic.mrcs 1 0 0 0"])
    assert cs.fix_extensions(p, tmp_path) == 1
    text = p.read_text()
    assert "1@Ext/a.mrcs Ext/mic.mrcs" in text and ".mrcss" not in text            # micrograph column untouched
    assert (tmp_path / "Ext/a.mrcs").is_symlink() and (tmp_path / "Ext/a.mrcs").read_bytes() == b"stack"
    assert "1@Ext/a.mrc Ext/mic.mrcs" in Path(str(p) + ".orig").read_text()        # original kept untouched
    assert not [x for x in cs.validate(p, tmp_path) if x["level"] == "error"]
    assert cs.fix_extensions(p, tmp_path) == 0                                    # idempotent
    with pytest.raises(ValueError):
        cs.fix_extensions(star(tmp_path, ["1@Ext/none.mrc m 1 0 0 0"], "q.star"), tmp_path)


def test_convert_calls_external_tool(tmp_path):
    fake = tmp_path / "csparc2star.py"
    fake.write_text("import sys\nargs = sys.argv[1:]\nassert '--inverty' in args\nopen(args[-1], 'w').write(%r.format(rows='1@Ext/a.mrcs m 1 0 0 0'))\n" % GOOD)
    out = cs.convert(tmp_path / "x.cs", tmp_path / "o.star", [tmp_path / "t.cs"], csparc2star=str(fake))
    assert out.is_file() and "data_optics" in out.read_text()
    with pytest.raises(FileNotFoundError):
        cs.find_csparc2star(str(tmp_path / "nope.py"))
    bad = tmp_path / "bad.py"
    bad.write_text("import sys\nsys.exit(3)\n")
    with pytest.raises(RuntimeError):
        cs.convert(tmp_path / "x.cs", tmp_path / "o2.star", csparc2star=str(bad))


def test_cli_exit_codes(tmp_path, capsys):
    p = star(tmp_path, ["1@Ext/a.mrc m 1 0 0 0"])
    assert cs.main(["validate", str(p)]) == 1
    assert cs.main(["validate", str(tmp_path / "missing.star")]) == 1
    assert cs.main(["fix-ext", str(p), "--project", str(tmp_path)]) == 2          # stack not found -> tool problem
