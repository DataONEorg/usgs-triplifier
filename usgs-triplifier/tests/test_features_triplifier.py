from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, XSD

from conftest import make_text_zip, parse_nt_gz
from usgs_triplifier.lib.gnis.features_triplifier import FeaturesTriplifier

# The columns the triplifier reads, plus elev_in_ft to show it is ignored
# outside archive mode
HEADER = (
    "feature_id|feature_name|feature_class|state_name|county_name|map_name"
    "|date_created|date_edited|prim_lat_dec|prim_long_dec|elev_in_ft"
)


def _features_zip(input_dir: Path) -> Path:
    """
    Stages a DomesticNames text product covering the triplifier's edge cases.

    :param input_dir: Directory the triplifier reads zips from.
    :return: Path to the zip file.
    """
    return make_text_zip(
        input_dir,
        "DomesticNames_National_Text.zip",
        "Text/DomesticNames_National.txt",
        [
            HEADER,
            "1|Blue Lake|Lake|California|Alameda|Oakland East"
            "|01/02/1998|10/06/1998|34.5|-117.2|5280",
            "2|Blue Lake|Lake|California|Alameda|Oakland East|bogus||34.6||",
            "3|High Ridge|Range|Nevada|Clark|Vegas NE"
            "|02/03/2000|01/01/2001|36.1|-115.1|",
            "4|Lone Rock|Summit|||Map|||40.0|-110.0|",
        ],
    )


def test_features_end_to_end(data_dirs, monkeypatch, config):
    input_dir, output_dir = data_dirs
    _features_zip(input_dir)

    FeaturesTriplifier(config).run()

    graph = parse_nt_gz(output_dir / "features.nt.gz")

    gnisf = config.prefix_list["gnisf"]
    gnis = config.prefix_list["gnis"]
    usgs = config.prefix_list["usgs"]
    geosparql = config.prefix_list["geosparql"]

    # Check class mappings and typings
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

    # Check that the geometry is present for rows with both coordinates or absent otherwise
    assert list(graph.objects(gnisf["1"], geosparql["hasGeometry"])) == [
        URIRef(f"{config.geo_base}/point/gnisf.1")
    ]
    assert list(graph.objects(gnisf["2"], geosparql["hasGeometry"])) == []
    geom_node = URIRef(f"{config.geo_base}/point/gnisf.1")
    wkt = list(graph.objects(geom_node, geosparql["asWKT"]))
    assert len(wkt) == 1 and "POINT(-117.2 34.5)" in str(wkt[0])

    assert list(graph.objects(gnisf["1"], gnis["dateFeatureCreated"])) == [
        Literal("1998-01-02", datatype=XSD.date)
    ]
    assert list(graph.objects(gnisf["1"], gnis["dateFeatureEdited"])) == [
        Literal("1998-10-06", datatype=XSD.date)
    ]
    # A date in neither format is skipped
    assert list(graph.objects(gnisf["2"], gnis["dateFeatureCreated"])) == []
    assert list(graph.objects(gnisf["2"], gnis["dateFeatureEdited"])) == []

    # Check that empty states and counties produce no links
    assert list(graph.objects(gnisf["4"], gnis["state"])) == []
    assert list(graph.objects(gnisf["4"], gnis["county"])) == []
    assert "None" not in graph.serialize(format="nt")

    aliases = parse_nt_gz(output_dir / "feature-aliases.nt.gz")
    gnisf_alias = config.prefix_list["gnisf-alias"]
    shared = gnisf_alias["California.Alameda.Lake.Blue_Lake"]
    assert set(aliases.objects(shared, gnis["disambiguatesTo"])) == {
        gnisf["1"],
        gnisf["2"],
    }
    unique = gnisf_alias["Nevada.Clark.MountainRange.High_Ridge"]
    assert list(aliases.objects(unique, OWL.sameAs)) == [gnisf["3"]]
    assert list(aliases.objects(gnisf_alias["..Summit.Lone_Rock"], OWL.sameAs)) == [
        gnisf["4"]
    ]


def test_state_and_county_object_edge_cases(config):
    ft = FeaturesTriplifier(config)
    gnisf_alias = config.prefix_list["gnisf-alias"]
    assert ft.state_object("New York", {}) == gnisf_alias["New_York"]
    assert ft.county_object("", {}) == config.prefix_list["gnis"]["UnknownCounty"]
    assert (
        ft.county_object("Kings", {"state_name": "New York"})
        == gnisf_alias["New_York.Kings"]
    )


def test_prim_lat_dec_field_guards(config):
    ft = FeaturesTriplifier(config)
    assert ft.prim_lat_dec_field("", {"feature_id": "1"}, Graph()) is None
    assert ft.prim_lat_dec_field("0.0", {"feature_id": "1"}, Graph()) is None
    assert ft.prim_lat_dec_field("0", {"feature_id": "1"}, Graph()) is None
    assert ft.prim_lat_dec_field("34.5", {"feature_id": "1"}, Graph()) is None
    assert (
        ft.prim_lat_dec_field("34.5", {"prim_long_dec": "", "feature_id": "1"}, Graph())
        is None
    )
    # One zero coordinate, or a coordinate that is not a number, is no geometry
    assert (
        ft.prim_lat_dec_field(
            "34.5", {"prim_long_dec": "0", "feature_id": "1"}, Graph()
        )
        is None
    )
    assert (
        ft.prim_lat_dec_field(
            "abc", {"prim_long_dec": "-117.2", "feature_id": "1"}, Graph()
        )
        is None
    )
    assert ft.feature_id_object("0005", {}) == Literal("5")
    result = ft.prim_lat_dec_field(
        "34.5", {"prim_long_dec": "-117.2", "feature_id": "1"}, Graph()
    )
    assert result == {
        "geosparql:hasGeometry": [URIRef(f"{config.geo_base}/point/gnisf.1")]
    }


def test_elev_in_ft_field_guards(config):
    ft = FeaturesTriplifier(config)
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


def test_current_sources_omit_elevation(data_dirs, monkeypatch, config):
    input_dir, output_dir = data_dirs
    _features_zip(input_dir)

    FeaturesTriplifier(config).run()

    graph = parse_nt_gz(output_dir / "features.nt.gz")
    gnis = config.prefix_list["gnis"]
    assert list(graph.subject_objects(gnis["elevation"])) == []
