from rdflib import Literal
from rdflib.namespace import OWL, RDF, RDFS

from conftest import make_text_zip, parse_nt_gz
from usgs_triplifier.lib.gnis.history_triplifier import HistoryTriplifier
from usgs_triplifier.lib.gnis.units_triplifier import UnitsTriplifier


def test_history_end_to_end(data_dirs, config):
    input_dir, output_dir = data_dirs
    make_text_zip(
        input_dir,
        "FeatureDescriptionHistory_National_Text.zip",
        "Text/FeatureDescriptionHistory_National.txt",
        [
            "feature_id|description|history",
            "1|  A lake.  |Named in 1901.",
            "2|   |",
        ],
    )

    HistoryTriplifier(config).run()

    graph = parse_nt_gz(output_dir / "history.nt.gz")
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


def test_history_reads_quoted_fields_with_line_breaks(data_dirs, config):
    input_dir, output_dir = data_dirs
    make_text_zip(
        input_dir,
        "FeatureDescriptionHistory_National_Text.zip",
        "Text/FeatureDescriptionHistory_National.txt",
        [
            "feature_id|description|history",
            '630143|"1 mi. N of Wildlife Lake',
            '452 acres in size with a maximum depth of 35 feet."|Not approved',
            '3954||"""Dennehotso"" is a Navajo word."',
        ],
    )

    HistoryTriplifier(config).run()

    graph = parse_nt_gz(output_dir / "history.nt.gz")
    gnisf = config.prefix_list["gnisf"]
    gnis = config.prefix_list["gnis"]

    assert set(graph.subjects()) == {gnisf["630143"], gnisf["3954"]}
    assert list(graph.objects(gnisf["630143"], gnis["description"])) == [
        Literal(
            "1 mi. N of Wildlife Lake\n452 acres in size with a maximum depth of 35 feet.",
            lang="en",
        )
    ]
    assert list(graph.objects(gnisf["630143"], gnis["history"])) == [
        Literal("Not approved", lang="en")
    ]
    assert list(graph.objects(gnisf["3954"], gnis["history"])) == [
        Literal('"Dennehotso" is a Navajo word.', lang="en")
    ]


def test_units_end_to_end(data_dirs, config):
    input_dir, output_dir = data_dirs
    make_text_zip(
        input_dir,
        "GovernmentUnits_National_Text.zip",
        "Text/GovernmentUnits_National.txt",
        [
            "feature_id|unit_type|county_numeric|county_name|state_numeric"
            "|state_alpha|state_name|country_alpha|country_name|feature_name",
            "10|STATE|||06|CA|California|US|United States|California",
            "20|COUNTY|1|Alameda|06|CA|California|US|United States|Alameda County",
            "30|COUNTRY||||||US|United States|United States",
        ],
    )

    UnitsTriplifier(config).run()

    graph = parse_nt_gz(output_dir / "units.nt.gz")
    gnisf = config.prefix_list["gnisf"]
    gnis = config.prefix_list["gnis"]
    gnisf_alias = config.prefix_list["gnisf-alias"]

    # The unit's alias is the subject, so a feature's gnis:state value
    # carries the state's properties
    california = gnisf_alias["California"]
    assert (california, RDF.type, gnis["State"]) in graph
    # gnis:featureId stays on the gnisf: IRI, which the features file writes
    assert list(graph.objects(california, gnis["featureId"])) == []
    assert list(graph.objects(california, gnis["stateId"])) == [Literal("06")]
    assert list(graph.objects(california, gnis["stateCode"])) == [Literal("CA")]
    assert list(graph.objects(california, gnis["stateName"])) == [
        Literal("California", lang="en")
    ]
    assert list(graph.objects(california, gnis["country"])) == [
        gnisf_alias["United_States"]
    ]
    assert list(graph.objects(california, OWL.sameAs)) == [gnisf["10"]]
    assert list(graph.predicate_objects(gnisf["10"])) == []

    # A COUNTY row gets a zero-padded code and a state alias link, and no
    # state code or id
    alameda = gnisf_alias["California.Alameda"]
    assert (alameda, RDF.type, gnis["County"]) in graph
    assert list(graph.objects(alameda, gnis["countyCode"])) == [Literal("001")]
    assert list(graph.objects(alameda, gnis["countyName"])) == [
        Literal("Alameda", lang="en")
    ]
    assert list(graph.objects(alameda, gnis["state"])) == [california]
    assert list(graph.objects(alameda, gnis["stateCode"])) == []
    assert list(graph.objects(alameda, OWL.sameAs)) == [gnisf["20"]]

    # The COUNTRY row is written too, without a link to itself
    country = gnisf_alias["United_States"]
    assert (country, RDF.type, gnis["Country"]) in graph
    assert (country, RDFS.label, Literal("United States", lang="en")) in graph
    assert list(graph.objects(country, gnis["country"])) == []
    assert list(graph.objects(country, OWL.sameAs)) == [gnisf["30"]]
