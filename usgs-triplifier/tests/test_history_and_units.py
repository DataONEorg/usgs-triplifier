from rdflib import Graph, Literal
from rdflib.namespace import OWL, RDF

from conftest import make_gpkg_zip
from usgs_triplifier.config import config
from usgs_triplifier.lib.gnis.history_triplifier import HistoryTriplifier
from usgs_triplifier.lib.gnis.units_triplifier import UnitsTriplifier


def test_history_end_to_end(data_dirs):
    input_dir, output_dir = data_dirs
    make_gpkg_zip(
        input_dir,
        "Gazetteer_National_GPKG.zip",
        {
            "Gaz_Features": [
                {
                    "feature_id": "1",
                    "description": "  A lake.  ",
                    "history": "Named in 1901.",
                },
                {"feature_id": "2", "description": "   ", "history": None},
            ]
        },
    )

    HistoryTriplifier()

    graph = Graph()
    graph.parse(output_dir / "history.ttl", format="turtle")
    gnisf = config.prefix_list["gnisf"]
    gnis = config.prefix_list["gnis"]

    assert list(graph.objects(gnisf["1"], gnis["description"])) == [
        Literal("A lake.", lang="en")
    ]
    assert list(graph.objects(gnisf["1"], gnis["history"])) == [
        Literal("Named in 1901.", lang="en")
    ]
    # Whitespace-only and missing values produce no triples
    assert list(graph.predicate_objects(gnisf["2"])) == []


def test_units_end_to_end(data_dirs):
    input_dir, output_dir = data_dirs
    make_gpkg_zip(
        input_dir,
        "Gazetteer_National_GPKG.zip",
        {
            "GovernmentUnits": [
                {
                    "feature_id": "10",
                    "unit_type": "STATE",
                    "state_alpha": "CA",
                    "state_name": "California",
                    "state_numeric": "06",
                    "county_name": None,
                    "county_numeric": None,
                    "country_name": "United States",
                    "feature_name": "California",
                },
                {
                    "feature_id": "20",
                    "unit_type": "COUNTY",
                    "state_alpha": "CA",
                    "state_name": "California",
                    "state_numeric": "06",
                    "county_name": "Alameda",
                    "county_numeric": "1",
                    "country_name": "United States",
                    "feature_name": "Alameda County",
                },
                {
                    "feature_id": "30",
                    "unit_type": "COUNTRY",
                    "state_alpha": None,
                    "state_name": None,
                    "state_numeric": None,
                    "county_name": None,
                    "county_numeric": None,
                    "country_name": "United States",
                    "feature_name": "United States",
                },
            ]
        },
    )

    UnitsTriplifier()

    graph = Graph()
    graph.parse(output_dir / "units.ttl", format="turtle")
    gnisf = config.prefix_list["gnisf"]
    gnis = config.prefix_list["gnis"]
    gnisf_alias = config.prefix_list["gnisf-alias"]

    # STATE row
    assert (gnisf["10"], RDF.type, gnis["State"]) in graph
    assert list(graph.objects(gnisf["10"], gnis["stateId"])) == [Literal("06")]
    assert list(graph.objects(gnisf["10"], gnis["stateCode"])) == [Literal("CA")]
    assert list(graph.objects(gnisf["10"], gnis["stateName"])) == [
        Literal("California", lang="en")
    ]
    assert (gnisf_alias["California"], OWL.sameAs, gnisf["10"]) in graph

    # COUNTY row: zero-padded code, state alias link, no state code/id
    assert (gnisf["20"], RDF.type, gnis["County"]) in graph
    assert list(graph.objects(gnisf["20"], gnis["countyCode"])) == [Literal("001")]
    assert list(graph.objects(gnisf["20"], gnis["countyName"])) == [
        Literal("Alameda", lang="en")
    ]
    assert list(graph.objects(gnisf["20"], gnis["state"])) == [
        gnisf_alias["California"]
    ]
    assert list(graph.objects(gnisf["20"], gnis["stateCode"])) == []
    assert (gnisf_alias["California.Alameda"], OWL.sameAs, gnisf["20"]) in graph

    # COUNTRY row is skipped entirely
    assert list(graph.predicate_objects(gnisf["30"])) == []
