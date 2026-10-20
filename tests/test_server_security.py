"""The watch server's settings / open-3d routes can lead to a shell command, so they must refuse anything that is not our own page:
no token, wrong token, foreign Host (DNS rebinding) or foreign Origin (cross-site form) -> 403. Real server, real HTTP."""
import http.client
import json
import os
import re
import socket
import subprocess
import sys
import time

import pytest


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    root = tmp_path_factory.mktemp("srv")
    proj = root / "proj"
    proj.mkdir()
    (proj / "default_pipeline.star").write_text("data_pipeline_general\n_rlnPipeLineJobCounter 1\n")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    env = dict(os.environ, HOME=str(root))
    errlog = root / "server.err"
    proc = subprocess.Popen([sys.executable, "-c", "import sys; from reliontree.cli import main; main(sys.argv[1:])",
                             "watch", str(proj), "--port", str(port), "--no-open"],
                            env=env, stdout=subprocess.DEVNULL, stderr=open(errlog, "w"))
    deadline = time.time() + 90            # a loaded CI runner needs far longer than a laptop to start Python
    while True:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            if proc.poll() is not None or time.time() > deadline:
                state = "exited with %s" % proc.returncode if proc.poll() is not None else "still not listening after 90 s"
                proc.kill()
                pytest.fail("server did not start (%s): %s" % (state, errlog.read_text()[-1500:]))
            time.sleep(0.2)
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/")
    page = conn.getresponse().read().decode()
    token = re.search(r'const TOKEN = "([^"]+)"', page).group(1)
    yield {"port": port, "token": token, "home": root, "page": page}
    proc.kill()


def call(server, method, path, headers=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", server["port"])
    h = {"Host": "127.0.0.1:%d" % server["port"]}
    h.update(headers or {})
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read().decode()
    try:
        return r.status, json.loads(data)
    except ValueError:
        return r.status, data


def test_page_embeds_token_and_settings_ui(server):
    assert 'id="settings"' in server["page"] and "openSettings()" in server["page"] and "chip3d" in server["page"]


def test_get_routes_need_the_token(server):
    t = server["token"]
    assert call(server, "GET", "/settings")[0] == 403
    assert call(server, "GET", "/settings?t=wrong")[0] == 403
    assert call(server, "GET", "/open-3d?job=Class3D/job001&f=a.mrc")[0] == 403
    assert call(server, "GET", "/settings-check")[0] == 403
    status, data = call(server, "GET", "/settings?t=" + t)
    assert status == 200 and data["settings"] == {"chimerax_cmd": "", "prelaunch": "", "figure_template": ""}


def test_foreign_host_and_origin_are_refused_even_with_the_token(server):
    t = server["token"]
    assert call(server, "GET", "/settings?t=" + t, {"Host": "evil.example:80"})[0] == 403          # DNS rebinding
    assert call(server, "GET", "/settings?t=" + t, {"Origin": "http://evil.example"})[0] == 403    # cross-site
    body = json.dumps({"t": t, "chimerax_cmd": "touch /tmp/pwned", "prelaunch": ""})
    assert call(server, "POST", "/settings", {"Content-Type": "application/json", "Origin": "http://evil.example"}, body)[0] == 403
    assert call(server, "POST", "/settings", {"Content-Type": "application/json", "Host": "evil.example"}, body)[0] == 403


def test_post_settings(server):
    t = server["token"]
    ok = {"Content-Type": "application/json", "Origin": "http://127.0.0.1:%d" % server["port"]}
    assert call(server, "POST", "/settings", ok, json.dumps({"chimerax_cmd": "x"}))[0] == 403          # no token
    assert call(server, "POST", "/settings", {}, json.dumps({"t": t}))[0] == 400                          # not JSON content type
    assert call(server, "POST", "/settings", ok, "not json")[0] == 400
    status, data = call(server, "POST", "/settings", ok, json.dumps({"t": t, "chimerax_cmd": "chimerax", "prelaunch": "module load chimerax"}))
    assert status == 200 and data["settings"]["prelaunch"] == "module load chimerax"
    saved = json.loads((server["home"] / ".reliontree" / "settings.json").read_text())
    assert saved == {"chimerax_cmd": "chimerax", "prelaunch": "module load chimerax", "figure_template": ""}
    status, data = call(server, "POST", "/settings", ok, json.dumps({"t": t, "chimerax_cmd": "a\nb"}))
    assert status == 400 and "single line" in data["error"]
    assert call(server, "POST", "/other", ok, "{}")[0] == 404


def test_every_route_checks_host_and_origin(server):
    evil = {"Host": "evil.example:80"}
    for path in ("/", "/class-thumbs?job=Class2D/job001&it=1", "/overlap?a=Class2D/job001&b=Class2D/job002", "/orientation?job=Class3D/job001"):
        assert call(server, "GET", path, evil)[0] == 403, path
        assert call(server, "GET", path, {"Origin": "http://evil.example"})[0] == 403, path
    assert call(server, "GET", "/")[0] == 200


def test_open_and_browse_need_the_token(server):
    t, proj = server["token"], str(server["home"] / "proj")
    for q in ("open=" + proj, "browse=" + str(server["home"])):
        assert call(server, "GET", "/?" + q)[0] == 403                                   # cross-site <img>: no token
        assert call(server, "GET", "/?%s&t=wrong" % q)[0] == 403
        assert call(server, "GET", "/?%s&t=%s" % (q, t), {"Host": "evil.example"})[0] == 403
    assert call(server, "GET", "/?open=%s&t=%s" % (proj, t))[0] == 302
    status, page = call(server, "GET", "/?browse=%s&t=%s" % (server["home"], t))
    assert status == 200 and "&amp;t=" + t in page            # page links carry the token
