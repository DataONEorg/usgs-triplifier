import io
import logging
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pandas as pd
import requests

from ..output_files import OutputFiles
from .crosswalk import Crosswalk


class CensusCrosswalk(Crosswalk):
    """
    Links GNIS counties and places to their Census GEOIDs, using the Census
    Bureau's national gazetteer files.

    Each feature gets at most one GEOID. An independent city, such as
    Virginia Beach, is listed in both the county and the place file under one
    ANSI code, and gets its county GEOID. An ANSI code listed twice in one
    file belongs to two Census entities, so no feature can be linked from
    it and the code is skipped.
    """

    output_name: ClassVar[str] = OutputFiles.CENSUS_CROSSWALK

    # Gazetteer files read, without the "<year>_" prefix of their names. A
    # GEOID from a later file replaces one from an earlier file for the same
    # ANSI code, so the county file is last.
    GAZETTEER_FILES: ClassVar[list[str]] = [
        "Gaz_place_national.zip",
        "Gaz_counties_national.zip",
    ]

    _log: ClassVar[logging.Logger] = logging.getLogger(__name__)

    def build(self) -> Path | None:
        """
        Downloads the gazetteer files and writes the links.

        :return: Path of the written file, or None when a gazetteer file
            could not be downloaded or read.
        """
        year = self.config.census_gazetteer_year
        frames = []
        for name in self.GAZETTEER_FILES:
            url = f"{self.config.census_gazetteer_base}/{year}_Gazetteer/{year}_{name}"
            try:
                response = requests.get(url, timeout=300)
                response.raise_for_status()
                frames.append(self._read_gazetteer(response.content))
            except (requests.RequestException, zipfile.BadZipFile, KeyError) as error:
                self._log.warning(
                    f"Census gazetteer {url} unavailable; writing no Census links: {error}"
                )
                return None

        self.write_lines(self._links(self._geoids(frames)))
        return self.output_path

    def _geoids(self, gazetteers: list[pd.DataFrame]) -> dict[str, str]:
        """
        Maps the ANSI codes of the gazetteer files to one GEOID each.

        :param gazetteers: Rows with GEOID and ANSICODE columns, one frame
            per file, in the order of GAZETTEER_FILES.
        :return: ANSI code without leading zeros -> GEOID.
        """
        geoids: dict[str, str] = {}
        for gazetteer in gazetteers:
            codes: dict[str, list[str]] = {}
            for row in gazetteer.itertuples():
                ansi = str(row.ANSICODE).strip()
                geoid = str(row.GEOID).strip()
                if ansi.isdigit() and geoid:
                    codes.setdefault(ansi.lstrip("0"), []).append(geoid)
            for ansi, file_geoids in codes.items():
                if len(file_geoids) > 1:
                    self._log.warning(
                        f"ANSI code {ansi} has the GEOIDs {', '.join(file_geoids)} "
                        "in one gazetteer file and is not linked"
                    )
                    geoids.pop(ansi, None)
                else:
                    geoids[ansi] = file_geoids[0]
        return geoids

    def _links(self, geoids: dict[str, str]) -> Iterator[str]:
        """
        Yields the two link lines of every feature with a GEOID.

        :param geoids: ANSI code -> GEOID.
        :return: Iterator of N-Triples lines.
        """
        geoid_property = f"<{self.config.lod_base}/gnis/ontology/censusGeoid>"
        for ansi, geoid in geoids.items():
            feature = self.feature_iri(ansi)
            yield f'{feature} {geoid_property} "{geoid}" .'
            yield (
                f"{feature} {self.OWL_SAMEAS} "
                f"<https://datacommons.org/browser/geoId/{geoid}> ."
            )

    @staticmethod
    def _read_gazetteer(zip_bytes: bytes) -> pd.DataFrame:
        """
        Reads the GEOID and ANSICODE columns of a zipped gazetteer file.

        The files are tab-delimited up to 2024 and pipe-delimited from 2025,
        so the delimiter is taken from the header line. Some years pad the
        header names with whitespace, which is stripped so the columns can be
        selected by name.

        :param zip_bytes: Contents of the zip file.
        :return: Rows with both a GEOID and an ANSICODE.
        :raises KeyError: If either column is missing.
        :raises zipfile.BadZipFile: If the bytes are not a zip file.
        """
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = [n for n in zf.namelist() if n.endswith(".txt")]
            raw = zf.read(names[0])
        header = raw.split(b"\n", 1)[0]
        frame = pd.read_csv(
            io.BytesIO(raw),
            sep="|" if b"|" in header else "\t",
            dtype=str,
            encoding="latin-1",
            quoting=3,
        )
        frame.columns = [c.strip() for c in frame.columns]
        return frame[["GEOID", "ANSICODE"]].dropna()
