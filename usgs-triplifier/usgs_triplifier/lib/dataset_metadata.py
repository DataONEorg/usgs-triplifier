import json
from datetime import datetime
from importlib import metadata as importlib_metadata
from pathlib import Path

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import DCAT, DCTERMS, PROV, RDF, RDFS, VOID, XSD

from ..config import Config
from ..output_files import OutputFiles
from ..usgs_products import UsgsProducts


class DatasetMetadataWriter:
    """
    Writes dataset-metadata.ttl, the VoID/DCAT description of GNIS-LD and its
    releases, to the output directory.
    """

    def __init__(self, config: Config) -> None:
        """
        Creates the writer.

        :param config: Settings holding lod_base, site_base, the output and
            archive output directories, and whether the input is a legacy dump.
        """
        self.config = config

    def write(
        self,
        build_time: datetime,
        release_path: Path | None = None,
        historical_path: Path | None = None,
    ) -> Path:
        """
        Writes the description of the dataset and its releases.

        :param build_time: Time the release being built is dated with.
        :param release_path: The release file, described as a download, or
            None when it has not been exported.
        :param historical_path: The historical release file, described the
            same way, or None when there is none.
        :return: Path of dataset-metadata.ttl.
        """
        release_id = OutputFiles.release_id(build_time)
        dataset = URIRef(f"{self.config.lod_base}/gnis")

        graph = Graph()
        for prefix, namespace in {
            "void": VOID,
            "dcat": DCAT,
            "dcterms": DCTERMS,
            "prov": PROV,
        }.items():
            graph.bind(prefix, namespace)

        graph.add((dataset, RDF.type, VOID.Dataset))
        graph.add((dataset, RDF.type, DCAT.Dataset))
        graph.add((dataset, DCTERMS.title, Literal("USGS GNIS Linked Data", lang="en")))

        release = self._add_release(
            graph, dataset, release_id, build_time.date().isoformat()
        )
        graph.add(
            (
                release,
                DCTERMS.created,
                Literal(build_time.isoformat(), datatype=XSD.dateTime),
            )
        )

        activity = BNode()
        graph.add((release, PROV.wasGeneratedBy, activity))
        graph.add((activity, RDF.type, PROV.Activity))
        graph.add((activity, RDFS.label, Literal(f"usgs-triplifier {self._version()}")))

        for url in UsgsProducts.source_urls(self.config.legacy_dump):
            graph.add((release, DCTERMS.source, URIRef(url)))

        for path in (release_path, historical_path):
            if path is not None:
                self._add_download(graph, release, path)

        # One distribution per generated file, except retained-features.nt.gz,
        # which is published as the historical release file
        for nt_path in sorted(self.config.output_directory.glob("*.nt.gz")):
            if nt_path.name == OutputFiles.RETAINED:
                continue
            distribution = URIRef(f"{release}/{nt_path.name.replace('.nt.gz', '')}")
            graph.add((release, DCAT.distribution, distribution))
            graph.add((distribution, RDF.type, DCAT.Distribution))
            graph.add((distribution, DCTERMS.title, Literal(nt_path.name)))
            graph.add(
                (
                    distribution,
                    DCAT.byteSize,
                    Literal(nt_path.stat().st_size, datatype=XSD.integer),
                )
            )

        self._add_earlier_releases(graph, dataset, release_id)

        path = self.config.output_directory / OutputFiles.METADATA
        graph.serialize(destination=str(path), format="turtle")
        return path

    def _add_release(
        self, graph: Graph, dataset: URIRef, release_id: str, issued: str
    ) -> URIRef:
        """
        Describes a release and links it to the dataset.

        :param graph: Graph the triples are added to.
        :param dataset: The dataset's IRI.
        :param release_id: Release id (YYMMDD).
        :param issued: Release date as YYYY-MM-DD, written as dcterms:issued.
        :return: The release's IRI.
        """
        release = URIRef(f"{self.config.lod_base}/gnis/release/{release_id}")
        graph.add((dataset, DCTERMS.hasVersion, release))
        graph.add((release, RDF.type, VOID.Dataset))
        graph.add((release, RDF.type, DCAT.Dataset))
        graph.add((release, DCTERMS.isVersionOf, dataset))
        graph.add((release, DCTERMS.identifier, Literal(release_id)))
        graph.add((release, DCTERMS.issued, Literal(issued, datatype=XSD.date)))
        return release

    def _add_download(self, graph: Graph, release: URIRef, path: Path) -> None:
        """
        Describes a release or historical release file.

        :param graph: Graph the triples are added to.
        :param release: IRI of the release the file belongs to.
        :param path: The file.
        """
        url = URIRef(f"{self.config.site_base}/archive/{path.name}")
        graph.add((release, DCAT.distribution, url))
        graph.add((url, RDF.type, DCAT.Distribution))
        graph.add((url, DCTERMS.title, Literal(path.name)))
        graph.add((url, DCAT.downloadURL, url))
        graph.add((url, DCAT.mediaType, Literal("application/n-triples")))
        graph.add((url, DCAT.compressFormat, Literal("application/gzip")))
        graph.add(
            (url, DCAT.byteSize, Literal(path.stat().st_size, datatype=XSD.integer))
        )

    def _add_earlier_releases(
        self, graph: Graph, dataset: URIRef, skip_id: str
    ) -> None:
        """
        Describes every release in the archive output directory except the one
        being built, with its release and historical release files.

        :param graph: Graph the triples are added to.
        :param dataset: The dataset's IRI.
        :param skip_id: Id of the release being built.
        """
        archive_dir = self.config.archive_output_directory
        if not archive_dir.is_dir():
            return
        for path in sorted(archive_dir.glob("*.nt.gz")):
            match = OutputFiles.RELEASE.match(path.name)
            if not match or match[1] == skip_id:
                continue
            release_id = match[1]
            release = self._add_release(
                graph, dataset, release_id, self._published(path, release_id)
            )
            self._add_download(graph, release, path)
            historical = path.with_name(OutputFiles.historical_release(release_id))
            if historical.exists():
                self._add_download(graph, release, historical)

    @staticmethod
    def _published(path: Path, release_id: str) -> str:
        """
        Reads a release's date from its .meta.json, or derives it from the
        release id when that file is missing or unreadable.

        :param path: Release file.
        :param release_id: Release id (YYMMDD).
        :return: The date as YYYY-MM-DD.
        """
        try:
            published = json.loads(OutputFiles.sidecar_for(path).read_text()).get(
                "published"
            )
            if published:
                return published
        except OSError, ValueError:
            pass
        return f"20{release_id[0:2]}-{release_id[2:4]}-{release_id[4:6]}"

    @staticmethod
    def _version() -> str:
        """
        Reads the installed version of the usgs-triplifier package.

        :return: The version, or "unknown" when the package is not installed.
        """
        try:
            return importlib_metadata.version("usgs-triplifier")
        except importlib_metadata.PackageNotFoundError:
            return "unknown"
