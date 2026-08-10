"""
GNIS Triplifier - Converts GNIS data to RDF triples.

This module extracts GNIS data from GeoPackage files (inside zip archives)
and converts them to RDF Turtle format.
"""

import logging
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import geopandas as gpd
from rdflib import BNode, Graph, Literal, URIRef
from tqdm import tqdm

from ...config import config

logger = logging.getLogger(__name__)


@dataclass
class FieldDescriptor:
    """Describes how to map a field to RDF predicates/objects."""

    predicate: str
    object: Callable[[str, dict, Graph], Any] | None = None
    optional: bool = False


@dataclass
class TriplifierConfig:
    """Configuration for the triplifier."""

    subject: Callable[[dict, Graph], str | None]
    fields: dict[str, FieldDescriptor | Callable]


def normalize_feature_id(raw: Any) -> str:
    """
    Normalize a feature id to the canonical string form used in gnisf: IRIs.

    :param raw: Feature id as read from a GPKG table or text file.
    :return: Canonical feature id string.
    """
    if isinstance(raw, (int, float)):
        return str(int(raw))
    return str(raw).lstrip("0") or "0"


def clean(s: str) -> str:
    """
    Clean IRIs by replacing non-word characters with underscores.

    :param s: String to clean.
    :return: Cleaned string with non-word characters replaced by underscores.
    """
    return re.sub(r"[^\w]", "_", s)


def get_gpkg_zip_files(pattern: str = "*_GPKG.zip") -> list[Path]:
    """
    Get list of GPKG zip files from the input directory.

    :param pattern: Glob pattern to match zip files.
    :return: List of paths to zip files.
    """
    return sorted(config.input_directory.glob(pattern))


def triplify_all(
    triplifier_config: TriplifierConfig,
    table_name: str,
    output_basename: str = "output",
) -> Graph:
    """
    Process all GPKG zip files in the input directory.

    :param triplifier_config: Triplifier configuration.
    :param table_name: Name of the table to read from each GPKG file.
    :param output_basename: Basename for output file.
    :return: Graph holding the combined triples.
    """
    zip_files = get_gpkg_zip_files()

    if not zip_files:
        raise ValueError(f"No GPKG zip files found in {config.input_directory}")

    print(f"Found {len(zip_files)} GPKG zip files")

    # Create a single triplifier for combined output
    output_dir = config.output_directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize RDF graph with prefixes
    graph = Graph()
    for prefix, ns in config.prefix_list.items():
        graph.bind(prefix, ns)

    # Process each zip file
    for zip_path in zip_files:
        logger.info(f"Processing {zip_path.name}")

        with zipfile.ZipFile(zip_path, "r") as zf:
            gpkg_files = [f for f in zf.namelist() if f.endswith(".gpkg")]

            if not gpkg_files:
                logger.debug("No GPKG file found, skipping")
                continue

            with tempfile.TemporaryDirectory() as tmpdir:
                for gpkg_file in gpkg_files:
                    zf.extract(gpkg_file, tmpdir)
                    gpkg_path = Path(tmpdir) / gpkg_file

                    logger.debug(f"Reading table {table_name}")
                    gdf = gpd.read_file(gpkg_path, layer=table_name, engine="pyogrio")

                    pbar = tqdm(
                        total=len(gdf),
                        unit="rows",
                        desc="Processing",
                        bar_format="{l_bar}{bar:40}{r_bar}",
                    )

                    for _, row in gdf.iterrows():
                        row_dict = row.to_dict()
                        subject_iri = triplifier_config.subject(row_dict, graph)

                        if not subject_iri:
                            pbar.update(1)
                            continue

                        subject = _resolve_iri(subject_iri)

                        for field_name, descriptor in triplifier_config.fields.items():
                            value = row_dict.get(field_name)

                            if value is None or (
                                isinstance(value, float) and value != value
                            ):
                                value = ""
                            else:
                                value = (
                                    str(value) if not isinstance(value, str) else value
                                )

                            if callable(descriptor) and not isinstance(
                                descriptor, FieldDescriptor
                            ):
                                pairs = descriptor(value, row_dict, graph)
                                if pairs:
                                    _add_pairs(graph, subject, pairs)
                            elif isinstance(descriptor, FieldDescriptor):
                                if not value:
                                    if descriptor.optional:
                                        continue
                                    raise ValueError(
                                        f'Missing value for column "{field_name}"'
                                    )
                                if descriptor.predicate and descriptor.object:
                                    predicate = _resolve_iri(descriptor.predicate)
                                    obj = descriptor.object(value, row_dict, graph)
                                    if obj:
                                        _add_triple(graph, subject, predicate, obj)

                        pbar.update(1)

                    pbar.close()

    # Write combined output
    output_path = output_dir / f"{output_basename}.ttl"
    graph.serialize(destination=str(output_path), format="turtle")
    logger.info(f"Output written to {output_path}")
    return graph


def _resolve_iri(iri_str: str) -> URIRef:
    """
    Resolve a prefixed IRI string to a full URIRef.

    :param iri_str: IRI string, possibly prefixed (e.g., 'gnisf:123').
    :return: Full URIRef representing the node.
    """
    if iri_str.startswith(">"):
        return URIRef(iri_str[1:])
    if ":" in iri_str:
        prefix, local = iri_str.split(":", 1)
        if prefix in config.prefix_list:
            ns = config.prefix_list[prefix]
            if hasattr(ns, "__getitem__"):
                return ns[local]
            return URIRef(str(ns) + local)
    return URIRef(iri_str)


def _add_pairs(graph: Graph, subject: URIRef, pairs: dict) -> None:
    """
    Add predicate-object pairs for a subject.

    :param graph: RDF graph to add triples to.
    :param subject: Subject node.
    :param pairs: Dictionary of predicate -> list of objects.
    """
    for predicate_str, objects in pairs.items():
        predicate = _resolve_iri(predicate_str)
        if not isinstance(objects, list):
            objects = [objects]
        for obj in objects:
            _add_triple(graph, subject, predicate, obj)


def _add_triple(graph: Graph, subject: URIRef, predicate: URIRef, obj: Any) -> None:
    """
    Add a single triple to the graph.

    Dict objects become a blank node whose predicate-object pairs are added
    recursively (e.g. an elevation node with qudt:numericValue/qudt:unit).

    :param graph: RDF graph to add the triple to.
    :param subject: Subject node.
    :param predicate: Predicate URIRef.
    :param obj: Object (string notation, URIRef, Literal, or nested dict).
    """
    if isinstance(obj, (URIRef, Literal)):
        graph.add((subject, predicate, obj))
    elif isinstance(obj, str):
        parsed_obj = _parse_object(obj)
        graph.add((subject, predicate, parsed_obj))
    elif isinstance(obj, dict):
        node = BNode()
        graph.add((subject, predicate, node))
        _add_pairs(graph, node, obj)
    else:
        logger.warning(f"Skipping unsupported object type {type(obj)!r}: {obj}")


def _parse_object(obj_str: str) -> URIRef | Literal:
    """
    Parse a graphy-style object notation.

    Notation:
        - '"value' -> plain literal
        - '@lang"value' -> language-tagged literal
        - '^datatype"value' -> typed literal
        - 'prefix:local' -> named node
        - '>uri' -> full URI

    :param obj_str: Object string in graphy notation.
    :return: Parsed URIRef or Literal.
    """
    if obj_str.startswith(">"):
        return URIRef(obj_str[1:])
    elif obj_str.startswith('"'):
        return Literal(obj_str[1:])
    elif obj_str.startswith("@"):
        lang_end = obj_str.index('"')
        lang = obj_str[1:lang_end]
        value = obj_str[lang_end + 1 :]
        return Literal(value, lang=lang)
    elif obj_str.startswith("^"):
        type_end = obj_str.index('"')
        datatype_str = obj_str[1:type_end]
        value = obj_str[type_end + 1 :]
        datatype = _resolve_iri(datatype_str)
        return Literal(value, datatype=datatype)
    elif ":" in obj_str:
        return _resolve_iri(obj_str)
    else:
        return Literal(obj_str)
