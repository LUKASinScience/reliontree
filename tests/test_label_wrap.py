"""Card footer text must wrap onto extra lines instead of spilling past the card border."""
from reliontree.relion_treebuild import _wrap_label


def test_short_label_stays_on_one_line():
    assert _wrap_label(["28.7 A", "6,407 particles"], 32) == ["28.7 A / 6,407 particles"]


def test_best_resolution_label_wraps_without_splitting_segments():
    lines = _wrap_label(["28.7 A shell", "27.84 A FSC", "4,025 particles"], 32)
    assert lines == ["28.7 A shell / 27.84 A FSC", "4,025 particles"]
    assert all(len(line) <= 32 for line in lines)


def test_overlong_single_segment_is_kept_whole():
    assert _wrap_label(["x" * 50], 32) == ["x" * 50]


def test_empty_label_has_no_lines():
    assert _wrap_label([], 32) == []
