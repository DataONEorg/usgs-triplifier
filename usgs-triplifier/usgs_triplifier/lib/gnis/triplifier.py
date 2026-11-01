import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

from rdflib import Literal
from rdflib.namespace import XSD

from ...config import Config
from ...usgs_products import UsgsProduct, UsgsProducts
from .rdf import NTriplesWriter, Terms
from .text_source import TextSource


@dataclass
class FieldDescriptor:
    """
    Maps one source column to one triple about the row's subject.

    :param predicate: Predicate in the term notation of Terms, e.g. "gnis:state".
    :param object: Function that builds the triple's object from the column.
        Called with the column's value and the whole row.
    :param optional: When False, a row with an empty value for the column
        raises ValueError. When True, the column is skipped for that row.
    """

    predicate: str
    object: Callable[[str, dict], Any]
    optional: bool = False


class Triplifier(ABC):
    """
    Converts one GNIS text product into a gzipped N-Triples file in the
    output directory.
    """

    product: ClassVar[UsgsProduct]
    output_name: ClassVar[str]

    _log: ClassVar[logging.Logger] = logging.getLogger(__name__)

    def __init__(self, config: Config) -> None:
        """
        Creates the triplifier.

        :param config: Settings holding the input and output directories, the
            base IRIs, and whether the input is a legacy dump.
        """
        self.config = config
        self.terms = Terms(config.prefix_list)

    def run(self) -> int:
        """
        Writes the triples for every row of the product.

        :return: Number of triples written.
        :raises FileNotFoundError: If the input directory has no zip for the product.
        :raises ValueError: If a row has no value for a required column, or
            its feature id is not a number.
        """
        legacy_dump = self.config.legacy_dump
        zip_paths = self.product.zip_paths(self.config.input_directory, legacy_dump)
        if not zip_paths:
            raise FileNotFoundError(
                f"No zip files matching {self.product.pattern_for(legacy_dump)} "
                f"in {self.config.input_directory}"
            )
        source = TextSource(zip_paths, UsgsProducts.quoting_for(legacy_dump))
        fields = self.fields()
        with NTriplesWriter(self.config.output_directory / self.output_name) as writer:
            for row in source.rows():
                self._write_row(row, fields, writer)
        self._log.info(f"Wrote {len(writer)} triples to {writer.path}")
        return len(writer)

    @abstractmethod
    def subject(self, row: dict[str, str], writer: NTriplesWriter) -> str | None:
        """
        Builds the IRI of the resource a row describes. Runs before the
        row's fields, so it may add values to the row for them to use.

        :param row: Source row.
        :param writer: Writer the row's triples go to.
        :return: Subject IRI in the term notation, or None to skip the row.
        """

    @abstractmethod
    def fields(self) -> dict[str, FieldDescriptor | Callable]:
        """
        Lists the columns that become triples and how.

        :return: Mapping of column name to its FieldDescriptor or field callable.
        """

    @staticmethod
    def plain_literal(value: str, row: dict) -> Literal:
        """
        Builds a plain literal of a column value.

        :param value: Column value.
        :param row: Source row (unused).
        :return: The value as a plain literal.
        """
        return Literal(value)

    @staticmethod
    def english_literal(value: str, row: dict) -> Literal:
        """
        Builds an English literal of a column value.

        :param value: Column value. Surrounding whitespace is removed.
        :param row: Source row (unused).
        :return: The value as an English literal.
        """
        return Literal(value.strip(), lang="en")

    @classmethod
    def date_literal(cls, value: str) -> Literal | None:
        """
        Builds an xsd:date literal from a date column value.

        :param value: Date as MM/DD/YYYY, or an ISO 8601 date or timestamp
            such as 1998-10-06T06:13:42.
        :return: The literal, or None when the value is in neither format,
            which is logged.
        """
        text = value.strip()
        try:
            if "/" in text:
                date = datetime.strptime(text, "%m/%d/%Y")
            else:
                date = datetime.fromisoformat(text)
        except ValueError:
            cls._log.warning(
                f"Skipping date {value!r}, which is not MM/DD/YYYY or ISO 8601"
            )
            return None
        return Literal(date.strftime("%Y-%m-%d"), datatype=XSD.date)

    def _write_row(
        self,
        row: dict[str, str],
        fields: dict[str, FieldDescriptor | Callable],
        writer: NTriplesWriter,
    ) -> None:
        """
        Writes the triples for one row.

        :param row: Source row.
        :param fields: The mappings from fields().
        :param writer: Writer the triples are added to.
        :raises ValueError: If a required column has no value.
        """
        subject_iri = self.subject(row, writer)
        if not subject_iri:
            return
        subject = self.terms.resolve_iri(subject_iri)

        for column, mapping in fields.items():
            value = row.get(column) or ""

            if not isinstance(mapping, FieldDescriptor):
                pairs = mapping(value, row, writer)
                if pairs:
                    self.terms.add_pairs(writer, subject, pairs)
                continue

            if not value:
                if mapping.optional:
                    continue
                raise ValueError(f'Missing value for column "{column}"')
            obj = mapping.object(value, row)
            if obj:
                self.terms.add_object(
                    writer, subject, self.terms.resolve_iri(mapping.predicate), obj
                )
