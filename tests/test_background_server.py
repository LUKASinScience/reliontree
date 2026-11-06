"""reliontree can serve its view from a thread of another program (CryoSTAR-Base embeds it this way)."""
import socket
import urllib.request

import pytest

import reliontree


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_start_serve_stop(tmp_path):
    (tmp_path / "default_pipeline.star").write_text("data_pipeline_general\n\n_rlnPipeLineJobCounter 1\n")
    port = _free_port()
    srv = reliontree.start_background(tmp_path, port)
    try:
        assert srv.alive() and srv.url == "http://127.0.0.1:%d/" % port
        with pytest.raises(urllib.error.HTTPError) as e:                   # no login code, no cookie: nothing is served
            urllib.request.urlopen(srv.url, timeout=5)
        assert e.value.code == 403
        browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        assert browser.open(srv.server.login_url(), timeout=5).status == 200     # code -> cookie -> redirect -> served
        assert browser.open(srv.url, timeout=5).status == 200                    # the cookie alone is enough afterwards
        with pytest.raises(OSError):                       # the port is taken while it runs
            reliontree.start_background(tmp_path, port)
    finally:
        srv.stop()
    assert not srv.alive()
    reliontree.start_background(tmp_path, port).stop()     # and free again afterwards


def test_not_a_project(tmp_path):
    with pytest.raises(ValueError):
        reliontree.start_background(tmp_path, _free_port())
