from pathlib import Path

import pytest

from usgs_triplifier.output_files import OutputFiles
from usgs_triplifier.usgs_products import UsgsProducts


def test_patterns_follow_the_input_format():
    assert UsgsProducts.FEATURES.pattern_for(False) == "DomesticNames*_Text.zip"
    assert UsgsProducts.FEATURES.pattern_for(True) == "NationalFile*.zip"
    assert UsgsProducts.GEOPACKAGE.pattern_for(False) == "*_GPKG.zip"


def test_legacy_dumps_have_no_geopackage():
    with pytest.raises(ValueError):
        UsgsProducts.GEOPACKAGE.pattern_for(True)


def test_source_urls_cover_the_files_each_build_reads():
    current = UsgsProducts.source_urls(legacy_dump=False)
    legacy = UsgsProducts.source_urls(legacy_dump=True)
    assert f"{UsgsProducts.S3_BASE}/{UsgsProducts.GEOPACKAGE.key}" in current
    assert len(current) == 5 and len(legacy) == 4
    assert all("/Archive/" in url for url in legacy)


def test_release_file_names_round_trip_through_the_patterns():
    release = OutputFiles.release("260701")
    historical = OutputFiles.historical_release("260701")
    assert OutputFiles.RELEASE.match(release)[1] == "260701"
    assert OutputFiles.HISTORICAL_RELEASE.match(historical)[1] == "260701"
    assert OutputFiles.RELEASE.match(historical) is None
    assert OutputFiles.sidecar_for(Path("/a/gnis-ld-260701.nt.gz")) == Path(
        "/a/gnis-ld-260701.meta.json"
    )


def test_zip_paths_leaves_out_the_current_product_for_a_legacy_dump(tmp_path):
    for name in ("AllNames.zip", "AllNames_National_Text.zip", "Other.zip"):
        (tmp_path / name).write_bytes(b"")

    assert UsgsProducts.NAMES.zip_paths(tmp_path, legacy_dump=True) == [
        tmp_path / "AllNames.zip"
    ]
    assert UsgsProducts.NAMES.zip_paths(tmp_path, legacy_dump=False) == [
        tmp_path / "AllNames_National_Text.zip"
    ]
    assert UsgsProducts.NAMES.zip_paths(tmp_path / "missing", legacy_dump=False) == []
