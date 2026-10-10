import json

from reliontree.relion_annotations import load_annotations


def _write(project, tool, data):
    d = project / ".reliontree" / "annotations"
    d.mkdir(parents=True, exist_ok=True)
    (d / (tool + ".json")).write_text(data if isinstance(data, str) else json.dumps(data))


def test_load_merges_tools_sorts_by_severity_and_sanitises(tmp_path):
    _write(tmp_path, "origin", {"Class3D/job004": [{"label": "fine", "level": "good"},
                                                   {"label": "x" * 200, "level": "warn", "detail": "d" * 900},
                                                   {"label": "odd level", "level": "purple"}, {"nolabel": 1}, "junk"]})
    _write(tmp_path, "copilot", {"Class3D/job004": [{"label": "next: more classes", "level": "info"}], "Refine3D/job9": "not a list"})
    _write(tmp_path, "broken", "{ not json")
    got = load_annotations(tmp_path)
    assert list(got) == ["Class3D/job004"]
    a = got["Class3D/job004"]
    assert [x["level"] for x in a] == ["warn", "info", "info", "good"]            # severity order, bad level -> info
    assert len(a[0]["label"]) == 48 and len(a[0]["detail"]) == 400 and a[0]["source"] == "origin"


def test_no_directory_means_no_annotations(tmp_path):
    assert load_annotations(tmp_path) == {}


def test_annotations_reach_the_svg_and_html(tmp_path):
    from reliontree.relion_treebuild import build_tree, render_svg
    from reliontree.render_html import render_html
    star = ('data_pipeline_processes\n\nloop_\n_rlnPipeLineProcessName #1\n_rlnPipeLineProcessAlias #2\n'
            '_rlnPipeLineProcessTypeLabel #3\n_rlnPipeLineProcessStatusLabel #4\nClass3D/job001/ None relion.class3d Succeeded\n')
    (tmp_path / "default_pipeline.star").write_text(star)
    (tmp_path / "Class3D" / "job001").mkdir(parents=True)
    _write(tmp_path, "origin", {"Class3D/job001": [{"label": "<b>8% flagged</b>", "level": "warn", "detail": "<script>x</script>"}],
                                "Class3D/ghost": [{"label": "not in tree"}]})
    t = build_tree(tmp_path)
    assert list(t["annotations"]) == ["Class3D/job001"]
    svg = render_svg(t)
    assert 'class="anno"' in svg and "<b>" not in svg and "&lt;b&gt;8% flagged" in svg
    _write(tmp_path, "evil", {"Class3D/job001": [{"label": "ok", "detail": "</script><img src=x onerror=alert(1)>"}]})
    page = render_html(build_tree(tmp_path))
    assert "</script><img" not in page and "<\\/script><img" in page   # cannot break out of the embedded JSON
