import gzip
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path
from typing import ClassVar

from ..config import Config
from .gnis.identifiers import FeatureIds


class Crosswalk(ABC):
    """
    Links GNIS features to records in another dataset and writes the links
    to a gzipped N-Triples file in the output directory.

    The links are written as N-Triples lines without rdflib, because they
    are built from strings in large batches. A crosswalk whose source cannot
    be reached writes no file.
    """

    OWL_SAMEAS: ClassVar[str] = "<http://www.w3.org/2002/07/owl#sameAs>"
    SKOS_CLOSEMATCH: ClassVar[str] = "<http://www.w3.org/2004/02/skos/core#closeMatch>"

    # Name of the file the links are written to, in the output directory
    output_name: ClassVar[str]

    _log: ClassVar[logging.Logger] = logging.getLogger(__name__)

    def __init__(self, config: Config) -> None:
        """
        Creates the crosswalk.

        :param config: Settings holding the output directory, the base IRI of
            the features, and the crosswalk's source settings.
        """
        self.config = config

    @property
    def output_path(self) -> Path:
        """
        Builds the path of the file the links are written to.

        :return: output_name in the output directory.
        """
        return self.config.output_directory / self.output_name

    @abstractmethod
    def build(self) -> Path | None:
        """
        Fetches the other dataset and writes the links.

        :return: Path of the written file, or None when the source could not
            be reached and nothing was written.
        """

    def feature_iri(self, feature_id: str) -> str:
        """
        Builds the N-Triples term of a GNIS feature's IRI.

        :param feature_id: GNIS feature id, as given by the other dataset.
        :return: The IRI in angle brackets, e.g. <http://gnis-ld.org/lod/gnis/feature/1414314>.
        """
        return (
            f"<{self.config.lod_base}/gnis/feature/{FeatureIds.normalize(feature_id)}>"
        )

    def write_lines(self, lines: Iterable[str]) -> int:
        """
        Writes N-Triples lines to the output file, replacing any existing file.

        :param lines: Iterable of N-Triples lines without line endings.
        :return: Number of lines written.
        """
        count = 0
        with gzip.open(self.output_path, "wt", encoding="utf-8") as out:
            for line in lines:
                out.write(line + "\n")
                count += 1
        self._log.info(f"Wrote {count} links to {self.output_path.name}")
        return count
