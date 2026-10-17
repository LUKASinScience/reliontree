import importlib.util
import json
import stat
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("chx_run", Path(__file__).parent.parent / "contrib" / "chx_run.py")
cr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cr)


@pytest.fixture
def d(tmp_path):
    (tmp_path / "m.pdb").write_text("END\n")
    return [tmp_path.resolve()]


@pytest.mark.parametrize("cmd", ["runscript x.py", "shell ls", "open 4hhb", "open /etc/passwd", "close #1; shell ls",
                                 "chopchop disulfides #1\nshell ls", "chopchop pisa a.xml #1", "instantmap listen",
                                 "chopchop disulfides #1 jsonFile /tmp/x", "open /x/m.pdb format pdb", "", "instantmap tree /etc", "instantmap table /tmp save /etc/x", "figurestyle saveImage a /etc/x.png"])
def test_refused(cmd, d):
    with pytest.raises(cr.Refused):
        cr.check(cmd, d)


def test_allowed(d):
    p = str(d[0] / "m.pdb")
    assert cr.check("open " + p, d) == "open " + p
    assert cr.check("chopchop disulfides #1 maxDist 2.2", d)
    with pytest.raises(cr.Refused):
        cr.check("open " + p, [Path("/nonexistent")])


def test_fake_chimerax_returns_json(d, tmp_path):
    fake = tmp_path / "fake"
    fake.write_text('#!%s\nimport sys, re, json\nc = sys.argv[sys.argv.index("--cmd")+1]\n'
                    'f = re.search(r"jsonFile (\\S+)", c).group(1)\njson.dump({"pairs": []}, open(f, "w"))\nprint("hi")\n' % sys.executable)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    r = cr.run(["chopchop disulfides #1"], chimerax=str(fake), allow_dirs=d)
    assert r["ok"] and r["results"]["chopchop disulfides #1"] == {"pairs": []}
