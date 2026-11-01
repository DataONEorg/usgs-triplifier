from collections.abc import Callable
from typing import ClassVar

from rdflib import Literal

from ...output_files import OutputFiles
from ...usgs_products import UsgsProduct, UsgsProducts
from .identifiers import FeatureIds
from .rdf import NTriplesWriter
from .triplifier import FieldDescriptor, Triplifier


class HistoryTriplifier(Triplifier):
    """
    Converts the GNIS feature descriptions and histories
    into history.nt.gz as gnis:description and gnis:history literals.
    """

    product: ClassVar[UsgsProduct] = UsgsProducts.HISTORY
    output_name: ClassVar[str] = OutputFiles.HISTORY

    def fields(self) -> dict[str, FieldDescriptor | Callable]:
        """
        Lists the description and history columns.

        :return: Mapping of column name to its field mapping.
        """
        return {
            "description": FieldDescriptor(
                "gnis:description", self.text_object, optional=True
            ),
            "history": FieldDescriptor("gnis:history", self.text_object, optional=True),
        }

    def subject(self, row: dict[str, str], writer: NTriplesWriter) -> str:
        """
        Builds the IRI of the feature the description and history belong to.

        :param row: Source row.
        :param writer: Writer the row's triples go to (unused).
        :return: The feature's gnisf: IRI.
        """
        return f"gnisf:{FeatureIds.normalize(row.get('feature_id', ''))}"

    def text_object(self, value: str, row: dict) -> Literal | str:
        """
        Builds a description or history literal.

        :param value: The text.
        :param row: Source row (unused).
        :return: The text without surrounding whitespace as an English
            literal, or an empty string when it is blank.
        """
        text = value.strip()
        return Literal(text, lang="en") if text else ""
