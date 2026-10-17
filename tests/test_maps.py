"""relion_maps: which maps a job directory holds, grouped and ranked for the 3D buttons."""
from reliontree.relion_maps import card_maps, list_job_maps


def _job(tmp_path, *names):
    d = tmp_path / "job"
    d.mkdir()
    for n in names:
        (d / n).write_bytes(b"x")
    return d


def labels(maps):
    return [m["label"] for m in maps]


def test_refine3d_final_and_last_half_maps_only(tmp_path):
    d = _job(tmp_path, "run_class001.mrc", "run_half1_class001_unfil.mrc", "run_half2_class001_unfil.mrc",
             "run_it000_half1_class001.mrc", "run_it000_half2_class001.mrc", "run_it005_half1_class001.mrc",
             "run_it005_half2_class001.mrc", "run_data.star", "particles.mrcs")
    maps = list_job_maps(d)
    assert labels(maps) == ["Final map", "Half maps"]               # per-iteration halves are not buttons; .mrcs is no map
    assert maps[1]["tile"] is True and len(maps[1]["files"]) == 2
    assert [m["label"] for m in card_maps(maps)] == ["Final map"]


def test_iteration_halves_when_no_final_halves(tmp_path):
    maps = list_job_maps(_job(tmp_path, "run_it001_half1_class001.mrc", "run_it003_half1_class001.mrc",
                              "run_it003_half2_class001.mrc"))
    assert labels(maps) == ["Half maps (it 3)"] and len(maps[0]["files"]) == 2


def test_class3d_all_classes_tiled(tmp_path):
    maps = list_job_maps(_job(tmp_path, *["run_it%03d_class%03d.mrc" % (i, c) for i in (24, 25) for c in (1, 2, 3)]))
    assert labels(maps) == ["All 3 classes (it 25)"]
    assert maps[0]["tile"] and maps[0]["files"][0] == "run_it025_class001.mrc"


def test_mask_job_and_mask_chip_next_to_a_map(tmp_path):
    assert labels(list_job_maps(_job(tmp_path, "mask.mrc"))) == ["Mask"]
    d2 = tmp_path / "other"
    d2.mkdir()
    for n in ("postprocess.mrc", "postprocess_masked.mrc", "my_mask.mrc", "relion_locres.mrc"):
        (d2 / n).write_bytes(b"x")
    maps = list_job_maps(d2)
    assert labels(maps) == ["Post-processed", "relion_locres", "Mask", "Post-processed (masked)"]
    assert [m["label"] for m in card_maps(maps)] == ["Post-processed", "Mask"]


def test_no_maps_and_dumps(tmp_path):
    assert list_job_maps(_job(tmp_path, "note.txt", "run.out")) == [] and card_maps([]) == []
    big = tmp_path / "dump"
    big.mkdir()
    for i in range(70):
        (big / ("p%03d.mrc" % i)).write_bytes(b"x")
    assert list_job_maps(big) == []
    assert list_job_maps(tmp_path / "does-not-exist") == []


def test_card_maps_prefers_a_mask_entry_even_when_it_belongs_to_another_job():
    own = {"label": "Final map", "files": ["run_class001.mrc"], "tile": False, "rank": 1}
    used = {"label": "Mask (m013)", "files": ["mask.mrc"], "tile": False, "rank": 4, "job": "MaskCreate/job013"}
    chips = card_maps(sorted([used, own], key=lambda m: m["rank"]))
    assert [c["label"] for c in chips] == ["Final map", "Mask (m013)"] and chips[1]["job"] == "MaskCreate/job013"


def test_long_classification_keeps_its_buttons(tmp_path):
    """Class3D with many iterations holds hundreds of run_itNNN_classNNN.mrc: still a result folder, not a dump."""
    from reliontree.relion_maps import list_job_maps
    for it in range(0, 41):
        for k in range(1, 6):
            (tmp_path / ("run_it%03d_class%03d.mrc" % (it, k))).write_text("x")
    maps = list_job_maps(tmp_path)
    assert maps and maps[0]["label"].startswith("All 5 classes (it 40)") and len(maps[0]["files"]) == 5


def test_real_dump_still_rejected(tmp_path):
    from reliontree.relion_maps import list_job_maps
    for i in range(80):
        (tmp_path / ("part%03d.mrc" % i)).write_text("x")
    assert list_job_maps(tmp_path) == []
