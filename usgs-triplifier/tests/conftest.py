import gzip
import zipfile
from pathlib import Path

import numpy as np
import pyogrio.raw
import pytest
import shapely
from rdflib import Graph

from usgs_triplifier.config import Config


def parse_nt_gz(path: Path) -> Graph:
    """
    Parses a gzipped N-Triples file into a Graph for assertions.

    :param path: Gzipped N-Triples file.
    :return: Graph holding the file's triples.
    """
    graph = Graph()
    with gzip.open(path, "rt", encoding="utf-8") as f:
        graph.parse(f, format="nt")
    return graph


@pytest.fixture()
def config(tmp_path: Path) -> Config:
    """
    Builds settings whose input, output and archive directories are inside
    the test's temporary directory.

    :param tmp_path: pytest temporary directory.
    :return: The settings.
    """
    settings = Config(
        input_directory=tmp_path / "input",
        output_directory=tmp_path / "output",
        archive_output_directory=tmp_path / "archive",
    )
    settings.input_directory.mkdir()
    settings.output_directory.mkdir()
    return settings


@pytest.fixture()
def jena_config(config: Config) -> Config:
    """
    Returns the test's settings when JENA_HOME and JENA_JAVA_HOME point at a
    Jena distribution with validate-release.jar and a Java runtime, and skips
    the test otherwise.

    :param config: The test's settings.
    :return: The settings.
    """
    jar = config.jena_home / "validate-release.jar"
    java = config.jena_java_home / "bin" / "java"
    if not jar.exists() or not java.exists():
        pytest.skip("JENA_HOME or JENA_JAVA_HOME does not point at a Jena build")
    return config


@pytest.fixture()
def data_dirs(config: Config) -> tuple[Path, Path]:
    """
    Returns the test's input and output directories.

    :param config: The test's settings.
    :return: (input directory, output directory).
    """
    return config.input_directory, config.output_directory


def make_gpkg_zip(
    input_dir: Path, zip_name: str, geometries: dict[int, shapely.Geometry | None]
) -> Path:
    """
    Builds a zipped GeoPackage in input_dir shaped like the USGS FullModel.

    :param input_dir: Directory the triplifiers read zips from.
    :param zip_name: Name of the zip file (must match *_GPKG.zip).
    :param geometries: Mapping of feature id to shapely geometry, or None
        for a feature without one.
    :return: Path to the zip file.
    """
    gpkg_path = input_dir / "data.gpkg"
    feature_ids = np.array(list(geometries), dtype="int64")
    wkb = np.array(
        [None if g is None else shapely.to_wkb(g) for g in geometries.values()],
        dtype=object,
    )
    pyogrio.raw.write(
        gpkg_path,
        geometry=wkb,
        field_data=[feature_ids],
        fields=["feature_id"],
        layer="DomesticNames",
        driver="GPKG",
        geometry_type="MultiPoint Z",
        crs="EPSG:4326",
    )
    zip_path = input_dir / zip_name
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(gpkg_path, "data.gpkg")
    gpkg_path.unlink()
    return zip_path


def make_text_zip(
    input_dir: Path, zip_name: str, txt_name: str, lines: list[str]
) -> Path:
    """
    Builds a zip containing one pipe-delimited text file in input_dir.

    :param input_dir: Directory the triplifiers read zips from.
    :param zip_name: Name of the zip file (must match the triplifier's glob).
    :param txt_name: Name of the text file inside the zip.
    :param lines: Text lines (header first) to join with newlines.
    :return: Path to the zip file.
    """
    zip_path = input_dir / zip_name
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(txt_name, "\n".join(lines) + "\n")
    return zip_path
