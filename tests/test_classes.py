

def test_scalar_with_signed_exponent(tmp_path):
    from reliontree.relion_artifacts import _find_scalar_field
    assert _find_scalar_field("_rlnChangesOptimalClasses   1.5e+00\n", "_rlnChangesOptimalClasses") == 1.5
