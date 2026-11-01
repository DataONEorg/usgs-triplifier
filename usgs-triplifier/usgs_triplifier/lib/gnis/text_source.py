import csv
import io
import logging
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar


class TextSource:
    """
    Reads the rows of the pipe-delimited text files inside zips.

    Header names are stripped and lowercased, because legacy dumps use
    uppercase headers and the current products lowercase ones.
    """

    _log: ClassVar[logging.Logger] = logging.getLogger(__name__)

    def __init__(self, zip_paths: list[Path], quoting: int = csv.QUOTE_MINIMAL) -> None:
        """
        Creates a source over zips.

        :param zip_paths: The zips, read in this order.
        :param quoting: csv quoting mode of the files. See
            UsgsProducts.quoting_for.
        """
        self.zip_paths = zip_paths
        self.quoting = quoting

    def rows(self) -> Iterator[dict[str, str]]:
        """
        Yields every row of every .txt file in the zips, in file order.

        :return: Iterator of rows, each a mapping of lowercase column name to value.
        """
        for zip_path in self.zip_paths:
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = [n for n in zf.namelist() if n.endswith(".txt")]
                if not names:
                    self._log.warning(f"No text files in {zip_path.name}")
                for name in names:
                    self._log.info(f"Reading {name} from {zip_path.name}")
                    yield from self._read(zf, name)

    def _read(self, zf: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
        """
        Yields the rows of one text file in a zip.

        :param zf: Open zip file.
        :param name: Name of the text file inside the zip.
        :return: Iterator of rows.
        """
        with (
            zf.open(name) as raw,
            io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as f,
        ):
            reader = csv.DictReader(f, delimiter="|", quoting=self.quoting, restval="")
            reader.fieldnames = [n.strip().lower() for n in reader.fieldnames or []]
            yield from reader
