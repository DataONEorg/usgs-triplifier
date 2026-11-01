import logging
import os
from pathlib import Path
from typing import ClassVar

from rdflib import Graph

from ..config import Config
from ..output_files import OutputFiles
from .gnis.rdf import NTriplesWriter


class OntologyWriter:
    """
    Writes the gnis and usgs ontologies to the output directory as gzipped
    N-Triples, so they are released and loaded with the data, and to the
    archive output directory as Turtle, which the website serves.
    """

    # Directory holding the vendored Turtle files
    ONTOLOGIES_DIR: ClassVar[Path] = Path(__file__).parent.parent / "ontologies"

    # Base IRI written in the Turtle files; replaced with lod_base when loaded
    SOURCE_LOD_BASE: ClassVar[str] = "http://gnis-ld.org/lod"

    # Website IRI written in the Turtle files (rdfs:seeAlso); replaced with
    # site_base when loaded
    SOURCE_SITE_BASE: ClassVar[str] = "https://gnis-ld.org"

    # Turtle file name -> output file name
    FILES: ClassVar[dict[str, str]] = {
        "gnis.ttl": OutputFiles.ONTOLOGY_GNIS,
        "usgs.ttl": OutputFiles.ONTOLOGY_USGS,
    }

    _log: ClassVar[logging.Logger] = logging.getLogger(__name__)

    def __init__(self, config: Config) -> None:
        """
        Creates the writer.

        :param config: Settings holding the output and archive output
            directories, lod_base and site_base.
        """
        self.config = config

    def write(self) -> list[Path]:
        """
        Writes every ontology in FILES as N-Triples to the output directory,
        with the triples in sorted order so two runs produce identical files,
        and as Turtle under ONTOLOGY_ARCHIVE_DIR in the archive output
        directory.

        :return: Paths of the N-Triples files.
        """
        archive_dir = (
            self.config.archive_output_directory / OutputFiles.ONTOLOGY_ARCHIVE_DIR
        )
        archive_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for source_name, output_name in self.FILES.items():
            text = self.source_text(source_name)
            path = self.config.output_directory / output_name
            with NTriplesWriter(path) as writer:
                for triple in sorted(Graph().parse(data=text, format="turtle")):
                    writer.add(triple)
            self._log.info(f"Wrote {len(writer)} ontology triples to {path}")
            paths.append(path)

            # Written under a temporary name and renamed, so the website
            # never serves a partly written file
            turtle_path = archive_dir / source_name
            part_path = turtle_path.with_name(source_name + ".part")
            part_path.write_text(text, encoding="utf-8")
            os.replace(part_path, turtle_path)
        return paths

    def source_text(self, source_name: str) -> str:
        """
        Reads a vendored ontology with its base IRI replaced by lod_base and
        its website IRI by site_base.

        :param source_name: File name in ONTOLOGIES_DIR, e.g. "gnis.ttl".
        :return: The Turtle text.
        """
        text = (self.ONTOLOGIES_DIR / source_name).read_text(encoding="utf-8")
        text = text.replace(self.SOURCE_LOD_BASE, self.config.lod_base)
        return text.replace(self.SOURCE_SITE_BASE, self.config.site_base)

    def load(self, source_name: str) -> Graph:
        """
        Parses a vendored ontology with its IRIs rewritten as in source_text.

        :param source_name: File name in ONTOLOGIES_DIR, e.g. "gnis.ttl".
        :return: The ontology graph.
        """
        return Graph().parse(data=self.source_text(source_name), format="turtle")
