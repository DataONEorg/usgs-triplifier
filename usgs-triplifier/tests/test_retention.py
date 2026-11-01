import gzip
from datetime import datetime, timezone

import pytest

from usgs_triplifier.lib.archive_exporter import ReleaseExporter
from usgs_triplifier.lib.retention import RetentionBuilder
from usgs_triplifier.output_files import OutputFiles

BUILD_TIME = datetime(2026, 7, 1, tzinfo=timezone.utc)

LOD = "http://gnis-ld.org/lod"
GEO = "http://gnis-ld.org/geometry"
RDF_TYPE = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
LABEL = "<http://www.w3.org/2000/01/rdf-schema#label>"
SAMEAS = "<http://www.w3.org/2002/07/owl#sameAs>"
HAS_GEOMETRY = "<http://www.opengis.net/ont/geosparql#hasGeometry>"
FEATURE_ID = f"<{LOD}/gnis/ontology/featureId>"
DISAMBIGUATES_TO = f"<{LOD}/gnis/ontology/disambiguatesTo>"
HISTORICAL = f"<{LOD}/usgs/ontology/HistoricalFeature>"
LAST_APPEARED = f"<{LOD}/gnis/ontology/lastAppearedIn>"


def _feature(n: int, label: str) -> list[str]:
    """
    Builds the featureId and label lines of a feature.

    :param n: Feature id.
    :param label: Label text.
    :return: The two N-Triples lines.
    """
    return [
        f'<{LOD}/gnis/feature/{n}> {FEATURE_ID} "{n}" .',
        f'<{LOD}/gnis/feature/{n}> {LABEL} "{label}" .',
    ]


def _tombstones(n: int, release_id: str) -> list[str]:
    """
    Builds the lines a feature gets when it is copied from a release file.

    :param n: Feature id.
    :param release_id: Id of the release the feature last appeared in.
    :return: The two N-Triples lines.
    """
    return [
        f"<{LOD}/gnis/feature/{n}> {RDF_TYPE} {HISTORICAL} .",
        f"<{LOD}/gnis/feature/{n}> {LAST_APPEARED} <{LOD}/gnis/release/{release_id}> .",
    ]


# Feature 1 is dropped upstream. Its record has an alias, a geometry, which
# is an IRI subject of its own, and an elevation blank node.
ALIAS_LINE = f"<{LOD}/gnis/feature-alias/Utah.Salt_Lake.Lake.Blue_Lake> {SAMEAS} <{LOD}/gnis/feature/1> ."
FEATURE_1 = _feature(1, "Blue Lake") + [
    f"<{LOD}/gnis/feature/1> {HAS_GEOMETRY} <{GEO}/point/gnisf.1> .",
    f"<{LOD}/gnis/feature/1> <{LOD}/gnis/ontology/elevation> _:b1 .",
    '_:b1 <http://qudt.org/schema/qudt/numericValue> "5280.0"^^<http://www.w3.org/2001/XMLSchema#double> .',
    f'<{GEO}/point/gnisf.1> <http://www.opengis.net/ont/geosparql#asWKT> "POINT(1 2)" .',
]
DROPPED_RECORD = [ALIAS_LINE] + FEATURE_1

KEPT = _feature(2, "Kept Creek")

# Feature 3 was already retained in an earlier release, with its tombstones
PRIOR_HISTORICAL = _feature(3, "Ghost Town") + _tombstones(3, "260101")


@pytest.fixture()
def archive_dir(tmp_path, monkeypatch, config):
    archive = tmp_path / "archive"
    archive.mkdir()
    config.archive_output_directory = archive
    return archive


def _write_dump(archive_dir, name, lines):
    with gzip.open(archive_dir / name, "wt", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _write_new_release(config, lines, name="features.nt.gz"):
    """
    Writes the lines of the release being built into the output directory.
    """
    with gzip.open(config.output_directory / name, "wt", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _retained_lines(config):
    with gzip.open(config.output_directory / OutputFiles.RETAINED, "rt") as f:
        return [line for line in f.read().splitlines() if line.strip()]


def test_dropped_record_is_carried_with_closure_and_tombstone(
    data_dirs, archive_dir, config
):
    # The alias line sits after the feature's lines in the release file
    _write_dump(archive_dir, "gnis-ld-260401.nt.gz", FEATURE_1 + [ALIAS_LINE] + KEPT)
    _write_new_release(config, KEPT)

    assert RetentionBuilder(config).build(BUILD_TIME) is not None
    lines = _retained_lines(config)

    # Still-current features are not carried
    assert not set(KEPT) & set(lines)
    # The alias line comes first, then the feature, blank node and geometry
    # lines, then the tombstones against the release it last appeared in
    assert lines == DROPPED_RECORD + _tombstones(1, "260401")


def test_alias_and_geometry_of_a_current_feature_are_not_retained(
    data_dirs, archive_dir, config
):
    # Feature 1 was renamed and lost its coordinates, so its old alias and
    # geometry are gone from the new release while the feature itself stays
    _write_dump(archive_dir, "gnis-ld-260401.nt.gz", DROPPED_RECORD + KEPT)
    _write_new_release(config, KEPT + _feature(1, "Azure Lake"))

    assert RetentionBuilder(config).build(BUILD_TIME) is None
    assert _retained_lines(config) == []


def test_alias_now_owned_by_another_feature_is_not_retained(
    data_dirs, archive_dir, config
):
    # The alias of dropped feature 1 is a subject in the new release, naming
    # feature 9, so retaining the old owl:sameAs would equate the two
    alias = f"<{LOD}/gnis/feature-alias/Utah.Salt_Lake.Lake.Blue_Lake>"
    _write_dump(archive_dir, "gnis-ld-260401.nt.gz", DROPPED_RECORD + KEPT)
    _write_new_release(config, KEPT + [f"{alias} {SAMEAS} <{LOD}/gnis/feature/9> ."])

    RetentionBuilder(config).build(BUILD_TIME)
    lines = _retained_lines(config)

    assert FEATURE_1[0] in lines
    assert ALIAS_LINE not in lines


def test_crosswalk_link_is_not_a_feature(data_dirs, archive_dir, config):
    # Feature 1 is dropped but Wikidata still links it, and the earlier
    # release linked feature 8, which was never a feature of any release
    link_1 = f"<{LOD}/gnis/feature/1> {SAMEAS} <http://www.wikidata.org/entity/Q1> ."
    link_8 = f"<{LOD}/gnis/feature/8> {SAMEAS} <http://www.wikidata.org/entity/Q8> ."
    _write_dump(archive_dir, "gnis-ld-260401.nt.gz", DROPPED_RECORD + KEPT + [link_8])
    _write_new_release(config, KEPT)
    _write_new_release(config, [link_1], name="crosswalk.nt.gz")

    RetentionBuilder(config).build(BUILD_TIME)
    lines = _retained_lines(config)

    assert lines == DROPPED_RECORD + _tombstones(1, "260401")


def test_disambiguation_alias_with_a_current_feature_is_not_retained(
    data_dirs, archive_dir, config
):
    # Features 1 and 5 shared a disambiguation alias. Feature 5 is still
    # current under another alias, so the old alias is not retained with
    # only one of its two features.
    alias = f"<{LOD}/gnis/feature-alias/Utah.Salt_Lake.Lake.Twin_Lake>"
    group = [
        f"{alias} {DISAMBIGUATES_TO} <{LOD}/gnis/feature/1> .",
        f"{alias} {DISAMBIGUATES_TO} <{LOD}/gnis/feature/5> .",
    ]
    _write_dump(
        archive_dir,
        "gnis-ld-260401.nt.gz",
        group + _feature(1, "Twin Lake") + _feature(5, "Twin Lake") + KEPT,
    )
    _write_new_release(
        config,
        KEPT
        + _feature(5, "Twin Lake")
        + [
            f"<{LOD}/gnis/feature-alias/Utah.Salt_Lake.Reservoir.Twin_Lake> {SAMEAS} <{LOD}/gnis/feature/5> ."
        ],
    )

    RetentionBuilder(config).build(BUILD_TIME)
    lines = _retained_lines(config)

    assert lines == _feature(1, "Twin Lake") + _tombstones(1, "260401")


def test_records_of_a_disambiguation_alias_are_written_together(
    data_dirs, archive_dir, config
):
    # In the release file a crosswalk line of feature 5 comes before the
    # alias lines and feature 6 sits between feature 5 and the alias group
    alias = f"<{LOD}/gnis/feature-alias/Utah.Salt_Lake.Lake.Twin_Lake>"
    alias_1 = f"{alias} {DISAMBIGUATES_TO} <{LOD}/gnis/feature/1> ."
    alias_5 = f"{alias} {DISAMBIGUATES_TO} <{LOD}/gnis/feature/5> ."
    link_5 = f"<{LOD}/gnis/feature/5> {SAMEAS} <http://www.wikidata.org/entity/Q5> ."
    _write_dump(
        archive_dir,
        "gnis-ld-260401.nt.gz",
        [link_5]
        + _feature(6, "Mid Creek")
        + [alias_1, alias_5]
        + _feature(1, "Twin Lake")
        + _feature(5, "Twin Lake")
        + KEPT,
    )
    _write_new_release(config, KEPT)

    RetentionBuilder(config).build(BUILD_TIME)
    lines = _retained_lines(config)

    assert lines == (
        [alias_1]
        + _feature(1, "Twin Lake")
        + _tombstones(1, "260401")
        + [alias_5, link_5]
        + _feature(5, "Twin Lake")
        + _tombstones(5, "260401")
        + _feature(6, "Mid Creek")
        + _tombstones(6, "260401")
    )


def test_previously_retained_records_stay_without_new_tombstones(
    data_dirs, archive_dir, config
):
    _write_dump(archive_dir, "gnis-ld-260401.nt.gz", KEPT)
    _write_dump(archive_dir, "gnis-ld-historical-260401.nt.gz", PRIOR_HISTORICAL)
    _write_new_release(config, KEPT)

    RetentionBuilder(config).build(BUILD_TIME)
    lines = _retained_lines(config)

    assert lines == PRIOR_HISTORICAL


def test_orphans_in_an_earlier_historical_file_are_dropped(
    data_dirs, archive_dir, config
):
    # An earlier run retained the alias of feature 2, which is still current
    orphan = f"<{LOD}/gnis/feature-alias/Old.Alias> {SAMEAS} <{LOD}/gnis/feature/2> ."
    _write_dump(archive_dir, "gnis-ld-260401.nt.gz", KEPT)
    _write_dump(
        archive_dir, "gnis-ld-historical-260401.nt.gz", PRIOR_HISTORICAL + [orphan]
    )
    _write_new_release(config, KEPT)

    RetentionBuilder(config).build(BUILD_TIME)

    assert _retained_lines(config) == PRIOR_HISTORICAL


def test_reappearing_feature_leaves_the_historical_set(data_dirs, archive_dir, config):
    _write_dump(archive_dir, "gnis-ld-260401.nt.gz", KEPT)
    _write_dump(archive_dir, "gnis-ld-historical-260401.nt.gz", PRIOR_HISTORICAL)
    _write_new_release(config, KEPT + _feature(3, "Ghost Town"))

    assert RetentionBuilder(config).build(BUILD_TIME) is None
    assert _retained_lines(config) == []


def test_first_release_has_nothing_to_retain(data_dirs, archive_dir, config):
    _write_new_release(config, KEPT)
    assert RetentionBuilder(config).build(BUILD_TIME) is None


def test_feature_only_in_a_backfilled_legacy_dump_is_retained(
    data_dirs, archive_dir, config
):
    # The 2021 legacy dump is added to the archive after the 2026 releases
    # exist; feature 1 is only in it, feature 4 was dropped after 2026-04
    feature_4 = _feature(4, "Old Mill")
    _write_dump(archive_dir, "gnis-ld-210825.nt.gz", DROPPED_RECORD + KEPT)
    _write_dump(archive_dir, "gnis-ld-260401.nt.gz", KEPT + feature_4)
    _write_new_release(config, KEPT)

    RetentionBuilder(config).build(BUILD_TIME)
    lines = _retained_lines(config)

    for line in DROPPED_RECORD + feature_4:
        assert line in lines
    assert _tombstones(1, "210825")[1] in lines
    assert _tombstones(4, "260401")[1] in lines
    assert not set(KEPT) & set(lines)


def test_feature_in_several_earlier_releases_is_taken_from_the_newest(
    data_dirs, archive_dir, config
):
    old = _feature(1, "Blue Pond")
    new = _feature(1, "Blue Lake")
    _write_dump(archive_dir, "gnis-ld-210825.nt.gz", old + KEPT)
    _write_dump(archive_dir, "gnis-ld-260401.nt.gz", new + KEPT)
    _write_new_release(config, KEPT)

    RetentionBuilder(config).build(BUILD_TIME)
    lines = _retained_lines(config)

    assert new[1] in lines
    assert old[1] not in lines
    stamps = [line for line in lines if LAST_APPEARED in line]
    assert stamps == [_tombstones(1, "260401")[1]]


def test_dropped_unit_record_is_retained_unchanged(data_dirs, archive_dir, config):
    unit = [
        f"<{LOD}/gnis/feature-alias/Connecticut.Fairfield> {RDF_TYPE} <{LOD}/gnis/ontology/County> .",
        f'<{LOD}/gnis/feature-alias/Connecticut.Fairfield> {LABEL} "Fairfield County"@en .',
        f"<{LOD}/gnis/feature-alias/Connecticut.Fairfield> {SAMEAS} <{LOD}/gnis/feature/7> .",
    ]
    _write_dump(archive_dir, "gnis-ld-260401.nt.gz", unit + KEPT)
    _write_new_release(config, KEPT + _feature(7, "Fairfield"))

    RetentionBuilder(config).build(BUILD_TIME)
    lines = _retained_lines(config)

    # The unit's lines are kept as they are, with no tombstones
    assert lines == unit


def test_export_historical_publishes_companion_dump(data_dirs, archive_dir, config):
    _write_dump(archive_dir, "gnis-ld-260401.nt.gz", DROPPED_RECORD + KEPT)
    _write_new_release(config, KEPT)
    RetentionBuilder(config).build(BUILD_TIME)

    dump = ReleaseExporter(config).export_historical(BUILD_TIME)

    assert dump == archive_dir / "gnis-ld-historical-260701.nt.gz"
    with gzip.open(dump, "rt", encoding="utf-8") as f:
        published = [line for line in f.read().splitlines() if line.strip()]
    assert published == _retained_lines(config)
    sidecar = (archive_dir / "gnis-ld-historical-260701.meta.json").read_text()
    assert '"id": "260701"' in sidecar
    assert f'"triples": "{len(published):,}"' in sidecar


def test_ontology_terms_are_never_retained(data_dirs, archive_dir, config):
    # A term declared in an earlier release's ontology and absent now is not
    # a feature, so nothing retains it
    term = f'<{LOD}/gnis/ontology/oldProperty> {LABEL} "Old property"@en .'
    _write_dump(archive_dir, "gnis-ld-260401.nt.gz", DROPPED_RECORD + [term])
    _write_new_release(config, KEPT)

    RetentionBuilder(config).build(BUILD_TIME)
    lines = _retained_lines(config)

    assert term not in lines
    assert FEATURE_1[0] in lines
