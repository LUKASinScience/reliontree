"""An existing-but-unreadable pipeline file must be reported, not silently dropped from the lineage."""
import logging
import os
import stat

import pytest

from reliontree.relion_pipeline import load_pipeline


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="needs POSIX permissions and a non-root user")
def test_unreadable_pipeline_is_logged(tmp_path, caplog):
    star = tmp_path / "default_pipeline.star"
    star.write_text("data_pipeline_general\n")
    star.chmod(0)
    try:
        with caplog.at_level(logging.WARNING):
            load_pipeline(tmp_path)
    finally:
        star.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert any("could not read" in r.message for r in caplog.records)


def test_missing_job_star_stays_quiet(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        load_pipeline(tmp_path)      # no files at all: normal for a fresh directory
    assert not caplog.records
