import csv
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import ClassVar


@dataclass(frozen=True)
class UsgsProduct:
    """
    A USGS GNIS file the pipeline reads.

    :param key: S3 key of the current file in the USGS bucket.
    :param pattern: Glob matching the current file in the input directory.
    :param legacy_key: S3 key of the legacy dump file, or None when legacy
        dumps have no such file.
    :param legacy_pattern: Glob matching the legacy dump file in the input
        directory, or None when legacy dumps have no such file.
    """

    key: str
    pattern: str
    legacy_key: str | None = None
    legacy_pattern: str | None = None

    def pattern_for(self, legacy_dump: bool) -> str:
        """
        Returns the glob that matches the product's zip in the input directory.

        :param legacy_dump: Whether the input directory holds a legacy dump.
        :return: The legacy pattern for a legacy dump, otherwise the current one.
        :raises ValueError: If legacy_dump is True and legacy dumps have no
            such product.
        """
        if not legacy_dump:
            return self.pattern
        if self.legacy_pattern is None:
            raise ValueError(f"Legacy dumps have no equivalent of {self.key}")
        return self.legacy_pattern

    def zip_paths(self, directory: Path, legacy_dump: bool) -> list[Path]:
        """
        Finds the product's zips in a directory.

        A legacy pattern can also match the current product's zip (AllNames*.zip
        matches AllNames_National_Text.zip), so for a legacy dump the zips
        matching the current pattern are left out.

        :param directory: Directory holding the zips.
        :param legacy_dump: Whether the directory holds a legacy dump.
        :return: The matching zips in name order; empty when there are none.
        :raises ValueError: If legacy_dump is True and legacy dumps have no
            such product.
        """
        paths = sorted(directory.glob(self.pattern_for(legacy_dump)))
        if legacy_dump:
            paths = [p for p in paths if not fnmatch(p.name, self.pattern)]
        return paths


class UsgsProducts:
    """
    The USGS GNIS files the pipeline reads.
    """

    BUCKET: ClassVar[str] = "prd-tnm"
    S3_BASE: ClassVar[str] = f"https://{BUCKET}.s3.amazonaws.com"

    # Date of the legacy dump under the legacy keys. USGS no longer updates
    # that format, so the legacy keys always contain this dump.
    LEGACY_DUMP_DATE: ClassVar[str] = "2021-08-25"

    GEOPACKAGE: ClassVar[UsgsProduct] = UsgsProduct(
        key="StagedProducts/GeographicNames/FullModel/Gazetteer_National_GPKG.zip",
        pattern="*_GPKG.zip",
    )
    FEATURES: ClassVar[UsgsProduct] = UsgsProduct(
        key="StagedProducts/GeographicNames/DomesticNames/DomesticNames_National_Text.zip",
        pattern="DomesticNames*_Text.zip",
        legacy_key="StagedProducts/GeographicNames/Archive/MainDomestic/NationalFile.zip",
        legacy_pattern="NationalFile*.zip",
    )
    NAMES: ClassVar[UsgsProduct] = UsgsProduct(
        key="StagedProducts/GeographicNames/Topical/AllNames_National_Text.zip",
        pattern="AllNames*_Text.zip",
        legacy_key="StagedProducts/GeographicNames/Archive/TopicalGazetteers/AllNames.zip",
        legacy_pattern="AllNames*.zip",
    )
    UNITS: ClassVar[UsgsProduct] = UsgsProduct(
        key="StagedProducts/GeographicNames/Topical/GovernmentUnits_National_Text.zip",
        pattern="GovernmentUnits*_Text.zip",
        legacy_key="StagedProducts/GeographicNames/Archive/TopicalGazetteers/GOVT_UNITS.zip",
        legacy_pattern="GOVT_UNITS*.zip",
    )
    HISTORY: ClassVar[UsgsProduct] = UsgsProduct(
        key="StagedProducts/GeographicNames/Topical/FeatureDescriptionHistory_National_Text.zip",
        pattern="FeatureDescriptionHistory*_Text.zip",
        legacy_key="StagedProducts/GeographicNames/Archive/TopicalGazetteers/Feature_Description_History.zip",
        legacy_pattern="Feature_Description_History*.zip",
    )

    @staticmethod
    def quoting_for(legacy_dump: bool) -> int:
        """
        Returns the csv quoting mode the text products are read with.

        The current products wrap a field in double quotes when it contains a
        double quote or a line break, doubling the quotes inside it. Legacy
        dumps never wrap fields, and a field may start with a double quote
        that is part of the value.

        :param legacy_dump: Whether the input directory holds a legacy dump.
        :return: csv.QUOTE_NONE for a legacy dump, otherwise csv.QUOTE_MINIMAL.
        """
        return csv.QUOTE_NONE if legacy_dump else csv.QUOTE_MINIMAL

    @classmethod
    def text_products(cls) -> list[UsgsProduct]:
        """
        Lists the text products.

        :return: The features, names, units and history products.
        """
        return [cls.FEATURES, cls.NAMES, cls.UNITS, cls.HISTORY]

    @classmethod
    def download_keys(cls, legacy_dump: bool = False) -> list[str]:
        """
        Lists the S3 keys of the files a release is built from, in download
        order.

        :param legacy_dump: Whether the release is built from a legacy dump.
        :return: The legacy dump files for a legacy dump, otherwise the
            GeoPackage key followed by the current text product keys.
        """
        if legacy_dump:
            return [p.legacy_key for p in cls.text_products()]
        return [cls.GEOPACKAGE.key, *(p.key for p in cls.text_products())]

    @classmethod
    def source_urls(cls, legacy_dump: bool) -> list[str]:
        """
        Lists the URLs of the USGS files a release is built from.

        :param legacy_dump: Whether the release is built from a legacy dump.
        :return: The legacy dump files for a legacy dump, otherwise the
            current products including the GeoPackage.
        """
        return [f"{cls.S3_BASE}/{key}" for key in cls.download_keys(legacy_dump)]
