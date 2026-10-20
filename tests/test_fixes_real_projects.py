"""Regressions found by running reliontree on two real projects (synthetic fixtures with the same pattern)."""
from reliontree.relion_artifacts import scan_job_artifacts
from reliontree.relion_pipeline import load_pipeline
from reliontree.relion_treebuild import find_main_path

HEAD = ("data_pipeline_processes\n\nloop_\n_rlnPipeLineProcessName #1\n_rlnPipeLineProcessAlias #2\n"
        "_rlnPipeLineProcessTypeLabel #3\n_rlnPipeLineProcessStatusLabel #4\n")


def star(procs, edges):
    """edges: [(from_node, process, to_node_of_process_or_None)]"""
    s = HEAD + "".join("%s/ None relion.x Succeeded\n" % p for p in procs)
    s += "\ndata_pipeline_input_edges\n\nloop_\n_rlnPipeLineEdgeFromNode #1\n_rlnPipeLineEdgeProcess #2\n"
    s += "".join("%s %s/\n" % (n, p) for n, p, _ in edges)
    s += "\ndata_pipeline_output_edges\n\nloop_\n_rlnPipeLineEdgeProcess #1\n_rlnPipeLineEdgeToNode #2\n"
    s += "".join("%s/ %s/out.mrc\n" % (p, p) for p in procs)
    return s


def test_main_pipeline_beats_contradicting_job_snapshot(tmp_path):
    (tmp_path / "default_pipeline.star").write_text(
        star(["Class3D/job041", "Class3D/job043", "Refine3D/job045"], [("Class3D/job043/out.mrc", "Refine3D/job045", None)]))
    d = tmp_path / "Class3D" / "job043"
    d.mkdir(parents=True)
    # old snapshot: Refine3D/job045 still read job041, and it knows a job (job099) the main pipeline lacks
    (d / "default_pipeline.star").write_text(
        star(["Class3D/job041", "Refine3D/job045", "Class3D/job099"],
             [("Class3D/job041/out.mrc", "Refine3D/job045", None), ("Class3D/job041/out.mrc", "Class3D/job099", None)]))
    procs, node_to_prod, proc_to_in = load_pipeline(tmp_path)
    assert proc_to_in["Refine3D/job045"] == {"Class3D/job043/out.mrc"}   # snapshot edge ignored
    assert "Class3D/job099" in procs and proc_to_in["Class3D/job099"] == {"Class3D/job041/out.mrc"}  # extra job still found


def test_latest_map_is_highest_iteration_numerically(tmp_path):
    for n in ("run_it023_class001.mrc", "run_it040_class001.mrc", "run_it100_class002.mrc", "run_it009_class001.mrc"):
        (tmp_path / n).write_bytes(b"x")
    assert scan_job_artifacts(tmp_path)["latest_map"].name == "run_it100_class002.mrc"
    (tmp_path / "run_class001.mrc").write_bytes(b"x")                      # final without iteration beats all
    assert scan_job_artifacts(tmp_path)["latest_map"].name == "run_class001.mrc"


def test_best_resolution_tie_breaks_by_fsc_then_newest_job():
    jobs = ["Refine3D/job010", "Refine3D/job020", "Refine3D/job030"]
    ok = {j: {"state": "succeeded"} for j in jobs}
    stats = {j: {"resolution_angstrom": 28.7456} for j in jobs}
    parents = {j: set() for j in jobs}
    cross = {"Refine3D/job010": 27.0, "Refine3D/job020": 25.5, "Refine3D/job030": None}
    assert find_main_path(jobs, parents, ok, stats, cross.get)[1] == "Refine3D/job020"
    assert find_main_path(jobs, parents, ok, stats)[1] == "Refine3D/job030"   # no FSC: newest job


def test_class_slots_follow_the_model_not_leftover_files(tmp_path):
    from reliontree.relion_artifacts import list_class_maps
    for c in (1, 2, 3, 4):                                    # an earlier 4-class run left its early maps behind
        (tmp_path / ("run_it005_class%03d.mrc" % c)).write_bytes(b"x")
    for c in (1, 2):
        (tmp_path / ("run_it040_class%03d.mrc" % c)).write_bytes(b"x")
    (tmp_path / "run_it040_model.star").write_text("data_model_general\n\n_rlnNrClasses 2\n_rlnCurrentResolution 8.0\n")
    assert [p.name for p in list_class_maps(tmp_path)] == ["run_it040_class001.mrc", "run_it040_class002.mrc"]


def test_missing_card_chip_does_not_overlap_the_state_text(tmp_path):
    import re
    from reliontree.relion_treebuild import build_tree, render_svg, CHIP_H
    (tmp_path / "default_pipeline.star").write_text(
        HEAD.replace("relion.x", "relion.x") + "MaskCreate/job001/ None relion.maskcreate Succeeded\nRefine3D/job002/ None relion.refine3d Succeeded\n"
        "\ndata_pipeline_input_edges\n\nloop_\n_rlnPipeLineEdgeFromNode #1\n_rlnPipeLineEdgeProcess #2\n"
        "MaskCreate/job001/mask.mrc Refine3D/job002/\n\ndata_pipeline_output_edges\n\nloop_\n_rlnPipeLineEdgeProcess #1\n"
        "_rlnPipeLineEdgeToNode #2\nMaskCreate/job001/ MaskCreate/job001/mask.mrc\n")
    (tmp_path / "MaskCreate" / "job001").mkdir(parents=True)          # Refine3D/job002 stays missing on disk
    svg = render_svg(build_tree(tmp_path))
    card_y, card_h = map(float, re.search(r'id="card-Refine3D/job002"[^>]*data-y="([\d.]+)" data-w="\d+" data-h="(\d+)"', svg).groups())
    state_y = float(re.search(r'y="([\d.]+)" fill="[^"]+">\[missing\]', svg).group(1))
    chip_y = float(re.search(r'class="mask-chip".*?<rect x="[\d.]+" y="([\d.]+)"', svg, re.S).group(1))
    assert chip_y > state_y                                              # chip row sits below the "[missing]" line
    assert chip_y + CHIP_H - 8 <= card_y + card_h                        # and inside the card
