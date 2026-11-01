import gzip
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from ..config import Config
from ..output_files import OutputFiles


class ReleaseExporter:
    """
    Writes a release's files to the archive output directory.

    Each release file comes with a gnis-ld-<yymmdd>.meta.json beside it with its
    id, publication date, triple count and size. A file is written under a
    temporary name and renamed to its final name after its sidecar, so the
    website, which lists the directory, never sees a release file that is
    incomplete or has no sidecar.
    """

    # Suffix of a file while it is being written
    PART_SUFFIX: ClassVar[str] = ".part"

    def __init__(self, config: Config) -> None:
        """
        Creates the exporter.

        :param config: Settings holding the output and archive output directories.
        """
        self.config = config

    def export_release(self, build_time: datetime) -> Path:
        """
        Writes the release file, gnis-ld-<yymmdd>.nt.gz.

        :param build_time: Time the release is dated with.
        :return: Path of the release file.
        """
        release_id = OutputFiles.release_id(build_time)
        path = self._archive_dir() / OutputFiles.release(release_id)
        part_path = self._part(path)

        triples = 0
        with gzip.open(part_path, "wt", encoding="utf-8") as out:
            # Concatenate the generated files, except retained-features.nt.gz,
            # into the release file, counting one triple per line
            for nt_path in sorted(self.config.output_directory.glob("*.nt.gz")):
                if nt_path.name == OutputFiles.RETAINED:
                    continue
                with gzip.open(nt_path, "rt", encoding="utf-8") as f:
                    for line in f:
                        out.write(line)
                        triples += 1

        self._publish(part_path, path, build_time, triples)
        return path

    def export_historical(self, build_time: datetime) -> Path:
        """
        Writes the historical release file, gnis-ld-historical-<yymmdd>.nt.gz.

        :param build_time: Time the release is dated with.
        :return: Path of the historical release file.
        :raises FileNotFoundError: If retained-features.nt.gz has not been written.
        """
        release_id = OutputFiles.release_id(build_time)
        path = self._archive_dir() / OutputFiles.historical_release(release_id)
        part_path = self._part(path)

        retained_path = self.config.output_directory / OutputFiles.RETAINED
        with gzip.open(retained_path, "rt", encoding="utf-8") as f:
            triples = sum(1 for line in f if line.strip())
        shutil.copyfile(retained_path, part_path)

        self._publish(part_path, path, build_time, triples)
        return path

    def _archive_dir(self) -> Path:
        """
        Returns the archive output directory, creating it if missing and
        deleting the temporary files of an earlier run that did not finish.

        :return: The directory.
        """
        archive_dir = self.config.archive_output_directory
        archive_dir.mkdir(parents=True, exist_ok=True)
        for stale in archive_dir.glob(f"gnis-ld-*{self.PART_SUFFIX}"):
            stale.unlink()
        return archive_dir

    @classmethod
    def _part(cls, path: Path) -> Path:
        """
        Builds the temporary name a file is written under.

        :param path: Final path of the file.
        :return: The path with PART_SUFFIX appended.
        """
        return path.with_name(path.name + cls.PART_SUFFIX)

    def _publish(
        self, part_path: Path, path: Path, build_time: datetime, triples: int
    ) -> None:
        """
        Writes the sidecar for a finished and closed temporary file, writes
        both to disk, then renames the sidecar and the file to their final
        names, sidecar first.

        :param part_path: The finished temporary file.
        :param path: Final path of the file.
        :param build_time: Time the release is dated with.
        :param triples: Number of triples in the file.
        """
        sidecar = {
            "id": OutputFiles.release_id(build_time),
            "published": build_time.date().isoformat(),
            "triples": f"{triples:,}",
            "size": self.format_size(part_path.stat().st_size),
        }
        sidecar_path = OutputFiles.sidecar_for(path)
        sidecar_part = self._part(sidecar_path)
        sidecar_part.write_text(json.dumps(sidecar, indent=2) + "\n")
        for written in (part_path, sidecar_part):
            with open(written, "rb") as f:
                os.fsync(f.fileno())
        os.replace(sidecar_part, sidecar_path)
        os.replace(part_path, path)

    @staticmethod
    def format_size(n_bytes: int) -> str:
        """
        Formats a file size in decimal units, with one decimal place for MB
        and GB and at least 1 KB.

        :param n_bytes: Size in bytes.
        :return: The size, e.g. "3.5 MB".
        """
        if n_bytes >= 1e9:
            return f"{n_bytes / 1e9:.1f} GB"
        if n_bytes >= 1e6:
            return f"{n_bytes / 1e6:.1f} MB"
        return f"{max(1, round(n_bytes / 1e3))} KB"
