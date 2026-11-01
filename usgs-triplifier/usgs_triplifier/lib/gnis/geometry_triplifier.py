import logging
import tempfile
import zipfile
from pathlib import Path
from typing import ClassVar

import pyogrio
import pyogrio.raw
import shapely

from ...config import Config
from ...output_files import OutputFiles
from ...usgs_products import UsgsProducts
from .identifiers import FeatureIds
from .rdf import NTriplesWriter, Terms


class GeometryTriplifier:
    """
    Converts the multipoint geometries in the GeoPackage into geometries.nt.gz.
    """

    # Layer holding one row per feature
    LAYER: ClassVar[str] = "DomesticNames"

    # Rows read from the layer per call
    BATCH_SIZE: ClassVar[int] = 100_000

    # USGS places a feature with an unknown location at 0,0. In the
    # GeoPackage the point is a few 1e-11 degrees from 0,0, so a geometry
    # whose coordinates are all within this many degrees of 0 is skipped.
    UNKNOWN_LOCATION_TOLERANCE: ClassVar[float] = 1e-6

    _log: ClassVar[logging.Logger] = logging.getLogger(__name__)

    def __init__(self, config: Config) -> None:
        """
        Creates the triplifier.

        :param config: Settings holding the input and output directories and
            the base IRIs.
        """
        self.config = config

    def run(self) -> int:
        """
        Writes a geometry for every feature in the GeoPackage zips in the
        input directory.

        :return: Number of triples written.
        :raises FileNotFoundError: If the input directory has no GeoPackage zip.
        """
        pattern = UsgsProducts.GEOPACKAGE.pattern
        zip_paths = sorted(self.config.input_directory.glob(pattern))
        if not zip_paths:
            raise FileNotFoundError(
                f"No zip files matching {pattern} in {self.config.input_directory}"
            )

        path = self.config.output_directory / OutputFiles.GEOMETRIES
        with NTriplesWriter(path) as writer:
            for zip_path in zip_paths:
                self._log.info(f"Reading geometries from {zip_path.name}")
                with zipfile.ZipFile(zip_path, "r") as zf:
                    names = [n for n in zf.namelist() if n.endswith(".gpkg")]
                    # GDAL reads a GeoPackage from a file, so it is extracted
                    with tempfile.TemporaryDirectory() as tmpdir:
                        for name in names:
                            zf.extract(name, tmpdir)
                            self._read_layer(Path(tmpdir) / name, writer)
        self._log.info(f"Wrote {len(writer)} triples to {path}")
        return len(writer)

    def _read_layer(self, gpkg_path: Path, writer: NTriplesWriter) -> None:
        """
        Reads the features layer in batches and writes one multipoint per
        feature, at full coordinate precision. Features without a geometry or
        with an unknown location are skipped.

        :param gpkg_path: Path of the extracted GeoPackage.
        :param writer: Writer the geometry triples are added to.
        """
        total = pyogrio.read_info(gpkg_path, layer=self.LAYER)["features"]
        for offset in range(0, total, self.BATCH_SIZE):
            _, _, wkb, (feature_ids,) = pyogrio.raw.read(
                gpkg_path,
                layer=self.LAYER,
                columns=["feature_id"],
                force_2d=True,
                skip_features=offset,
                max_features=self.BATCH_SIZE,
            )
            for feature_id, geometry in zip(
                feature_ids.tolist(), shapely.from_wkb(wkb)
            ):
                if geometry is None or geometry.is_empty:
                    continue
                coordinates = shapely.get_coordinates(geometry)
                if abs(coordinates).max() < self.UNKNOWN_LOCATION_TOLERANCE:
                    continue
                wkt = shapely.to_wkt(geometry, rounding_precision=-1)
                self._add_geometry(writer, FeatureIds.normalize(feature_id), wkt)

    def _add_geometry(self, writer: NTriplesWriter, feature_id: str, wkt: str) -> None:
        """
        Writes the feature's geosparql:hasGeometry triple and its multipoint's
        geosparql:asWKT triple.

        :param writer: Writer the triples are added to.
        :param feature_id: Canonical feature id, as used in gnisf: IRIs.
        :param wkt: 2D multipoint WKT, without a CRS prefix.
        """
        prefixes = self.config.prefix_list
        geosparql = prefixes["geosparql"]
        geometry = prefixes["usgeo-multipoint"][f"gnisf.{feature_id}"]
        writer.add((prefixes["gnisf"][feature_id], geosparql["hasGeometry"], geometry))
        writer.add((geometry, geosparql["asWKT"], Terms.wkt_literal(wkt)))
