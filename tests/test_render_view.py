"""Viewer stage 2 (refs across jobs, mask, colour), /render route, `reliontree render` with a fake Chrome. Synthetic data only."""
import argparse
import os
import stat
import sys
import urllib.error
import urllib.request

import pytest

from reliontree import cli, relion_render, relion_volume
from reliontree.render_html import _renders_of
from reliontree.view3d_page import render_view3d
from test_volume_view import _write_mrc


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setattr(relion_volume, "_CACHE_DIR", tmp_path / "cache")
    p = tmp_path / "proj"
    for j, f in (("Refine3D/job001", "run_class001.mrc"), ("Refine3D/job002", "run_class001.mrc"),
                 ("MaskCreate/job003", "mask.mrc"), ("LocalRes/job004", "relion_locres.mrc"), ("Class3D/job005", "run_it025_class001.mrc")):
        (p / j).mkdir(parents=True)
        _write_mrc(p / j / f, 12)
    (p / "default_pipeline.star").write_text("data_pipeline_general\n\n_rlnPipeLineJobCounter 6\n\n")
    return p


def test_view_request_refs(proj):
    q = {"job": ["Refine3D/job001"], "f": ["run_class001.mrc", "Refine3D/job002:run_class001.mrc"],
         "mask": ["MaskCreate/job003:mask.mrc"], "color": ["LocalRes/job004:relion_locres.mrc"]}
    with pytest.raises(ValueError):                                  # 4 distinct jobs
        cli._view_request(q, proj)
    del q["color"]
    job, maps, mask, color = cli._view_request(q, proj)
    assert (job, maps, mask, color) == ("Refine3D/job001", ["run_class001.mrc", "Refine3D/job002:run_class001.mrc"], "MaskCreate/job003:mask.mrc", None)
    assert cli._view_request({"f": ["Refine3D/job002:run_class001.mrc"]}, proj)[0] == "Refine3D/job002"   # job from the ref


@pytest.mark.parametrize("q", [
    {"job": ["Refine3D/job001"], "f": ["../job002/run_class001.mrc"]},
    {"job": ["Refine3D/job001"], "f": ["run_class001.mrc"], "mask": ["../../etc:passwd.mrc"]},
    {"job": ["Refine3D/job001"], "f": ["run_class001.mrc"], "mask": ["Refine3D/job099:mask.mrc"]},
    {"job": ["Refine3D/job001"], "f": ["run_class001.mrc"], "color": ["/etc/x.mrc"]},
    {"job": ["Refine3D/job001"], "f": ["Refine3D/job002:x.bild"]},
    {"job": ["Refine3D/job001"], "f": ["a/../../b:run_class001.mrc"]}])
def test_view_request_rejects(proj, q):
    with pytest.raises(ValueError):
        cli._view_request(q, proj)


def test_volume_from_second_job(proj):
    import gzip
    assert gzip.decompress(cli._volume({"job": ["Refine3D/job001"], "f": ["MaskCreate/job003:mask.mrc"], "detail": ["32"]}, proj))[:2] == b"\x0c\x00"


def test_page_embeds_stage2_and_render_default():
    page = render_view3d("Refine3D/job001", ["a.mrc", "Refine3D/job002:a.mrc"], "tok", mask="MaskCreate/job003:m.mrc",
                         color="LocalRes/job004:relion_locres.mrc", render="soft")
    for needle in ('"MaskCreate/job003:m.mrc"', '"LocalRes/job004:relion_locres.mrc"', 'RENDER_DEFAULT = "soft"', "difference", "chrome", "sdiff"):
        assert needle in page
    assert 'RENDER_DEFAULT = "auto"' in render_view3d("j", ["a.mrc"], "t", render="evil</script>")
    assert "null" in render_view3d("j", ["a.mrc"], "t")             # no mask -> JSON null


def test_render_png_route_validates(proj):
    d = proj / ".reliontree" / "renders"
    d.mkdir(parents=True)
    (d / "Refine3D_job001_x.png").write_bytes(b"\x89PNG")
    assert cli._render_png({"f": ["Refine3D_job001_x.png"]}, proj) == b"\x89PNG"
    for bad in ("../../default_pipeline.star", "x.txt", "nope.png", "a/b.png", ""):
        with pytest.raises(ValueError):
            cli._render_png({"f": [bad]}, proj)
    assert _renders_of(proj / "Refine3D" / "job001", "Refine3D/job001") == ["Refine3D_job001_x.png"]
    assert _renders_of(proj / "Refine3D" / "job002", "Refine3D/job002") == []


def _get(url, host=None):
    req = urllib.request.Request(url, headers={"Host": host} if host else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_routes_token_and_host(proj):
    import socket
    with socket.socket() as k:
        k.bind(("127.0.0.1", 0))
        port = k.getsockname()[1]
    bg = cli.start_background(proj, port=port)
    try:
        t, base = bg.server.page_token, bg.url
        (proj / ".reliontree" / "renders").mkdir(parents=True)
        (proj / ".reliontree" / "renders" / "a.png").write_bytes(b"\x89PNG")
        ok = base + "view3d?t=%s&job=Refine3D/job001&f=run_class001.mrc&mask=MaskCreate/job003:mask.mrc" % t
        assert _get(ok)[0] == 200 and b"MaskCreate/job003:mask.mrc" in _get(ok)[1]
        assert _get(ok.replace(t, "wrong"))[0] == 403
        assert _get(ok, host="evil.example:%d" % port)[0] == 403
        assert _get(base + "render?t=%s&f=a.png" % t) == (200, b"\x89PNG")
        assert _get(base + "render?f=a.png")[0] == 403
        assert _get(base + "render?t=%s&f=../default_pipeline.star" % t)[0] == 400
        assert _get(base + "view3d-state?t=%s&s=ready%%20gpu%%3Cb%%3E" % t)[0] == 200
        assert bg.server.view_state == "ready gpub"
        assert _get(base + "view3d?t=%s&job=Refine3D/job001&f=run_class001.mrc&mask=Refine3D/job077:m.mrc" % t)[0] == 400
    finally:
        bg.stop()


def test_out_name_and_cache(proj):
    n = relion_render.out_name("Refine3D/job001", ["run_class001.mrc"], 20, -30.5, 800, "auto")
    assert n == "Refine3D_job001_run_class001_rx20_rym30p5_s800_auto.png"
    assert n == relion_render.out_name("Refine3D/job001", ["run_class001.mrc"], 20, -30.5, 800, "auto")
    out = proj / "o.png"
    assert not relion_render.is_fresh(out, proj, "Refine3D/job001", ["run_class001.mrc"])
    out.write_bytes(b"x")
    os.utime(proj / "Refine3D/job001/run_class001.mrc", (1, 1))
    assert relion_render.is_fresh(out, proj, "Refine3D/job001", ["run_class001.mrc"])
    os.utime(out, (1, 1)); os.utime(proj / "Refine3D/job001/run_class001.mrc", (5, 5))
    assert not relion_render.is_fresh(out, proj, "Refine3D/job001", ["run_class001.mrc"])
    assert "Refine3D/job001" in relion_render.default_jobs(proj) and "MaskCreate/job003" not in relion_render.default_jobs(proj)


def _args(proj, out, chrome, **kw):
    d = dict(project=str(proj), job=["Refine3D/job001"], out=(str(out) if out else None), chrome=chrome, render="auto", size=64, rx=0.0, ry=10.0,
             level="auto", turntable=0, force=False)
    d.update(kw)
    return argparse.Namespace(**d)


FAKE = """#!{py}
import sys, re, urllib.request
a = sys.argv[1:]
out = [x for x in a if x.startswith("--screenshot=")][0].split("=", 1)[1]
url = a[-1]
soft = "--use-angle=swiftshader" in a
open(out, "wb").write(b"\\x89PNG fake " + (b"soft" if soft else b"gpu"))
tok = re.search(r"t=([^&]+)", url).group(1)
state = "failed" if (soft is False and "FAILGPU" in " ".join(a + [__import__("os").environ.get("FAKE_MODE", "")])) else "ready " + ("soft" if soft else "gpu")
urllib.request.urlopen(url.split("view3d")[0] + "view3d-state?t=" + tok + "&s=" + state.replace(" ", "%20"))
"""


@pytest.fixture
def fake_chrome(tmp_path):
    p = tmp_path / "fakechrome"
    p.write_text(FAKE.format(py=sys.executable))
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def test_cmd_render_writes_caches_turntable(proj, tmp_path, fake_chrome, capsys):
    out = tmp_path / "o"
    cli.cmd_render(_args(proj, out, fake_chrome))
    (png,) = out.glob("*.png")
    assert png.name == "Refine3D_job001_run_class001_rx0_ry10_s64_auto.png" and png.read_bytes().endswith(b"gpu")
    capsys.readouterr()
    cli.cmd_render(_args(proj, out, fake_chrome))                     # newer than the map: nothing redrawn
    assert "0 written, 1 up to date" in capsys.readouterr().out
    cli.cmd_render(_args(proj, out, fake_chrome, turntable=4, force=True))
    assert sorted(p.name.split("_ry")[1].split("_")[0] for p in out.glob("*.png")) == ["10", "100", "190", "280"]


def test_cmd_render_soft_and_default_dir(proj, fake_chrome, monkeypatch):
    cli.cmd_render(_args(proj, None, fake_chrome, render="soft"))
    (png,) = (proj / ".reliontree" / "renders").glob("*.png")
    assert png.read_bytes().endswith(b"soft")


def test_cmd_render_no_chrome_exits_2(proj, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(relion_render, "_NAMES", ())
    monkeypatch.setattr(relion_render, "_MAC", ())
    with pytest.raises(SystemExit) as e:
        cli.main(["render", str(proj), "--out", str(tmp_path / "o")])
    assert e.value.code == 2 and "no Chrome" in capsys.readouterr().err
    assert not (tmp_path / "o").exists()


def test_chrome_flags():
    soft = relion_render.chrome_cmd("c", "u", "o", 10, 10, True, "p")
    gpu = relion_render.chrome_cmd("c", "u", "o", 10, 10, False, "p")
    assert "--headless=new" in gpu and "--enable-unsafe-swiftshader" in soft and "--use-angle=swiftshader" in soft
    assert not any("swiftshader" in x for x in gpu) and any(x.startswith("--virtual-time-budget=") for x in gpu)


def test_ui_hooks_in_interactive_page(proj):
    from reliontree.relion_treebuild import build_tree
    from reliontree.render_html import render_html
    page = render_html(build_tree(proj), interactive=True, token="tok")
    for needle in ("openBrowserCompare", "view3dUrl", "ev.shiftKey", "compare maps in 3D (browser)", "/render?t="):
        assert needle in page
