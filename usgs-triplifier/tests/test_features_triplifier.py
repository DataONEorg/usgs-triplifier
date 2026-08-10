from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import OWL, XSD

from conftest import make_gpkg_zip
from usgs_triplifier.config import config
from usgs_triplifier.lib.gnis import features_triplifier
from usgs_triplifier.lib.gnis.features_triplifier import FeaturesTriplifier


def _rows():
    return [
        {
            "feature_id": "1",
            "feature_name": "Blue Lake",
            "feature_class": "Lake",
            "state_name": "California",
            "county_name": "Alameda",
            "map_name": "Oakland East",
            "prim_lat_dec": 34.5,
            "prim_long_dec": -117.2,
            "elev_in_ft": 5280.0,
            "date_created": "01/02/1998",
            "date_edited": "1998-10-06T06:13:42",
        },
        {
            # Same alias as row 1 -> disambiguation; missing longitude -> no geometry
            "feature_id": "2",
            "feature_name": "Blue Lake",
            "feature_class": "Lake",
            "state_name": "California",
            "county_name": "Alameda",
            "map_name": "Oakland East",
            "prim_lat_dec": 34.6,
            "prim_long_dec": float("nan"),
            "elev_in_ft": float("nan"),
            "date_created": "bogus",
            "date_edited": None,
        },
        {
            # Mapped class name (Range -> MountainRange), unique alias -> sameAs
            "feature_id": "3",
            "feature_name": "High Ridge",
            "feature_class": "Range",
            "state_name": "Nevada",
            "county_name": "Clark",
            "map_name": "Vegas NE",
            "prim_lat_dec": 36.1,
            "prim_long_dec": -115.1,
            "elev_in_ft": float("nan"),
            "date_created": "02/03/2000",
            "date_edited": "2001-01-01T00:00:00",
        },
    ]


def test_features_end_to_end(data_dirs, monkeypatch):
    input_dir, output_dir = data_dirs
    monkeypatch.setattr(features_triplifier, "feature_aliases", {})
    make_gpkg_zip(input_dir, "Gazetteer_National_GPKG.zip", {"DomesticNames": _rows()})

    FeaturesTriplifier()

    graph = Graph()
    graph.parse(output_dir / "features.ttl", format="turtle")

    gnisf = config.prefix_list["gnisf"]
    gnis = config.prefix_list["gnis"]
    usgs = config.prefix_list["usgs"]
    geosparql = config.prefix_list["geosparql"]

    # Class mapping and typing
    assert (
        gnisf["1"],
        URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type"),
        usgs["Lake"],
    ) in graph
    assert (
        gnisf["3"],
        URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type"),
        usgs["MountainRange"],
    ) in graph

    # Geometry present for rows with both coordinates, absent otherwise
    assert list(graph.objects(gnisf["1"], geosparql["hasGeometry"])) == [
        URIRef(f"{config.geo_base}/point/gnisf.1")
    ]
    assert list(graph.objects(gnisf["2"], geosparql["hasGeometry"])) == []
    geom_node = URIRef(f"{config.geo_base}/point/gnisf.1")
    wkt = list(graph.objects(geom_node, geosparql["asWKT"]))
    assert len(wkt) == 1 and "POINT(-117.2 34.5)" in str(wkt[0])
    assert "nan" not in graph.serialize(format="turtle")

    # Elevation becomes a blank node with QUDT properties; zero/NaN skipped
    elev_nodes = list(graph.objects(gnisf["1"], gnis["elevation"]))
    assert len(elev_nodes) == 1 and isinstance(elev_nodes[0], BNode)
    qudt = config.prefix_list["qudt"]
    assert list(graph.objects(elev_nodes[0], qudt["numericValue"])) == [
        Literal("5280.0", datatype=XSD.double)
    ]
    assert list(graph.objects(gnisf["2"], gnis["elevation"])) == []
    assert list(graph.objects(gnisf["3"], gnis["elevation"])) == []

    # Dates: both formats normalize, unparsable passes through
    assert list(graph.objects(gnisf["1"], gnis["dateFeatureCreated"])) == [
        Literal("1998-01-02", datatype=XSD.date)
    ]
    assert list(graph.objects(gnisf["1"], gnis["dateFeatureEdited"])) == [
        Literal("1998-10-06", datatype=XSD.date)
    ]
    assert list(graph.objects(gnisf["2"], gnis["dateFeatureCreated"])) == [
        Literal("bogus")
    ]

    # geoms.tsv only contains rows with full coordinates
    geoms = (output_dir / "geoms.tsv").read_text().strip().splitlines()
    assert len(geoms) == 2
    assert geoms[0].startswith(
        f"{config.geo_base}/point/gnisf.1\tSRID=4326;POINT(-117.2 34.5)"
    )

    # Aliases: shared alias disambiguates, unique alias is sameAs
    aliases = Graph()
    aliases.parse(output_dir / "feature-aliases.ttl", format="turtle")
    gnisf_alias = config.prefix_list["gnisf-alias"]
    shared = gnisf_alias["California.Alameda.Lake.Blue_Lake"]
    assert set(aliases.objects(shared, gnis["disambiguatesTo"])) == {
        gnisf["1"],
        gnisf["2"],
    }
    unique = gnisf_alias["Nevada.Clark.MountainRange.High_Ridge"]
    assert list(aliases.objects(unique, OWL.sameAs)) == [gnisf["3"]]


def test_state_and_county_object_edge_cases():
    ft = FeaturesTriplifier.__new__(FeaturesTriplifier)
    assert ft.state_object("", {}, Graph()) == ""
    gnisf_alias = config.prefix_list["gnisf-alias"]
    assert ft.state_object("New York", {}, Graph()) == gnisf_alias["New_York"]
    assert (
        ft.county_object("", {}, Graph()) == config.prefix_list["gnis"]["UnknownCounty"]
    )
    assert (
        ft.county_object("Kings", {"state_name": "New York"}, Graph())
        == gnisf_alias["New_York.Kings"]
    )


def test_prim_lat_dec_field_guards():
    ft = FeaturesTriplifier.__new__(FeaturesTriplifier)
    field = ft.make_prim_lat_dec_field(None)
    assert field("", {"feature_id": 1}, Graph()) is None
    assert field("0.0", {"feature_id": 1}, Graph()) is None
    assert field("34.5", {"feature_id": 1}, Graph()) is None
    assert (
        field("34.5", {"prim_long_dec": float("nan"), "feature_id": 1}, Graph()) is None
    )
    result = field("34.5", {"prim_long_dec": -117.2, "feature_id": 1}, Graph())
    assert result == {"geosparql:hasGeometry": [f">{config.geo_base}/point/gnisf.1"]}


def test_elev_in_ft_field_guards():
    ft = FeaturesTriplifier.__new__(FeaturesTriplifier)
    assert ft.elev_in_ft_field("", {}, Graph()) is None
    assert ft.elev_in_ft_field("0", {}, Graph()) is None
    assert ft.elev_in_ft_field("  ", {}, Graph()) is None
    result = ft.elev_in_ft_field("5280", {}, Graph())
    assert result == {
        "gnis:elevation": {
            "qudt:numericValue": ['^xsd:double"5280'],
            "qudt:unit": ["unit:FT"],
        },
    }
