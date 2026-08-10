from pathlib import Path
from typing import ClassVar

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings
from rdflib import Namespace


_default_data_dir = Path(__file__).parent.parent / "data"


class Config(BaseSettings):
    lod_base: str = Field(default="http://gnis-ld.org/lod", alias="LOD_BASE")
    geo_base: str = Field(default="http://gnis-ld.org/geometry", alias="GEO_BASE")

    # Input directory for downloaded GNIS data
    input_directory: Path = Field(
        default=_default_data_dir / "geographic_names", alias="GNIS_INPUT_DIRECTORY"
    )

    # Output directory for generated RDF files
    output_directory: Path = Field(
        default=_default_data_dir / "output" / "gnis", alias="RDF_OUTPUT_DIRECTORY"
    )

    # Static prefixes that don't depend on config values
    _static_prefixes: ClassVar[dict[str, Namespace]] = {
        "rdf": Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#"),
        "rdfs": Namespace("http://www.w3.org/2000/01/rdf-schema#"),
        "owl": Namespace("http://www.w3.org/2002/07/owl#"),
        "xsd": Namespace("http://www.w3.org/2001/XMLSchema#"),
        "geosparql": Namespace("http://www.opengis.net/ont/geosparql#"),
        "qudt": Namespace("http://qudt.org/schema/qudt/"),
        "unit": Namespace("http://qudt.org/vocab/unit/"),
        "ago": Namespace("http://awesemantic-geo.link/ontology/"),
        "geonames": Namespace("http://sws.geonames.org/"),
    }

    @computed_field
    @property
    def prefix_list(self) -> dict[str, Namespace]:
        return {
            **self._static_prefixes,
            "usgs": Namespace(f"{self.lod_base}/usgs/ontology/"),
            "gnis": Namespace(f"{self.lod_base}/gnis/ontology/"),
            "gnisf": Namespace(f"{self.lod_base}/gnis/feature/"),
            "gnisf-alias": Namespace(f"{self.lod_base}/gnis/feature-alias/"),
            "nhd": Namespace(f"{self.lod_base}/nhd/ontology/"),
            "nhdf": Namespace(f"{self.lod_base}/nhd/feature/"),
            "usgeo-point": Namespace(f"{self.geo_base}/point/"),
            "usgeo-multipoint": Namespace(f"{self.geo_base}/multipoint/"),
            "usgeo-linestring": Namespace(f"{self.geo_base}/linestring/"),
            "usgeo-multilinestring": Namespace(f"{self.geo_base}/multilinestring/"),
            "usgeo-polygon": Namespace(f"{self.geo_base}/polygon/"),
            "usgeo-multipolygon": Namespace(f"{self.geo_base}/multipolygon/"),
        }

    model_config = {"populate_by_name": True}


config = Config()
