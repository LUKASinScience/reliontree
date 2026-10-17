"""FSC curves from postprocess.star / run_model.star; the 0.143 crossing."""
from reliontree.relion_fsc import crossing, fsc_curves, has_fsc

POST = """data_general

_rlnFinalResolution 4.0

data_fsc

loop_
_rlnSpectralOrigIndex #1
_rlnResolution #2
_rlnAngstromResolution #3
_rlnFourierShellCorrelationCorrected #4
_rlnFourierShellCorrelationUnmaskedMaps #5
_rlnFourierShellCorrelationMaskedMaps #6
_rlnCorrectedFourierShellCorrelationPhaseRandomizedMaskedMaps #7
0 0.000000 999.0 1.0 1.0 1.0 1.0
1 0.100000 10.0 0.9 0.8 0.95 0.01
2 0.200000 5.0 0.6 0.5 0.7 0.0
3 0.300000 3.333333 0.1 0.2 0.3 0.0
4 0.400000 2.5 0.0 0.1 0.0 0.0

data_guinier

loop_
_rlnResolutionSquared #1
_rlnLogAmplitudesOriginal #2
0.0 1.0
"""

MODEL = """data_model_general

_rlnReferenceDimension 64

data_model_classes

loop_
_rlnReferenceImage #1
_rlnClassDistribution #2
x.mrc 1.0

data_model_class_1

loop_
_rlnSpectralIndex #1
_rlnResolution #2
_rlnAngstromResolution #3
_rlnSsnrMap #4
_rlnGoldStandardFsc #5
0 0.0 999.0 1.0 1.0
1 0.1 10.0 2.0 0.8
2 0.2 5.0 0.5 0.3
3 0.3 3.33 0.1 0.05
"""


def test_crossing_interpolates():
    assert abs(crossing([0.1, 0.2, 0.3], [0.9, 0.6, 0.1]) - 1 / (0.2 + (0.6 - 0.143) / (0.6 - 0.1) * 0.1)) < 1e-9
    assert crossing([0.1, 0.2], [0.9, 0.8]) is None            # never drops below


def test_postprocess(tmp_path):
    (tmp_path / "postprocess.star").write_text(POST)
    assert has_fsc(tmp_path)
    r = fsc_curves(tmp_path)
    assert r["source"] == "postprocess.star" and r["x"][0] == 0.1        # the 0-frequency row is dropped
    labels = [c["label"] for c in r["curves"]]
    assert labels[0] == "corrected" and "masked maps" in labels and "phase-randomised" in labels
    assert 3.3 < r["resolution"] < 3.5                          # corrected: 0.6 at 0.2/A, 0.1 at 0.3/A -> 0.143 at ~0.291/A
    assert all(len(c["y"]) == len(r["x"]) for c in r["curves"])


def test_refine_gold_standard(tmp_path):
    (tmp_path / "run_model.star").write_text(MODEL)
    r = fsc_curves(tmp_path)
    assert r["source"] == "run_model.star" and [c["label"] for c in r["curves"]] == ["gold-standard"]
    assert 3.3 < r["resolution"] < 5.0


def test_nothing_there(tmp_path):
    assert fsc_curves(tmp_path) is None and not has_fsc(tmp_path)
    (tmp_path / "postprocess.star").write_text("data_general\n\n_rlnFinalResolution 4\n")
    assert fsc_curves(tmp_path) is None


PIPELINE = """data_pipeline_general

_rlnPipeLineJobCounter 3


data_pipeline_processes

loop_
_rlnPipeLineProcessName #1
_rlnPipeLineProcessAlias #2
_rlnPipeLineProcessTypeLabel #3
_rlnPipeLineProcessStatusLabel #4
Refine3D/job001/ None relion.refine3d Succeeded
PostProcess/job002/ None relion.postprocess Succeeded


data_pipeline_nodes

loop_
_rlnPipeLineNodeName #1
_rlnPipeLineNodeTypeLabel #2
_rlnPipeLineNodeTypeLabelDepth #3
Refine3D/job001/run_class001.mrc DensityMap.mrc.relion.refine3d 1
PostProcess/job002/postprocess.mrc DensityMap.mrc.relion.postprocess 1


data_pipeline_input_edges

loop_
_rlnPipeLineEdgeFromNode #1
_rlnPipeLineEdgeProcess #2
Refine3D/job001/run_class001.mrc PostProcess/job002/
"""


def test_page_carries_the_fsc(tmp_path):
    import json
    from reliontree import build_tree, render_html
    (tmp_path / "default_pipeline.star").write_text(PIPELINE)
    for j in ("Refine3D/job001", "PostProcess/job002"):
        (tmp_path / j).mkdir(parents=True)
        (tmp_path / j / "RELION_JOB_EXIT_SUCCESS").write_text("")
    (tmp_path / "PostProcess/job002/postprocess.star").write_text(POST)
    (tmp_path / "Refine3D/job001/run_model.star").write_text(MODEL)
    page = render_html(build_tree(tmp_path), title="t")
    i = page.index("const JOBS = ")
    jobs = json.JSONDecoder().raw_decode(page[i + len("const JOBS = "):])[0]
    assert jobs["PostProcess/job002"]["fsc"]["source"] == "postprocess.star"
    assert jobs["Refine3D/job001"]["fsc"]["source"] == "run_model.star"
    assert "function fscSection" in page
