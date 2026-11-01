import gzip
import logging
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from ..config import Config
from ..output_files import OutputFiles


class RetentionBuilder:
    """
    Keeps the records of features that are no longer in the USGS products,
    so their URIs keep resolving.

    The release being built is compared with every earlier release in the
    archive output directory, so a release built out of order (a legacy dump
    added after later releases) is covered too. A feature is a subject with a
    gnis:featureId line. A subject that only has crosswalk links is not one.
    A feature in an earlier file but not in the new release is dropped, and
    its record is copied to retained-features.nt.gz from the newest earlier
    file that has it. The record is the alias lines whose object is the
    feature, then the feature's own lines, the blank nodes they reference and
    the geometries its geosparql:hasGeometry points at. An alias that is a
    subject in the new release belongs to a current feature and is not
    copied. A disambiguation alias is copied only when every feature it
    disambiguates is dropped, and the records of those features are written
    one after the other. A feature copied from a release file gets rdf:type
    usgs:HistoricalFeature and gnis:lastAppearedIn with that release's IRI.
    A feature copied from the newest earlier historical release file keeps
    the ones it has.

    State, county and country unit records, whose subjects are gnisf-alias:
    IRIs, are copied unchanged when their alias is not a subject in the new
    release.
    """

    # Maximum passes over a file to collect the blank nodes that retained
    # lines reference. Retained blank nodes are one level deep (feature to
    # elevation), so the loop normally stops after two passes.
    MAX_CLOSURE_PASSES: ClassVar[int] = 5

    RDF_TYPE: ClassVar[str] = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
    OWL_SAMEAS: ClassVar[str] = "<http://www.w3.org/2002/07/owl#sameAs>"
    HAS_GEOMETRY: ClassVar[str] = "<http://www.opengis.net/ont/geosparql#hasGeometry>"

    # Local names of the unit classes under gnis:
    UNIT_CLASSES: ClassVar[tuple[str, ...]] = ("State", "County", "Country")

    _log: ClassVar[logging.Logger] = logging.getLogger(__name__)

    def __init__(self, config: Config) -> None:
        """
        Creates the builder.

        :param config: Settings holding the output and archive output
            directories and lod_base.
        """
        self.config = config
        lod = config.lod_base
        self._feature_prefix = f"<{lod}/gnis/feature/"
        self._feature_id = f"<{lod}/gnis/ontology/featureId>"
        self._disambiguates_to = f"<{lod}/gnis/ontology/disambiguatesTo>"
        self._unit_classes = {
            f"<{lod}/gnis/ontology/{name}>" for name in self.UNIT_CLASSES
        }
        self._historical_class = f"<{lod}/usgs/ontology/HistoricalFeature>"
        self._last_appeared = f"<{lod}/gnis/ontology/lastAppearedIn>"

    def build(self, build_time: datetime) -> Path | None:
        """
        Writes retained-features.nt.gz to the output directory from the
        release files in the output directory and the archive.

        :param build_time: Time the release being built is dated with.
        :return: Path of the file, or None when nothing is retained. When the
            archive has no earlier release, no file is written; otherwise the
            file is written even when it is empty.
        """
        release_id = OutputFiles.release_id(build_time)
        archive_dir = self.config.archive_output_directory
        earlier = self._earlier(archive_dir, OutputFiles.RELEASE, release_id)
        if not earlier:
            return None
        earlier_historical = self._earlier(
            archive_dir, OutputFiles.HISTORICAL_RELEASE, release_id
        )

        new_subjects, covered = self._new_release_subjects()
        # Features and units not to copy: those in the new release, and those
        # already copied from a newer file
        covered_units: set[str] = set()

        sources: list[tuple[Path, str | None]] = []
        if earlier_historical:
            sources.append((earlier_historical[0], None))
        for path in earlier:
            path_id = OutputFiles.RELEASE.match(path.name)[1]
            sources.append((path, f"{self.config.lod_base}/gnis/release/{path_id}"))

        count = 0
        path = self.config.output_directory / OutputFiles.RETAINED
        with gzip.open(path, "wt", encoding="utf-8") as out:
            for source, release_iri in sources:
                records = self._records(source, new_subjects, covered, covered_units)
                for owner, lines in records.items():
                    if release_iri and owner.startswith(self._feature_prefix):
                        lines.append(
                            f"{owner} {self.RDF_TYPE} {self._historical_class} ."
                        )
                        lines.append(f"{owner} {self._last_appeared} <{release_iri}> .")
                    for line in lines:
                        out.write(line + "\n")
                    count += len(lines)
                self._log.info(f"Retained {len(records)} records from {source.name}")
        return path if count else None

    @staticmethod
    def _earlier(archive_dir: Path, pattern: re.Pattern, release_id: str) -> list[Path]:
        """
        Lists the files in the archive whose name matches a release file
        pattern and whose release id is earlier than release_id.

        :param archive_dir: Archive output directory.
        :param pattern: OutputFiles.RELEASE or OutputFiles.HISTORICAL_RELEASE.
        :param release_id: Id of the release being built.
        :return: The files, newest release first.
        """
        candidates = [
            (m[1], path)
            for path in archive_dir.glob("*.nt.gz")
            if (m := pattern.match(path.name)) and m[1] < release_id
        ]
        return [path for _, path in sorted(candidates, reverse=True)]

    @staticmethod
    def _lines(path: Path) -> Iterator[str]:
        """
        Yields the triple lines of a gzipped N-Triples file.

        :param path: The file.
        :return: Iterator of lines without surrounding whitespace, skipping
            blank lines and comments.
        """
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    yield line

    @staticmethod
    def _terms(line: str) -> tuple[str, str, str]:
        """
        Splits an N-Triples line into its subject, predicate and object.

        :param line: N-Triples line without surrounding whitespace.
        :return: (subject, predicate, object), the object without the
            closing " .".
        """
        subject, rest = line.split(" ", 1)
        predicate, obj = rest.split(" ", 1)
        return subject, predicate, obj[:-2].strip()

    def _new_release_subjects(self) -> tuple[set[str], set[str]]:
        """
        Collects the IRI subjects of the release being built, from the
        .nt.gz files in the output directory other than the retained file.

        :return: (all IRI subjects, the subjects with a gnis:featureId line),
            in angle brackets.
        """
        subjects: set[str] = set()
        features: set[str] = set()
        for path in sorted(self.config.output_directory.glob("*.nt.gz")):
            if path.name == OutputFiles.RETAINED:
                continue
            for line in self._lines(path):
                subject, rest = line.split(" ", 1)
                if subject.startswith("<"):
                    subjects.add(subject)
                    if rest.startswith(self._feature_id):
                        features.add(subject)
        return subjects, features

    def _records(
        self,
        source: Path,
        new_subjects: set[str],
        covered: set[str],
        covered_units: set[str],
    ) -> dict[str, list[str]]:
        """
        Collects the records to retain from one earlier file, grouped by the
        feature or unit they belong to.

        :param source: Earlier release or historical release file.
        :param new_subjects: IRI subjects of the release being built.
        :param covered: Feature IRIs not to retain; the ones retained from
            this file are added.
        :param covered_units: Unit alias IRIs not to retain; the ones
            retained from this file are added.
        :return: Owner IRI -> its lines. The records of the features of one
            disambiguation alias follow each other. Within a record the alias
            lines come first, then the other lines in file order.
        """
        # Pass 1: the dropped features and units, the geometries the dropped
        # features point at, and the blank nodes their lines reference
        candidates: set[str] = set()
        features: set[str] = set()
        units: set[str] = set()
        owner_of: dict[str, str] = {}
        for subject, predicate, obj in map(self._terms, self._lines(source)):
            if subject.startswith(self._feature_prefix):
                if subject in covered:
                    continue
                candidates.add(subject)
                if predicate == self._feature_id:
                    features.add(subject)
                elif obj.startswith("_:") or (predicate == self.HAS_GEOMETRY):
                    owner_of[obj] = subject
            elif (
                predicate == self.RDF_TYPE
                and obj in self._unit_classes
                and subject not in new_subjects
                and subject not in covered_units
            ):
                units.add(subject)
        dropped = candidates & features
        owner_of = {node: owner for node, owner in owner_of.items() if owner in dropped}
        if not dropped and not units:
            return {}

        # Further passes: blank nodes referenced by owned blank nodes
        for _ in range(self.MAX_CLOSURE_PASSES - 1):
            added = False
            for subject, _, obj in map(self._terms, self._lines(source)):
                if subject in owner_of and obj.startswith("_:") and obj not in owner_of:
                    owner_of[obj] = owner_of[subject]
                    added = True
            if not added:
                break

        # Final pass: the lines, grouped by owner. Alias lines are kept apart
        # so they can go first in the record, and the lines of a
        # disambiguation alias are kept together until all of its features
        # are known to be dropped.
        records: dict[str, list[str]] = {unit: [] for unit in sorted(units)}
        alias_lines: dict[str, list[str]] = {}
        disambiguations: dict[str, list[tuple[str, str]]] = {}
        for line in self._lines(source):
            subject, predicate, obj = self._terms(line)
            if subject in dropped or subject in units:
                records.setdefault(subject, []).append(line)
            elif subject in owner_of:
                records.setdefault(owner_of[subject], []).append(line)
            elif subject in new_subjects or not obj.startswith(self._feature_prefix):
                continue
            elif predicate == self.OWL_SAMEAS and obj in dropped:
                alias_lines.setdefault(obj, []).append(line)
            elif predicate == self._disambiguates_to:
                disambiguations.setdefault(subject, []).append((obj, line))

        group_of: dict[str, list[str]] = {}
        for members in disambiguations.values():
            if all(feature in dropped for feature, _ in members):
                group = [feature for feature, _ in members]
                for feature, line in members:
                    alias_lines.setdefault(feature, []).append(line)
                    group_of[feature] = group

        ordered: dict[str, list[str]] = {}
        for owner in records:
            for feature in group_of.get(owner, [owner]):
                if feature not in ordered:
                    ordered[feature] = alias_lines.get(feature, []) + records[feature]

        covered |= dropped
        covered_units |= units
        return ordered
