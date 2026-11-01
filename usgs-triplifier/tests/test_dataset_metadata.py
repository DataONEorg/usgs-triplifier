from datetime import datetime, timezone

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCAT, DCTERMS, PROV, VOID, RDF, XSD

from usgs_triplifier.lib.dataset_metadata import DatasetMetadataWriter
from usgs_triplifier.output_files import OutputFiles
from usgs_triplifier.usgs_products import UsgsProducts

BUILD_TIME = datetime(2026, 8, 10, 12, 30, tzinfo=timezone.utc)
BUILD_ID = "260810"


def _write_and_parse(config, release_path=None):
    path = DatasetMetadataWriter(config).write(BUILD_TIME, release_path=release_path)
    assert path == config.output_directory / OutputFiles.METADATA
    graph = Graph()
    graph.parse(path, format="turtle")
    return graph


def test_build_id_is_yymmdd():
    assert OutputFiles.release_id(BUILD_TIME) == BUILD_ID


def test_dataset_and_release_are_linked_versions(data_dirs, config):
    _, output_dir = data_dirs
    graph = _write_and_parse(config)

    dataset = URIRef(f"{config.lod_base}/gnis")
    release = URIRef(f"{config.lod_base}/gnis/release/{BUILD_ID}")

    assert (dataset, RDF.type, VOID.Dataset) in graph
    assert (dataset, DCTERMS.hasVersion, release) in graph
    assert (release, DCTERMS.isVersionOf, dataset) in graph
    assert (release, DCTERMS.identifier, Literal(BUILD_ID)) in graph

    created = list(graph.objects(release, DCTERMS.created))
    assert len(created) == 1 and str(created[0]).startswith("2026-08-10T12:30")
    issued = list(graph.objects(release, DCTERMS.issued))
    assert len(issued) == 1 and str(issued[0]) == "2026-08-10"


def test_release_records_sources_and_pipeline(data_dirs, config):
    _, output_dir = data_dirs
    graph = _write_and_parse(config)
    release = URIRef(f"{config.lod_base}/gnis/release/{BUILD_ID}")

    sources = {str(s) for s in graph.objects(release, DCTERMS.source)}
    assert len(sources) == 5
    assert any(UsgsProducts.GEOPACKAGE.key in s for s in sources)
    assert all(s.startswith("https://") for s in sources)

    activities = list(graph.objects(release, PROV.wasGeneratedBy))
    assert len(activities) == 1
    assert (activities[0], RDF.type, PROV.Activity) in graph


def test_legacy_dump_release_records_the_legacy_sources(data_dirs, monkeypatch, config):
    _, output_dir = data_dirs
    config.legacy_dump = True
    graph = _write_and_parse(config)
    release = URIRef(f"{config.lod_base}/gnis/release/{BUILD_ID}")

    sources = {str(s) for s in graph.objects(release, DCTERMS.source)}
    assert sources == {
        f"https://prd-tnm.s3.amazonaws.com/{p.legacy_key}"
        for p in UsgsProducts.text_products()
    }


def test_distributions_describe_output_files(data_dirs, config):
    _, output_dir = data_dirs
    (output_dir / "features.nt.gz").write_text("# features")
    (output_dir / "names.nt.gz").write_text("# names, longer content")
    graph = _write_and_parse(config)
    release = URIRef(f"{config.lod_base}/gnis/release/{BUILD_ID}")

    distributions = list(graph.objects(release, DCAT.distribution))
    titles = {str(t) for d in distributions for t in graph.objects(d, DCTERMS.title)}
    assert titles == {"features.nt.gz", "names.nt.gz"}
    # The metadata file does not describe itself
    assert OutputFiles.METADATA not in titles

    features = URIRef(f"{release}/features")
    sizes = list(graph.objects(features, DCAT.byteSize))
    assert len(sizes) == 1 and int(sizes[0]) == len("# features")


def test_archive_dump_recorded_as_download(data_dirs, tmp_path, config):
    _, output_dir = data_dirs
    dump = tmp_path / f"gnis-ld-{BUILD_ID}.nt.gz"
    dump.write_bytes(b"gzip bytes")
    graph = _write_and_parse(config, release_path=dump)
    release = URIRef(f"{config.lod_base}/gnis/release/{BUILD_ID}")

    download = URIRef(f"{config.site_base}/archive/{dump.name}")
    assert (release, DCAT.distribution, download) in graph
    assert (download, DCAT.downloadURL, download) in graph
    assert (download, DCAT.mediaType, Literal("application/n-triples")) in graph
    assert (download, DCAT.compressFormat, Literal("application/gzip")) in graph
    sizes = list(graph.objects(download, DCAT.byteSize))
    assert len(sizes) == 1 and int(sizes[0]) == len(b"gzip bytes")


def test_archived_releases_are_redescribed_every_build(data_dirs, tmp_path, config):
    _, output_dir = data_dirs
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "gnis-ld-260401.nt.gz").write_bytes(b"prior dump")
    (archive / "gnis-ld-260401.meta.json").write_text('{"published": "2026-04-02"}')
    (archive / "gnis-ld-historical-260401.nt.gz").write_bytes(b"prior retained")
    # The current build's own dump is described via archive_path, not the scan
    (archive / f"gnis-ld-{BUILD_ID}.nt.gz").write_bytes(b"current dump")

    graph = _write_and_parse(config)

    dataset = URIRef(f"{config.lod_base}/gnis")
    prior = URIRef(f"{config.lod_base}/gnis/release/260401")
    assert (dataset, DCTERMS.hasVersion, prior) in graph
    assert (prior, DCTERMS.isVersionOf, dataset) in graph
    assert (prior, DCTERMS.issued, Literal("2026-04-02", datatype=XSD.date)) in graph
    downloads = {str(d) for d in graph.objects(prior, DCAT.distribution)}
    assert downloads == {
        f"{config.site_base}/archive/gnis-ld-260401.nt.gz",
        f"{config.site_base}/archive/gnis-ld-historical-260401.nt.gz",
    }
    # The current build is never duplicated by the archive scan
    current = URIRef(f"{config.lod_base}/gnis/release/{BUILD_ID}")
    assert list(graph.objects(current, DCAT.distribution)) == []
