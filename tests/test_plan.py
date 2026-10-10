from reliontree import relion_plan

STAR = '''data_job

_rlnJobTypeLabel             relion.class3d
_rlnJobIsContinue                             1

data_joboptions_values

loop_
_rlnJobOptionVariable #1
_rlnJobOptionValue #2
nr_classes "3"
nr_iter "25"
'''


def test_plan_check_and_sweep(tmp_path):
    d = tmp_path / "Class3D" / "job021"
    d.mkdir(parents=True)
    (d / "job.star").write_text(STAR)
    plan = {"steps": [
        {"id": "a", "from": "Class3D/job021", "set": {"nr_classes": 4}},
        {"id": "s", "from": "a", "sweep": {"nr_iter": [10, 50]}},
        {"id": "bad", "from": "Class3D/job021", "set": {"nr_clases": 1, "nr_iter": "{{nope}}"}},
    ]}
    rows = {r["id"]: r for r in relion_plan.resolve(tmp_path, plan)}
    assert rows["a"]["changed"] == {"nr_classes": ("3", "4")} and not rows["a"]["errors"]
    assert 'nr_classes "4"' in rows["s_nr_iter10"]["text"] and 'nr_iter "50"' in rows["s_nr_iter50"]["text"]
    assert "_rlnJobIsContinue                             0" in rows["a"]["text"]
    assert len(rows["bad"]["errors"]) == 2
