import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import Point

from usgs_triplifier.config import config


@pytest.fixture()
def data_dirs(tmp_path, monkeypatch):
    """Point the shared config singleton at per-test input/output directories."""
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    monkeypatch.setattr(config, "input_directory", input_dir)
    monkeypatch.setattr(config, "output_directory", output_dir)
    return input_dir, output_dir


def make_gpkg_zip(input_dir, zip_name, layers):
    """
    Build a zipped GeoPackage in ``input_dir``.

    :param input_dir: Directory the triplifiers read zips from.
    :param zip_name: Name of the zip file (must match *_GPKG.zip).
    :param layers: Mapping of layer name -> list of row dicts.
    """
    gpkg_path = input_dir / "data.gpkg"
    for layer, rows in layers.items():
        gdf = gpd.GeoDataFrame(
            rows, geometry=[Point(0, 0)] * len(rows), crs="EPSG:4326"
        )
        gdf.to_file(gpkg_path, layer=layer, driver="GPKG")
    zip_path = input_dir / zip_name
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(gpkg_path, "data.gpkg")
    gpkg_path.unlink()
    return zip_path


def make_text_zip(input_dir, zip_name, txt_name, lines):
    """
    Build a zip containing one pipe-delimited text file in ``input_dir``.

    :param input_dir: Directory the triplifiers read zips from.
    :param zip_name: Name of the zip file (must match the triplifier's glob).
    :param txt_name: Name of the text file inside the zip.
    :param lines: Text lines (header first) to join with newlines.
    """
    zip_path = input_dir / zip_name
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(txt_name, "\n".join(lines) + "\n")
    return zip_path
