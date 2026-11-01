import gzip
import logging
import zipfile
from pathlib import Path

import requests

from conftest import make_text_zip
from usgs_triplifier.lib import geonames_crosswalk
from usgs_triplifier.lib.geonames_crosswalk import GeoNamesCrosswalk
from usgs_triplifier.output_files import OutputFiles

SAMEAS = "<http://www.w3.org/2002/07/owl#sameAs>"


GNIS_COLUMNS = [
    "feature_id",
    "feature_name",
    "feature_class",
    "state_name",
    "county_name",
    "map_name",
    "prim_lat_dec",
    "prim_long_dec",
]


def _gnis_row(fid, name, state, lat, lon, cls="Lake"):
    return {
        "feature_id": fid,
        "feature_name": name,
        "feature_class": cls,
        "state_name": state,
        "county_name": "Somewhere",
        "map_name": "Map",
        "prim_lat_dec": lat,
        "prim_long_dec": lon,
    }


def _gnis_zip(input_dir: Path, rows: list[dict[str, str | float]]) -> Path:
    """
    Stages the rows as the DomesticNames text product.

    :param input_dir: Directory the crosswalk reads zips from.
    :param rows: Row dicts keyed by the GNIS_COLUMNS names.
    :return: Path to the zip file.
    """
    return make_text_zip(
        input_dir,
        "DomesticNames_National_Text.zip",
        "Text/DomesticNames_National.txt",
        ["|".join(GNIS_COLUMNS)]
        + ["|".join(str(row[c]) for c in GNIS_COLUMNS) for row in rows],
    )


def _geonames_row(gid, name, lat, lon, state, gn_class="", alternates=""):
    # A row of the GeoNames main format has 19 tab-separated columns
    cols = [""] * 19
    cols[0], cols[1], cols[3], cols[4], cols[5], cols[6], cols[10] = (
        str(gid),
        name,
        alternates,
        str(lat),
        str(lon),
        gn_class,
        state,
    )
    return "\t".join(cols)


def _write_us_zip(input_dir, rows):
    with zipfile.ZipFile(input_dir / GeoNamesCrosswalk.US_EXPORT_NAME, "w") as zf:
        zf.writestr("US.txt", "\n".join(rows) + "\n")


def test_nearest_same_named_candidate_within_threshold_wins(data_dirs, config):
    input_dir, output_dir = data_dirs
    _gnis_zip(
        input_dir,
        [
            _gnis_row("1", "Blue Lake", "California", 40.0, -120.0),
            # same-named candidate exists but 50+ km away
            _gnis_row("2", "Far Peak", "Alaska", 61.0, -150.0),
            # also has a curated Wikidata pair (QA reference only)
            _gnis_row("3", "Linked Lake", "California", 39.0, -121.0),
        ],
    )
    _write_us_zip(
        input_dir,
        [
            _geonames_row(111, "Blue Lake", 40.001, -120.001, "CA"),  # ~140 m
            _geonames_row(222, "Blue Lake", 40.05, -120.05, "CA"),  # ~7 km
            _geonames_row(333, "Far Peak", 61.5, -150.0, "AK"),  # ~55 km
            _geonames_row(444, "Linked Lake", 39.0, -121.0, "CA"),
        ],
    )
    (output_dir / OutputFiles.WIKIDATA_GEONAMES_PAIRS).write_text("3,999\n")

    path = GeoNamesCrosswalk(config).build()

    assert path == output_dir / OutputFiles.GEONAMES_CROSSWALK
    with gzip.open(path, "rt", encoding="utf-8") as f:
        lines = f.read().splitlines()
    # Each feature is linked to its nearest candidate, including features that
    # also have a Wikidata pair
    assert sorted(lines) == [
        f"<{config.lod_base}/gnis/feature/1> {SAMEAS} <http://sws.geonames.org/111/> .",
        f"<{config.lod_base}/gnis/feature/3> {SAMEAS} <http://sws.geonames.org/444/> .",
    ]


def test_missing_dump_is_not_fatal(data_dirs, monkeypatch, config):
    def boom(*a, **kw):
        raise requests.ConnectionError("no route to geonames")

    monkeypatch.setattr(geonames_crosswalk.requests, "get", boom)
    assert GeoNamesCrosswalk(config).build() is None


def test_alignment_guardrails(data_dirs, caplog, config):
    input_dir, output_dir = data_dirs
    _gnis_zip(
        input_dir,
        [
            # abbreviation + punctuation normalization
            _gnis_row("10", "St. Marys River", "California", 40.0, -120.0, "Stream"),
            # found only via a GeoNames alternate name
            _gnis_row("11", "Round Lake", "California", 40.2, -120.0, "Lake"),
            # Same name, but a stream's class is incompatible with a town's
            _gnis_row("12", "Milltown", "California", 40.4, -120.0, "Stream"),
            # Two candidates at similar distances, so the feature is left unpaired
            _gnis_row("13", "Twin Pond", "California", 40.6, -120.0, "Lake"),
            # Two features with one GeoNames record, which is paired with one of them
            _gnis_row("14", "Shared Spring", "California", 41.0, -120.0, "Spring"),
            _gnis_row("15", "Shared Spring", "California", 41.03, -120.0, "Spring"),
            # A point class, so 7 km exceeds the distance limit
            _gnis_row(
                "16", "Faraway City", "California", 42.0, -120.0, "Populated Place"
            ),
            # Not a point class, so 7 km is within the distance limit
            _gnis_row("17", "Long Creek", "California", 43.0, -120.0, "Stream"),
            # Has a Wikidata pair, which the link is compared with
            _gnis_row("18", "Check Lake", "California", 44.0, -120.0, "Lake"),
        ],
    )
    _write_us_zip(
        input_dir,
        [
            _geonames_row(1010, "Saint Marys River", 40.001, -120.0, "CA", "H"),
            _geonames_row(
                1111, "Bigwater", 40.201, -120.0, "CA", "H", "Round Lake,Roundy"
            ),
            _geonames_row(1212, "Milltown", 40.401, -120.0, "CA", "P"),
            _geonames_row(1313, "Twin Pond", 40.605, -120.0, "CA", "H"),
            _geonames_row(1414, "Twin Pond", 40.608, -120.0, "CA", "H"),
            _geonames_row(1515, "Shared Spring", 41.001, -120.0, "CA", "H"),
            _geonames_row(1616, "Faraway City", 42.063, -120.0, "CA", "P"),
            _geonames_row(1717, "Long Creek", 43.063, -120.0, "CA", "H"),
            _geonames_row(1818, "Check Lake", 44.001, -120.0, "CA", "H"),
        ],
    )
    (output_dir / OutputFiles.WIKIDATA_GEONAMES_PAIRS).write_text("18,1818\n")

    with caplog.at_level(logging.INFO):
        path = GeoNamesCrosswalk(config).build()

    with gzip.open(path, "rt", encoding="utf-8") as f:
        links = {
            line.split(" ")[0]: line.rsplit("/", 2)[-2]
            for line in f.read().splitlines()
        }
    expected = {
        f"<{config.lod_base}/gnis/feature/10>": "1010",
        f"<{config.lod_base}/gnis/feature/11>": "1111",
        f"<{config.lod_base}/gnis/feature/14>": "1515",
        f"<{config.lod_base}/gnis/feature/17>": "1717",
        f"<{config.lod_base}/gnis/feature/18>": "1818",
    }
    assert links == expected
    # The link of feature 18 agrees with its Wikidata pair
    assert (
        "GeoNames links agree with Wikidata on 1 of 1 features (100.0%)" in caplog.text
    )
