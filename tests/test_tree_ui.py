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
    assert load_meta(tmp_path) == {"Class3D/job001": {"alias": "remove_junk_1", "status": "succeeded"},
                                   "Select/job002": {"alias": "", "status": "running"}}


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
