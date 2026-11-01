import gzip
import logging
import subprocess
from pathlib import Path

import pytest

from usgs_triplifier.lib import validation
from usgs_triplifier.lib.validation import ReleaseValidator, ShaclValidationError

LOD = "http://gnis-ld.org/lod"
RDF_TYPE = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
GEO = "http://gnis-ld.org/geometry"
GEOSPARQL = "http://www.opengis.net/ont/geosparql#"
CRS84 = "<http://www.opengis.net/def/crs/OGC/1.3/CRS84>"

GOOD_FEATURE = [
    f'<{LOD}/gnis/feature/1> <{LOD}/gnis/ontology/featureId> "1" .',
    f"<{LOD}/gnis/feature/1> {RDF_TYPE} <{LOD}/usgs/ontology/Summit> .",
    f'<{LOD}/gnis/feature/1> <{LOD}/gnis/ontology/officialName> "Blue Peak"@en .',
    f"<{LOD}/gnis/feature/1> <{LOD}/gnis/ontology/elevation> _:e1 .",
    '_:e1 <http://qudt.org/schema/qudt/numericValue> "5280"^^<http://www.w3.org/2001/XMLSchema#double> .',
    "_:e1 <http://qudt.org/schema/qudt/unit> <http://qudt.org/vocab/unit/FT> .",
]


def _write(output_dir, name, lines):
    with gzip.open(output_dir / name, "wt", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _wkt(node: str, wkt: str) -> str:
    """
    Builds the N-Triples line attaching a CRS84 WKT literal to a geometry node.

    :param node: IRI of the geometry node.
    :param wkt: WKT text, without the CRS prefix.
    :return: The N-Triples line.
    """
    return f'<{node}> <{GEOSPARQL}asWKT> "{CRS84}{wkt}"^^<{GEOSPARQL}wktLiteral> .'


def test_conforming_release_passes(jena_config):
    _write(jena_config.output_directory, "features.nt.gz", GOOD_FEATURE)
    assert ReleaseValidator(jena_config).validate() is True
    # The temporary store is removed
    assert not (jena_config.output_directory / ReleaseValidator.STORE_NAME).exists()


def test_violation_fails_and_is_logged(jena_config, caplog):
    # officialName without a language tag violates the rdf:langString shape
    _write(
        jena_config.output_directory,
        "features.nt.gz",
        GOOD_FEATURE
        + [
            f'<{LOD}/gnis/feature/2> <{LOD}/gnis/ontology/featureId> "2" .',
            f'<{LOD}/gnis/feature/2> <{LOD}/gnis/ontology/officialName> "Bare Literal" .',
        ],
    )
    with caplog.at_level(logging.ERROR):
        assert ReleaseValidator(jena_config).validate() is False
    assert "SHACL violation: 1 x" in caplog.text
    assert "feature/2" in caplog.text


def test_incomplete_elevation_bnode_is_caught(jena_config):
    lines = [
        f'<{LOD}/gnis/feature/3> <{LOD}/gnis/ontology/featureId> "3" .',
        f"<{LOD}/gnis/feature/3> <{LOD}/gnis/ontology/elevation> _:e3 .",
        '_:e3 <http://qudt.org/schema/qudt/numericValue> "12"^^<http://www.w3.org/2001/XMLSchema#double> .',
    ]
    _write(jena_config.output_directory, "features.nt.gz", lines)
    assert ReleaseValidator(jena_config).validate() is False


def test_upstream_date_quirk_is_only_a_warning(jena_config, caplog):
    _write(
        jena_config.output_directory,
        "features.nt.gz",
        GOOD_FEATURE
        + [
            f'<{LOD}/gnis/feature/1> <{LOD}/gnis/ontology/dateFeatureCreated> "bogus" .'
        ],
    )
    with caplog.at_level(logging.WARNING):
        assert ReleaseValidator(jena_config).validate() is True
    assert "SHACL warning" in caplog.text


def test_point_and_multipoint_geometries_conform(jena_config):
    point = f"{GEO}/point/gnisf.1"
    multipoint = f"{GEO}/multipoint/gnisf.1"
    _write(
        jena_config.output_directory,
        "features.nt.gz",
        GOOD_FEATURE
        + [
            f"<{LOD}/gnis/feature/1> <{GEOSPARQL}hasGeometry> <{point}> .",
            _wkt(point, "POINT(-117.2 34.5)"),
        ],
    )
    _write(
        jena_config.output_directory,
        "geometries.nt.gz",
        [
            f"<{LOD}/gnis/feature/1> <{GEOSPARQL}hasGeometry> <{multipoint}> .",
            _wkt(multipoint, "MULTIPOINT ((-117.2 34.5), (-117.1 34.6))"),
        ],
    )
    assert ReleaseValidator(jena_config).validate() is True


def test_three_dimensional_wkt_is_a_violation(jena_config):
    multipoint = f"{GEO}/multipoint/gnisf.1"
    _write(
        jena_config.output_directory,
        "geometries.nt.gz",
        [
            f"<{LOD}/gnis/feature/1> <{GEOSPARQL}hasGeometry> <{multipoint}> .",
            _wkt(multipoint, "MULTIPOINT Z ((-117.2 34.5 0))"),
        ],
    )
    assert ReleaseValidator(jena_config).validate() is False


def test_subject_is_checked_across_files(jena_config):
    # Each file alone conforms, but together feature 1 has two official names
    _write(jena_config.output_directory, "features.nt.gz", GOOD_FEATURE)
    _write(
        jena_config.output_directory,
        "names.nt.gz",
        [f'<{LOD}/gnis/feature/1> <{LOD}/gnis/ontology/officialName> "Red Peak"@en .'],
    )
    assert ReleaseValidator(jena_config).validate() is False


def test_second_state_is_only_a_warning(jena_config, caplog):
    # A legacy feature that crosses a border has a state for each side
    alias = f"{LOD}/gnis/feature-alias"
    _write(
        jena_config.output_directory,
        "features.nt.gz",
        GOOD_FEATURE
        + [
            f"<{LOD}/gnis/feature/1> <{LOD}/gnis/ontology/state> <{alias}/Montana> .",
            f"<{LOD}/gnis/feature/1> <{LOD}/gnis/ontology/state> <{alias}/AB> .",
        ],
    )
    with caplog.at_level(logging.WARNING):
        assert ReleaseValidator(jena_config).validate() is True
    assert "SHACL warning: 1 x <http://gnis-ld.org/lod/gnis/ontology/state>" in (
        caplog.text
    )


def test_state_that_is_not_an_iri_is_a_violation(jena_config):
    _write(
        jena_config.output_directory,
        "features.nt.gz",
        GOOD_FEATURE + [f'<{LOD}/gnis/feature/1> <{LOD}/gnis/ontology/state> "MT" .'],
    )
    assert ReleaseValidator(jena_config).validate() is False


def test_relative_shape_iris_follow_lod_base(jena_config):
    # Under another lod_base the shapes target that base's IRIs
    jena_config.lod_base = "http://stage.gnis-ld.org/lod"
    stage = "http://stage.gnis-ld.org/lod"
    _write(
        jena_config.output_directory,
        "features.nt.gz",
        [
            f'<{stage}/gnis/feature/2> <{stage}/gnis/ontology/featureId> "2" .',
            f'<{stage}/gnis/feature/2> <{stage}/gnis/ontology/officialName> "Bare" .',
        ],
    )
    assert ReleaseValidator(jena_config).validate() is False


class FakeJena:
    """
    Stands in for subprocess.run and records the Jena commands.
    """

    def __init__(self, validator_output: str = "", returncode: int = 0) -> None:
        """
        Creates the fake.

        :param validator_output: Standard output of the validator.
        :param returncode: Exit status of every command.
        """
        self.validator_output = validator_output
        self.returncode = returncode
        self.commands: list[list[str]] = []

    def __call__(self, command, **kwargs) -> subprocess.CompletedProcess:
        """
        Records a command and creates the store directory as the loader does.

        :param command: The command and its arguments.
        :param kwargs: Ignored subprocess.run options.
        :return: The completed process.
        """
        self.commands.append(command)
        if command[1] == "--loc":
            Path(command[2]).mkdir()
        stdout = "" if command[1] == "--loc" else self.validator_output
        return subprocess.CompletedProcess(command, self.returncode, stdout, "boom")


def test_results_are_parsed_and_the_store_is_removed(config, monkeypatch, caplog):
    _write(config.output_directory, "features.nt.gz", GOOD_FEATURE)
    fake = FakeJena(
        "Violation\t3\t<http://x/p>\tMaxCountConstraintComponent\thttp://x/f\tToo many\n"
        "Warning\t2\t<http://x/d>\tDatatypeConstraintComponent\thttp://x/g\tNot a date\n"
    )
    monkeypatch.setattr(validation.subprocess, "run", fake)
    config.jena_jvm_args = "-Xmx1g -Xss8m"

    with caplog.at_level(logging.INFO):
        assert ReleaseValidator(config).validate() is False

    loader, validator = fake.commands
    store = str(config.output_directory / ReleaseValidator.STORE_NAME)
    assert loader[0].endswith("tdb2.tdbloader")
    assert loader[1:3] == ["--loc", store]
    assert loader[3].endswith("features.nt.gz")
    assert validator[1:3] == ["-Xmx1g", "-Xss8m"]
    assert validator[-3:] == [store, str(ReleaseValidator.SHAPES_PATH), f"{LOD}/"]
    assert "3 violations, 2 warnings" in caplog.text
    assert "3 x <http://x/p> MaxCountConstraintComponent" in caplog.text
    assert not (config.output_directory / ReleaseValidator.STORE_NAME).exists()


def test_failed_jena_command_raises_and_removes_the_store(config, monkeypatch):
    _write(config.output_directory, "features.nt.gz", GOOD_FEATURE)
    monkeypatch.setattr(validation.subprocess, "run", FakeJena(returncode=1))

    with pytest.raises(ShaclValidationError, match="loader exited with status 1"):
        ReleaseValidator(config).validate()
    assert not (config.output_directory / ReleaseValidator.STORE_NAME).exists()


def test_no_files_pass_without_running_jena(config, monkeypatch):
    fake = FakeJena()
    monkeypatch.setattr(validation.subprocess, "run", fake)
    assert ReleaseValidator(config).validate() is True
    assert fake.commands == []
