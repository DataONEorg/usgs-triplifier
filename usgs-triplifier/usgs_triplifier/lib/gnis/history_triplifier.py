from rdflib import Graph, Literal

from .triplifier import (
    triplify_all,
    TriplifierConfig,
    FieldDescriptor,
    normalize_feature_id,
)
from ...config import config


class HistoryTriplifier:
    """
    Abstraction over triplifying the Gaz_Features table (histories)

    Uses the Gaz_Features table from GPKG files which contains:
        - feature_id, feature_class
        - description, history
        - date_created, date_edited
    """

    def __init__(self):
        # Column mappings
        field_mappings = {
            "description": FieldDescriptor(
                predicate="gnis:description",
                object=HistoryTriplifier.create_description,
                optional=True,
            ),
            "history": FieldDescriptor(
                predicate="gnis:history",
                object=HistoryTriplifier.create_history,
                optional=True,
            ),
        }
        triples_mapping = TriplifierConfig(
            subject=self.get_subject,
            fields=field_mappings,
        )

        triplify_all(triples_mapping, "Gaz_Features", "history")

    @staticmethod
    def get_subject(row: dict, graph: Graph) -> str | None:
        """
        Generate subject IRI for a GNIS feature.

        :param row: Dictionary representing a row from the GPKG table.
        :param graph: RDF graph (unused but required by interface).
        :return: Subject IRI string or None if invalid.
        """
        return f"gnisf:{normalize_feature_id(row.get('feature_id', ''))}"

    @staticmethod
    def create_description(value: str, row: dict, graph: Graph) -> Literal | str:
        """
        Convert description to language-tagged literal.

        :param value: Description text value.
        :param row: Dictionary representing a row from the GPKG table.
        :param graph: RDF graph (unused but required by interface).
        :return: RDF Literal with English language tag or empty string if no value.
        """
        # Skip empty or whitespace-only descriptions
        if not value or value.strip() == "":
            return ""
        return Literal(value.strip(), lang="en")

    @staticmethod
    def create_history(value: str, row: dict, graph: Graph) -> Literal | str:
        """
        Convert history to language-tagged literal.

        :param value: History text value.
        :param row: Dictionary representing a row from the GPKG table.
        :param graph: RDF graph (unused but required by interface).
        :return: RDF Literal with English language tag or empty string if no value.
        """
        # Skip empty or whitespace-only history
        if not value or value.strip() == "":
            return ""
        return Literal(value.strip(), lang="en")


def main():
    """Run the history triplifier."""
    config.output_directory.mkdir(parents=True, exist_ok=True)
    HistoryTriplifier()


if __name__ == "__main__":
    main()
