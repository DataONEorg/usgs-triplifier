import gzip
import logging
from pathlib import Path
from typing import Any, ClassVar

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import GEO
from rdflib.plugins.serializers.nt import _nt_row


class NTriplesWriter:
    """
    Writes triples to a gzipped N-Triples file. It works as a context manager over the file.
    """

    def __init__(self, path: Path) -> None:
        """
        Creates a writer for a file.

        :param path: Path of the gzipped N-Triples file. Its parent directory
            is created if missing.
        """
        self.path = path
        self._out = None
        self._count = 0

    def __enter__(self) -> "NTriplesWriter":
        """
        Opens the file for writing, replacing any existing file.

        :return: The writer.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._out = gzip.open(self.path, "wt", encoding="utf-8")
        return self

    def __exit__(self, *exc_info: object) -> None:
        """
        Closes the file.

        :param exc_info: Exception details from the with block.
        """
        self._out.close()
        self._out = None

    def add(self, triple: tuple) -> None:
        """
        Writes one triple as an N-Triples line.

        :param triple: (subject, predicate, object) rdflib terms.
        """
        self._out.write(_nt_row(triple))
        self._count += 1

    def __len__(self) -> int:
        """
        Counts the triples written so far.

        :return: Number of add() calls.
        """
        return self._count


class Terms:
    """
    Converts the term notation used in field mappings into rdflib terms and
    writes them to a writer.

    The notation is a string whose first character selects the term type.

        - ``>http://...``     an IRI given in full
        - ``"text``           a plain literal
        - ``@en"text``        a language-tagged literal
        - ``^xsd:double"1.5`` a typed literal; the datatype is a prefixed name
        - ``prefix:local``    an IRI built from one of the prefixes it was created with
        - anything else      a plain literal
    """

    # CRS IRI written before every WKT literal, so the coordinates are read as
    # longitude/latitude in WGS 84
    CRS84: ClassVar[str] = "<http://www.opengis.net/def/crs/OGC/1.3/CRS84>"

    _log: ClassVar[logging.Logger] = logging.getLogger(__name__)

    def __init__(self, prefixes: dict[str, Namespace]) -> None:
        """
        Creates a converter for a set of prefixes.

        :param prefixes: Prefix -> namespace, as given by Config.prefix_list.
        """
        self.prefixes = prefixes

    def resolve_iri(self, text: str) -> URIRef:
        """
        Converts an IRI in the notation to a URIRef.

        :param text: ``>`` followed by a full IRI, or ``prefix:local`` with a
            known prefix. Any other string, including one
            with an unknown prefix, is used as the IRI unchanged.
        :return: The IRI.
        """
        if text.startswith(">"):
            return URIRef(text[1:])
        if ":" in text:
            prefix, local = text.split(":", 1)
            if prefix in self.prefixes:
                return self.prefixes[prefix][local]
        return URIRef(text)

    def parse_object(self, text: str) -> URIRef | Literal:
        """
        Converts an object in the notation to an rdflib term.

        :param text: Object in the notation described on the class.
        :return: The IRI or literal.
        """
        if text.startswith(">"):
            return URIRef(text[1:])
        if text.startswith('"'):
            return Literal(text[1:])
        if text.startswith("@"):
            lang, value = text[1:].split('"', 1)
            return Literal(value, lang=lang)
        if text.startswith("^"):
            datatype, value = text[1:].split('"', 1)
            return Literal(value, datatype=self.resolve_iri(datatype))
        if ":" in text:
            return self.resolve_iri(text)
        return Literal(text)

    def add_object(
        self,
        writer: NTriplesWriter | Graph,
        subject: URIRef | BNode,
        predicate: URIRef,
        obj: Any,
    ) -> None:
        """
        Writes the triple(s) for one object of a subject and predicate.

        An rdflib term is written as given and a string is parsed with
        parse_object. A dict becomes a blank node that is the object of the
        triple and the subject of the dict's predicate-object pairs. Any other
        type is logged and skipped.

        :param writer: Writer (or rdflib Graph) the triples are added to.
        :param subject: Subject term.
        :param predicate: Predicate IRI.
        :param obj: The object.
        """
        if isinstance(obj, (URIRef, Literal)):
            writer.add((subject, predicate, obj))
        elif isinstance(obj, str):
            writer.add((subject, predicate, self.parse_object(obj)))
        elif isinstance(obj, dict):
            node = BNode()
            writer.add((subject, predicate, node))
            self.add_pairs(writer, node, obj)
        else:
            self._log.warning(f"Skipping unsupported object type {type(obj)!r}: {obj}")

    def add_pairs(
        self, writer: NTriplesWriter | Graph, subject: URIRef | BNode, pairs: dict
    ) -> None:
        """
        Writes the triples for a mapping of predicates to objects.

        :param writer: Writer (or rdflib Graph) the triples are added to.
        :param subject: Subject term.
        :param pairs: Mapping of predicate, in the notation, to one object or
            a list of objects.
        """
        for predicate, objects in pairs.items():
            if not isinstance(objects, list):
                objects = [objects]
            for obj in objects:
                self.add_object(writer, subject, self.resolve_iri(predicate), obj)

    @classmethod
    def wkt_literal(cls, wkt: str) -> Literal:
        """
        Builds a geosparql:wktLiteral with the CRS84 prefix.

        :param wkt: 2D WKT geometry, e.g. ``POINT(-117.2 34.5)``.
        :return: The literal.
        """
        return Literal(f"{cls.CRS84}{wkt}", datatype=GEO.wktLiteral)
