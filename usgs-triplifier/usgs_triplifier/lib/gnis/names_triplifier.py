"""
GNIS Names Triplifier Configuration.

Processes GNIS text files (AllNames_*.txt from zip archives) and generates
RDF triples for feature names (official and alternative names), citations,
and date created.
"""

from datetime import datetime

from rdflib import Graph, Literal
from rdflib.namespace import XSD

from .text_triplifier import triplify_text_files
from .triplifier import TriplifierConfig, FieldDescriptor, normalize_feature_id
from ...config import config


class NamesTriplifier:
    """
    Triplifier for GNIS names from text files.

    Uses the AllNames_*.txt files from the topical text zip archives which contain:
        - feature_id, feature_name
        - feature_name_official ("Official" or "Variant")
        - citation, date_created
    """

    def __init__(self):
        # Column mappings for text file processing
        field_mappings = {
            "feature_name": NamesTriplifier.feature_name_field,
            "citation": FieldDescriptor(
                predicate="gnis:citation",
                object=NamesTriplifier.citation_object,
                optional=True,
            ),
            "date_created": FieldDescriptor(
                predicate="gnis:dateNameCreated",
                object=NamesTriplifier.date_created_object,
                optional=True,
            ),
        }
        triples_config = TriplifierConfig(
            subject=self.get_subject,
            fields=field_mappings,
        )
        # Run triplifier on AllNames text zip file
        triplify_text_files(triples_config, "AllNames*_Text.zip", "names")

    @staticmethod
    def get_subject(row: dict, graph: Graph) -> str | None:
        """
        Generate subject IRI for a GNIS feature.

        :param row: Dictionary representing a row from the text file.
        :param graph: RDF graph (unused but required by interface).
        :return: Subject IRI string or None if invalid.
        """
        return f"gnisf:{normalize_feature_id(row.get('feature_id', ''))}"

    @staticmethod
    def feature_name_field(value: str, row: dict, graph: Graph) -> dict | None:
        """
        Process feature name based on whether it's official or alternative.

        :param value: Feature name value.
        :param row: Dictionary representing a row from the text file.
        :param graph: RDF graph (unused but required by interface).
        :return: Dictionary of predicate-object pairs or None if no value.
        """
        if not value:
            return None

        # Text files use "Official" or "Variant" strings
        is_official = NamesTriplifier._is_official(row)

        if is_official:
            # Official name: add as label and official name
            return {
                "rdfs:label": [Literal(value, lang="en")],
                "gnis:officialName": [Literal(value, lang="en")],
            }
        else:
            # Alternative name
            return {
                "gnis:alternativeName": [Literal(value, lang="en")],
            }

    @staticmethod
    def citation_object(value: str, row: dict, graph: Graph) -> Literal | str:
        """
        Convert citation to literal (only for official names).

        :param value: Citation text value.
        :param row: Dictionary representing a row from the text file.
        :param graph: RDF graph (unused but required by interface).
        :return: RDF Literal or URIRef for unknown citation, or empty string.
        """
        # Only process citation for official names
        if not NamesTriplifier._is_official(row):
            return ""

        if not value or value.strip() == "":
            return ""

        if value == "Citation Unknown":
            return "gnis:UnknownCitation"

        return Literal(value, lang="en")

    @staticmethod
    def date_created_object(value: str, row: dict, graph: Graph) -> Literal | str:
        """
        Convert date created to XSD date literal (only for official names).

        :param value: Date string value (MM/DD/YYYY format in text files).
        :param row: Dictionary representing a row from the text file.
        :param graph: RDF graph (unused but required by interface).
        :return: RDF Literal with XSD date datatype or empty string.
        """
        # Only process date for official names
        if not NamesTriplifier._is_official(row):
            return ""

        if not value or value.strip() == "":
            return ""

        try:
            # Text files use MM/DD/YYYY format
            dt = datetime.strptime(value, "%m/%d/%Y")
            return Literal(dt.strftime("%Y-%m-%d"), datatype=XSD.date)
        except ValueError:
            return Literal(value)

    @staticmethod
    def _is_official(row: dict) -> bool:
        """
        Check if the name is official based on the row data.

        Handles both text file format ("Official"/"Variant") and
        GPKG format (1/0).

        :param row: Dictionary representing a row.
        :return: True if official name, False if variant.
        """
        is_official = row.get("feature_name_official")
        if isinstance(is_official, (int, float)):
            return int(is_official) == 1
        else:
            # Text files use "Official" or "Variant"
            return str(is_official).lower() == "official"


def main():
    """Run the names triplifier."""
    # Ensure output directory exists
    config.output_directory.mkdir(parents=True, exist_ok=True)
    NamesTriplifier()


if __name__ == "__main__":
    main()
