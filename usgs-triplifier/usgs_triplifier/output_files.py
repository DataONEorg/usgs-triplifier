import re
from datetime import datetime
from pathlib import Path
from typing import ClassVar


class OutputFiles:
    """
    Names of the files the pipeline writes.
    """

    # RDF written by the triplifiers
    FEATURES: ClassVar[str] = "features.nt.gz"
    FEATURE_ALIASES: ClassVar[str] = "feature-aliases.nt.gz"
    NAMES: ClassVar[str] = "names.nt.gz"
    HISTORY: ClassVar[str] = "history.nt.gz"
    UNITS: ClassVar[str] = "units.nt.gz"
    GEOMETRIES: ClassVar[str] = "geometries.nt.gz"

    # Files written by the crosswalks
    WIKIDATA_CROSSWALK: ClassVar[str] = "crosswalk.nt.gz"
    GEONAMES_CROSSWALK: ClassVar[str] = "geonames-crosswalk.nt.gz"
    CENSUS_CROSSWALK: ClassVar[str] = "census-crosswalk.nt.gz"
    WIKIDATA_GEONAMES_PAIRS: ClassVar[str] = "wikidata-geonames.csv"
    GEONAMES_QA_REPORT: ClassVar[str] = "geonames-qa-disagreements.csv"

    # The gnis and usgs ontologies, written as N-Triples so they are released
    # and loaded with the data
    ONTOLOGY_GNIS: ClassVar[str] = "ontology-gnis.nt.gz"
    ONTOLOGY_USGS: ClassVar[str] = "ontology-usgs.nt.gz"

    # Subdirectory of the archive output directory that gets the Turtle
    # copies of the ontologies, which the website serves
    ONTOLOGY_ARCHIVE_DIR: ClassVar[str] = "ontologies"

    # Records kept from earlier releases for features no longer in the USGS
    # products.
    RETAINED: ClassVar[str] = "retained-features.nt.gz"

    # VoID/DCAT
    METADATA: ClassVar[str] = "dataset-metadata.ttl"

    # Release files in the archive output directory
    # These are named by release id (YYMMDD)
    RELEASE: ClassVar[re.Pattern] = re.compile(r"^gnis-ld-(\d{6})\.nt\.gz$")
    HISTORICAL_RELEASE: ClassVar[re.Pattern] = re.compile(
        r"^gnis-ld-historical-(\d{6})\.nt\.gz$"
    )

    @staticmethod
    def release_id(build_time: datetime) -> str:
        """
        Builds the id of the release dated with a build time.

        :param build_time: Time the release is dated with.
        :return: The date as YYMMDD, e.g. 260701.
        """
        return build_time.strftime("%y%m%d")

    @staticmethod
    def release(release_id: str) -> str:
        """
        Builds the file name of a release's release file.

        :param release_id: Release id (YYMMDD).
        :return: The file name, e.g. gnis-ld-260701.nt.gz.
        """
        return f"gnis-ld-{release_id}.nt.gz"

    @staticmethod
    def historical_release(release_id: str) -> str:
        """
        Builds the file name of a release's historical release file.

        :param release_id: Release id (YYMMDD).
        :return: The file name, e.g. gnis-ld-historical-260701.nt.gz.
        """
        return f"gnis-ld-historical-{release_id}.nt.gz"

    @staticmethod
    def sidecar_for(release_path: Path) -> Path:
        """
        Builds the path of the .meta.json file that describes a release file.

        :param release_path: Path of a release or historical release file.
        :return: The path with .nt.gz replaced by .meta.json.
        """
        return release_path.with_name(release_path.name.replace(".nt.gz", ".meta.json"))
