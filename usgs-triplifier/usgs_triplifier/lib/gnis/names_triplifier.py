import re
from collections.abc import Callable
from typing import ClassVar

from rdflib import Literal

from ...output_files import OutputFiles
from ...usgs_products import UsgsProduct, UsgsProducts
from .identifiers import FeatureIds
from .rdf import NTriplesWriter
from .triplifier import FieldDescriptor, Triplifier


class NamesTriplifier(Triplifier):
    """
    Converts the GNIS names (AllNames) into names.nt.gz.

    Each row is one name of a feature. The official name becomes the
    feature's rdfs:label and gnis:officialName, with its gnis:citation and
    gnis:dateNameCreated; every other name becomes a gnis:alternativeName.
    """

    product: ClassVar[UsgsProduct] = UsgsProducts.NAMES
    output_name: ClassVar[str] = OutputFiles.NAMES

    # Citation values USGS writes for a name without a citation. "Unknown"
    # followed by more text names a source whose type is unknown and is kept.
    UNKNOWN_CITATION: ClassVar[re.Pattern] = re.compile(
        r"^((Map |Text )?Citation Unknown|Unknown)$"
    )

    def fields(self) -> dict[str, FieldDescriptor | Callable]:
        """
        Lists the name columns that become triples.

        :return: Mapping of column name to its field mapping.
        """
        return {
            "feature_name": self.feature_name_field,
            "citation": FieldDescriptor(
                "gnis:citation", self.citation_object, optional=True
            ),
            "date_created": FieldDescriptor(
                "gnis:dateNameCreated", self.date_created_object, optional=True
            ),
        }

    def subject(self, row: dict[str, str], writer: NTriplesWriter) -> str:
        """
        Builds the IRI of the feature the name belongs to.

        :param row: Source row.
        :param writer: Writer the row's triples go to (unused).
        :return: The feature's gnisf: IRI.
        """
        return f"gnisf:{FeatureIds.normalize(row.get('feature_id', ''))}"

    def feature_name_field(
        self, value: str, row: dict, writer: NTriplesWriter
    ) -> dict | None:
        """
        Builds rdfs:label and gnis:officialName for the official name, or
        gnis:alternativeName for any other name.

        :param value: The name.
        :param row: Source row.
        :param writer: Writer the row's triples go to (unused).
        :return: The predicate-object pairs, or None when the name is empty.
        """
        if not value:
            return None
        name = Literal(value, lang="en")
        if self._is_official(row):
            return {"rdfs:label": [name], "gnis:officialName": [name]}
        return {"gnis:alternativeName": [name]}

    def citation_object(self, value: str, row: dict) -> Literal | str:
        """
        Builds the gnis:citation of an official name.

        :param value: Citation text. Surrounding whitespace is removed.
        :param row: Source row.
        :return: The citation as an English literal, "gnis:UnknownCitation"
            when USGS gives "Citation Unknown", which the current products
            prefix with the source type ("Text Citation Unknown"), or an
            empty string for a name that is not official or a blank citation.
        """
        citation = value.strip()
        if not self._is_official(row) or not citation:
            return ""
        if self.UNKNOWN_CITATION.match(citation):
            return "gnis:UnknownCitation"
        return Literal(citation, lang="en")

    def date_created_object(self, value: str, row: dict) -> Literal | str:
        """
        Builds the gnis:dateNameCreated of an official name.

        :param value: Date as MM/DD/YYYY or ISO 8601.
        :param row: Source row.
        :return: An xsd:date literal, or an empty string for a name that is
            not official, a blank date, or a date in neither format.
        """
        if not self._is_official(row) or not value.strip():
            return ""
        return self.date_literal(value) or ""

    @staticmethod
    def _is_official(row: dict) -> bool:
        """
        Checks whether the row's name is the feature's official name.

        The current products mark names "Official" or "Variant"; legacy
        dumps mark them "Y" or "N". The comparison ignores case.

        :param row: Source row.
        :return: True for the official name, False otherwise.
        """
        return row.get("feature_name_official", "").lower() in ("official", "y")
