import pytest
import shapely
from rdflib import Literal

from conftest import make_gpkg_zip, parse_nt_gz
from usgs_triplifier.lib.gnis.geometry_triplifier import GeometryTriplifier
from usgs_triplifier.lib.gnis.rdf import Terms


def test_geometries_end_to_end(data_dirs, config):
    input_dir, output_dir = data_dirs
    make_gpkg_zip(
        input_dir,
        "Gazetteer_National_GPKG.zip",
        {
            1: shapely.MultiPoint([(-117.2, 34.5, 0), (-117.1, 34.6, 0)]),
            2: shapely.MultiPoint([(-115.1, 36.1, 0)]),
            3: None,
            # USGS's placeholder for an unknown location
            4: shapely.MultiPoint([(-2.3874235921539366e-11, -2.27e-13, 0)]),
        },
    )

    count = GeometryTriplifier(config).run()

    graph = parse_nt_gz(output_dir / "geometries.nt.gz")
    gnisf = config.prefix_list["gnisf"]
    geosparql = config.prefix_list["geosparql"]
    multipoint = config.prefix_list["usgeo-multipoint"]
    wkt_literal = geosparql["wktLiteral"]

    assert str(multipoint["gnisf.1"]) == f"{config.geo_base}/multipoint/gnisf.1"
    assert list(graph.objects(gnisf["1"], geosparql["hasGeometry"])) == [
        multipoint["gnisf.1"]
    ]
    # 2D WKT with the CRS prefix the point geometries carry
    assert graph.value(multipoint["gnisf.1"], geosparql["asWKT"]) == Literal(
        f"{Terms.CRS84}MULTIPOINT ((-117.2 34.5), (-117.1 34.6))", datatype=wkt_literal
    )
    assert graph.value(multipoint["gnisf.2"], geosparql["asWKT"]) == Literal(
        f"{Terms.CRS84}MULTIPOINT ((-115.1 36.1))", datatype=wkt_literal
    )
    assert list(graph.predicate_objects(gnisf["3"])) == []
    assert list(graph.predicate_objects(gnisf["4"])) == []
    assert count == len(graph) == 4


def test_geometries_without_gpkg_raise(data_dirs, config):
    with pytest.raises(FileNotFoundError):
        GeometryTriplifier(config).run()
