import pytest
from pathlib import Path
from reliontree.relion_pipeline import load_meta
from reliontree.relion_treebuild import user_notes, find_main_path, route_edges, CARD_W

PIPE = '''data_pipeline_processes

loop_
_rlnPipeLineProcessName #1
_rlnPipeLineProcessAlias #2
_rlnPipeLineProcessTypeLabel #3
_rlnPipeLineProcessStatusLabel #4
Class3D/job001/ Class3D/remove_junk_1/ relion.class3d  Succeeded
Select/job002/       None relion.select.interactive  Running
'''


def test_alias_and_status(tmp_path):
    (tmp_path / "default_pipeline.star").write_text(PIPE)
    assert load_meta(tmp_path) == {"Class3D/job001": {"alias": "remove_junk_1", "status": "succeeded", "type": "relion.class3d"},
                                   "Select/job002": {"alias": "", "status": "running", "type": "relion.select.interactive"}}


def test_notes_drop_command_log(tmp_path):
    (tmp_path / "note.txt").write_text(" ++++ Executing new job on x\n ++++ with:\n`cmd` --o a\n ++++ \nmy note\n")
    assert user_notes(tmp_path) == "my note"


def test_main_path_and_dead_ends():
    ok = {j: {"state": "succeeded"} for j in ("A/job001", "Class3D/job002", "Refine3D/job003", "Refine3D/job004", "Class3D/job005")}
    stats = {j: {"resolution_angstrom": r} for j, r in
             {"A/job001": None, "Class3D/job002": None, "Refine3D/job003": 9.0, "Refine3D/job004": 12.0, "Class3D/job005": None}.items()}
    parents = {"A/job001": set(), "Class3D/job002": {"A/job001"}, "Refine3D/job003": {"Class3D/job002"},
               "Refine3D/job004": {"Refine3D/job003"}, "Class3D/job005": {"A/job001"}}
    latest, best, main, side = find_main_path(list(ok), parents, ok, stats)
    assert (latest, best) == ("Refine3D/job004", "Refine3D/job003")
    assert main == {"Refine3D/job004", "Refine3D/job003", "Class3D/job002", "A/job001"}
    assert side == {"Class3D/job005"}


def test_skip_edge_avoids_cards():
    layers = [["a"], ["b", "c"], ["d"]]
    pos = {"a": (0, 0), "b": (0, 100), "c": (220, 100), "d": (0, 200)}
    sizes = {j: (CARD_W, 60) for j in pos}
    tree = {"layers": layers, "parents": {"d": {"a"}}, "main": set()}
    (_, _, d, _, skip), = route_edges(tree, pos, sizes)[0]
    assert skip
    gx = float(d.split("H")[1].split()[0])
    assert not any(x - 6 <= gx <= x + CARD_W + 6 for x, y in (pos["b"], pos["c"]))


def test_mask_becomes_chip_not_card(tmp_path):
    from reliontree.relion_treebuild import build_tree, render_svg
    star = '''data_pipeline_processes

loop_
_rlnPipeLineProcessName #1
_rlnPipeLineProcessAlias #2
_rlnPipeLineProcessTypeLabel #3
_rlnPipeLineProcessStatusLabel #4
MaskCreate/job001/ None relion.maskcreate Succeeded
Refine3D/job002/ None relion.refine3d Succeeded

data_pipeline_input_edges

loop_
_rlnPipeLineEdgeFromNode #1
_rlnPipeLineEdgeProcess #2
MaskCreate/job001/mask.mrc Refine3D/job002/

data_pipeline_output_edges

loop_
_rlnPipeLineEdgeProcess #1
_rlnPipeLineEdgeToNode #2
MaskCreate/job001/ MaskCreate/job001/mask.mrc
'''
    (tmp_path / "default_pipeline.star").write_text(star)
    for j in ("MaskCreate/job001", "Refine3D/job002"):
        (tmp_path / j).mkdir(parents=True)
        (tmp_path / j / "RELION_JOB_EXIT_SUCCESS").write_text("")
    t = build_tree(tmp_path)
    assert t["chips"] == {"Refine3D/job002": ["MaskCreate/job001"]}
    assert t["layers"] == [["Refine3D/job002"]] and t["masks"] == ["MaskCreate/job001"]
    svg = render_svg(t, fit=True)
    assert 'class="mask-chip"' in svg and 'id="card-MaskCreate' not in svg and 'viewBox="0 0' in svg


def test_pipeline_status_beats_the_runout_guess_but_not_an_exit_marker(tmp_path):
    from reliontree.relion_treebuild import build_tree
    row = lambda job, status: "%s/ None relion.class3d %s\n" % (job, status)
    star = ('data_pipeline_processes\n\nloop_\n_rlnPipeLineProcessName #1\n_rlnPipeLineProcessAlias #2\n'
            '_rlnPipeLineProcessTypeLabel #3\n_rlnPipeLineProcessStatusLabel #4\n'
            + row("Class3D/job001", "Succeeded") + row("Class3D/job002", "Running") + row("Class3D/job003", "Succeeded"))
    (tmp_path / "default_pipeline.star").write_text(star)
    for job, files in (("job001", ["run.out"]),                            # deposited copy: no marker, pipeline says Succeeded
                       ("job002", ["run.out", "RELION_JOB_EXIT_SUCCESS"]),  # GUI closed before updating: the marker is newer
                       ("job003", ["run.out", "RELION_JOB_EXIT_FAILURE"])):  # marker says failed, pipeline stale
        d = tmp_path / "Class3D" / job
        d.mkdir(parents=True)
        for f in files:
            (d / f).write_text("")
    states = {j.split("/")[1]: a["state"] for j, a in build_tree(tmp_path)["artifacts"].items()}
    assert states == {"job001": "succeeded", "job002": "succeeded", "job003": "failed"}


def test_many_class_job_card_is_capped_and_missing_jobs_are_compact(tmp_path):
    from reliontree.relion_treebuild import MAX_CLASS_THUMBS, pick_classes
    shares = [0.001 * (i % 7) + 0.0001 * i for i in range(200)]
    tree = {"classes": {"Class2D/job1": [{"shares": shares}], "Class3D/job2": [{"shares": [0.5, 0.3, 0.2]}]},
            "chosen": {"Class2D/job1": {150: ["Select/job3"], 7: ["Select/job3"]}}}
    keep = pick_classes(tree, "Class2D/job1")
    assert len(keep) == MAX_CLASS_THUMBS and {150, 7} <= keep          # kept classes always shown, the rest by size
    assert pick_classes(tree, "Class3D/job2") is None                  # few classes: all of them
    big = max(range(1, 201), key=lambda n: shares[n - 1])
    assert big in keep


def test_refine3d_reports_one_half_and_exposes_the_total(tmp_path):
    from reliontree.relion_artifacts import job_stats
    def model(n_a, n_b):
        return ("data_model_groups\n\nloop_\n_rlnGroupNumber #1\n_rlnGroupName #2\n_rlnGroupNrParticles #3\n"
                "1 g1 %d\n2 g2 %d\n\ndata_model_general\n\n_rlnCurrentResolution 4.0\n" % (n_a, n_b))
    (tmp_path / "run_model.star").write_text(model(30, 34))              # merged model: one half only
    (tmp_path / "run_it003_half1_model.star").write_text(model(10, 20))  # older iteration, ignored
    (tmp_path / "run_it003_half2_model.star").write_text(model(10, 20))
    (tmp_path / "run_it004_half1_model.star").write_text(model(30, 34))
    (tmp_path / "run_it004_half2_model.star").write_text(model(31, 33))
    stats = job_stats(tmp_path)
    assert stats["n_particles"] == 64 and stats["n_particles_total"] == 128   # shown: one half (half-map convention); total kept for consumers


def test_relion3_pipeline_with_numeric_type_and_status_columns(tmp_path):
    """RELION 3.x wrote _rlnPipeLineProcessType/Status as numbers; the project showed zero jobs."""
    from reliontree.relion_treebuild import build_tree
    star = ('data_pipeline_processes\n\nloop_ \n_rlnPipeLineProcessName #1 \n_rlnPipeLineProcessAlias #2 \n'
            '_rlnPipeLineProcessType #3 \n_rlnPipeLineProcessStatus #4 \n'
            'Class2D/job008/ Class2D/LoG/ 8 2 \nSelect/job009/ None 7 3 \n')
    (tmp_path / "default_pipeline.star").write_text(star)
    for j in ("Class2D/job008", "Select/job009"):
        (tmp_path / j).mkdir(parents=True)
        (tmp_path / j / "run.out").write_text("")
    t = build_tree(tmp_path)
    assert set(t["artifacts"]) == {"Class2D/job008", "Select/job009"}
    assert t["alias"]["Class2D/job008"] == "LoG"
    assert {j: a["state"] for j, a in t["artifacts"].items()} == {"Class2D/job008": "succeeded", "Select/job009": "failed"}


def _pipeline(tmp_path, rows):
    star = ('data_pipeline_processes\n\nloop_\n_rlnPipeLineProcessName #1\n_rlnPipeLineProcessAlias #2\n'
            '_rlnPipeLineProcessTypeLabel #3\n_rlnPipeLineProcessStatusLabel #4\n' + "".join("%s/ None %s Succeeded\n" % r for r in rows))
    (tmp_path / "default_pipeline.star").write_text(star)
    for name, _ in rows:
        (tmp_path / name).mkdir(parents=True, exist_ok=True)


def test_project_type_is_detected_from_the_pipeline_and_job_star(tmp_path):
    from reliontree.relion_treebuild import build_tree
    sta, spa, mixed_flag, empty = tmp_path / "sta", tmp_path / "spa", tmp_path / "flag", tmp_path / "empty"
    for d in (sta, spa, mixed_flag, empty):
        d.mkdir()
    _pipeline(sta, [("Import/job001", "relion.importtomo"), ("Refine3D/job002", "relion.refine3d.tomo")])
    _pipeline(spa, [("MotionCorr/job001", "relion.motioncorr.own"), ("Class2D/job002", "relion.class2d")])
    _pipeline(mixed_flag, [("Class3D/job001", "relion.class3d")])          # only job.star says tomography
    (mixed_flag / "Class3D/job001/job.star").write_text("data_job\n\n_rlnJobTypeLabel relion.class3d\n_rlnJobIsTomo 1\n")
    _pipeline(empty, [("Select/job001", "relion.select.interactive")])
    got = {n: build_tree(d)["experiment"]["type"] for n, d in (("sta", sta), ("spa", spa), ("flag", mixed_flag), ("empty", empty))}
    assert got == {"sta": "sta", "spa": "spa", "flag": "sta", "empty": "unknown"}
    assert "refine3d.tomo" in build_tree(sta)["experiment"]["evidence"]


def test_project_type_badge_is_shown_and_escaped(tmp_path):
    from reliontree.relion_treebuild import build_tree
    from reliontree.render_html import render_html
    _pipeline(tmp_path, [("Refine3D/job001", "relion.refine3d.tomo")])
    page = render_html(build_tree(tmp_path))
    assert 'class="exp-badge"' in page and "STA · subtomogram averaging" in page and "relion.refine3d.tomo" in page


def test_analyze_needs_the_optional_companion_and_uses_it_when_present(tmp_path, monkeypatch, capsys):
    import sys
    import types
    from reliontree import cli
    _pipeline(tmp_path, [("Class3D/job001", "relion.class3d")])
    # not installed: a clear message and exit code 2, nothing else breaks
    monkeypatch.setitem(sys.modules, "relion_origin", None)
    monkeypatch.setitem(sys.modules, "relion_origin.annotations", None)
    with pytest.raises(SystemExit) as e:
        cli.main(["analyze", str(tmp_path)])
    assert e.value.code == 2 and "relion-origin" in capsys.readouterr().err
    # installed: findings land in the annotation file the view reads
    written = {}
    fake = types.ModuleType("relion_origin.annotations")
    fake.annotate_project = lambda project: ({"Class3D/job001": [{"label": "views: 50% of sphere sparse", "level": "warn"}]}, [])
    fake.write_annotations = lambda project, tool, notes: written.update(tool=tool, notes=notes) or Path(project) / "x.json"
    monkeypatch.setitem(sys.modules, "relion_origin", types.ModuleType("relion_origin"))
    monkeypatch.setitem(sys.modules, "relion_origin.annotations", fake)
    cli.main(["analyze", str(tmp_path)])
    assert written["tool"] == "relion-origin" and "Class3D/job001" in written["notes"]


def test_every_subcommand_is_reachable_from_the_command_line():
    """`reliontree plan` and `analyze` were once treated as project folders (the zero-config `reliontree <path>`
    shortcut) because a hand-kept command list missed them."""
    from reliontree import cli
    names = cli._build_parser().subcommand_names
    assert {"tree", "table", "methods", "diff", "why", "overlap", "watch", "plan", "analyze"} <= names
    for name in sorted(names):
        with pytest.raises(SystemExit) as e:
            cli.main([name, "--help"])
        assert e.value.code == 0, name


def test_unknown_word_is_an_error_not_a_server(capsys):
    from reliontree import cli
    with pytest.raises(SystemExit) as e:
        cli.main(["analyse"])
    assert e.value.code == 2 and "neither a command nor an existing directory" in capsys.readouterr().err
