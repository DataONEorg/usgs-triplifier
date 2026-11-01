import gzip
import hashlib
import logging
import os
from pathlib import Path
from typing import ClassVar

from ..config import Config
from ..output_files import OutputFiles


class Deduplicator:
    """
    Removes repeated triples from the generated N-Triples files.

    The same triple can be written more than once, within a file or by two
    files. Each file is rewritten keeping only the first occurrence of every
    line across all of them, in file name order. retained-features.nt.gz is
    not rewritten.
    """

    _log: ClassVar[logging.Logger] = logging.getLogger(__name__)

    def __init__(self, config: Config) -> None:
        """
        Creates the deduplicator.

        :param config: Settings holding the output directory.
        """
        self.config = config

    def run(self) -> int:
        """
        Rewrites every .nt.gz in the output directory without repeated lines.

        :return: Number of lines removed across all files.
        """
        # Holds 16-byte digests of the lines instead of the lines, because a
        # full run has tens of millions of lines
        seen: set[int] = set()
        removed = 0
        for path in sorted(self.config.output_directory.glob("*.nt.gz")):
            if path.name != OutputFiles.RETAINED:
                removed += self._dedupe_file(path, seen)
        self._log.info(f"Removed {removed} duplicate triples")
        return removed

    @staticmethod
    def _dedupe_file(path: Path, seen: set[int]) -> int:
        """
        Rewrites one file keeping only the lines whose digest is not in seen.

        :param path: Gzipped N-Triples file, replaced in place.
        :param seen: Digests of the lines kept so far; the file's kept lines are added.
        :return: Number of lines removed from the file.
        """
        tmp_path = path.with_name(path.name + ".tmp")
        removed = 0
        with (
            gzip.open(path, "rt", encoding="utf-8") as f_in,
            gzip.open(tmp_path, "wt", encoding="utf-8") as f_out,
        ):
            for line in f_in:
                digest = int.from_bytes(
                    hashlib.blake2b(line.encode("utf-8"), digest_size=16).digest(),
                    "big",
                )
                if digest in seen:
                    removed += 1
                    continue
                seen.add(digest)
                f_out.write(line)
        os.replace(tmp_path, path)
        return removed
