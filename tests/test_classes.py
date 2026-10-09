

def test_scalar_with_signed_exponent(tmp_path):
    from reliontree.relion_artifacts import _find_scalar_field
    assert _find_scalar_field("_rlnChangesOptimalClasses   1.5e+00\n", "_rlnChangesOptimalClasses") == 1.5


def _mrc(path, nz, nx=8):
    import struct
    hdr = struct.pack("<3ii", nx, nx, nz, 2).ljust(1024, b"\0")
    path.write_bytes(hdr + b"".join(struct.pack("<f", float(i % 5)) for i in range(nx * nx * nz)))


def test_class2d_stack_and_iteration_thumbs(tmp_path):
    from reliontree.relion_classes import class_iter_thumbs
    from reliontree.relion_artifacts import list_class_stack
    _mrc(tmp_path / "run_it003_classes.mrcs", nz=3)
    assert list_class_stack(tmp_path).name == "run_it003_classes.mrcs"
    assert len(class_iter_thumbs(tmp_path, 3)) == 3
    assert class_iter_thumbs(tmp_path, 2) == []
    _mrc(tmp_path / "run_it001_class001.mrc", nz=4)
    _mrc(tmp_path / "run_it001_class002.mrc", nz=4)
    assert len(class_iter_thumbs(tmp_path, 1)) == 2


def test_api_rejects_path_traversal(tmp_path):
    from reliontree.cli import _api
    assert "error" in _api("/overlap", {"a": ["../etc/x"], "b": ["Class3D/job001"]}, tmp_path)
    assert "error" in _api("/class-thumbs", {"job": ["Class3D/job1/../../x"], "it": ["1"]}, tmp_path)
    assert _api("/class-thumbs", {"job": ["Class3D/job001"], "it": ["1"]}, tmp_path) == {"thumbs": []}


def test_class_selection_flags(tmp_path):
    from reliontree.relion_classes import class_selection
    (tmp_path / "backup_selection.star").write_text("data_\n\nloop_\n_rlnSelected #1\n0\n1\n0\n")
    assert class_selection(tmp_path, 3) == [False, True, False]
    assert class_selection(tmp_path, 4) is None  # length mismatch (not a class-selection of this parent)
    assert class_selection(tmp_path / "nope", 3) is None
