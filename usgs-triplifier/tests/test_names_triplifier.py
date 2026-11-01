from rdflib import Literal
from rdflib.namespace import RDFS, XSD

from conftest import make_text_zip, parse_nt_gz
from usgs_triplifier.lib.gnis.names_triplifier import NamesTriplifier


HEADER = "feature_id|feature_name|feature_name_official|citation|date_created"


def test_names_end_to_end(data_dirs, config):
    input_dir, output_dir = data_dirs
    make_text_zip(
        input_dir,
        "AllNames_National_Text.zip",
        "Text/AllNames_National.txt",
        [
            HEADER,
            '1|Blue Lake|Official|"""History of Alameda County"" p. 12"|01/02/1998',
            "1|Old Blue|Variant|ignored citation|03/04/1999",
            "2|Twin Peaks|Official|Citation Unknown|bogus-date",
            "3|Oak Hill|Official|Text Citation Unknown|2001-02-03",
            "4|Elm Spring|Official|Map U.S. Geological Survey 1981 |12/31/1981",
            "5|Ash Creek|Official|Unknown |01/01/1990",
            "6|Fir Knob|Official|Unknown J. Smith 1902|01/01/1990",
        ],
    )

    NamesTriplifier(config).run()

    graph = parse_nt_gz(output_dir / "names.nt.gz")
    gnisf = config.prefix_list["gnisf"]
    gnis = config.prefix_list["gnis"]

    # Official name -> label + officialName
    assert (gnisf["1"], RDFS.label, Literal("Blue Lake", lang="en")) in graph
    assert list(graph.objects(gnisf["1"], gnis["officialName"])) == [
        Literal("Blue Lake", lang="en")
    ]
    # Variant name -> alternativeName only, and its citation/date are ignored
    assert list(graph.objects(gnisf["1"], gnis["alternativeName"])) == [
        Literal("Old Blue", lang="en")
    ]
    assert list(graph.objects(gnisf["1"], gnis["dateNameCreated"])) == [
        Literal("1998-01-02", datatype=XSD.date)
    ]

    # A quoted field is unwrapped and its doubled quotes become single ones
    citations = list(graph.objects(gnisf["1"], gnis["citation"]))
    assert citations == [Literal('"History of Alameda County" p. 12', lang="en")]

    # 'Citation Unknown', with or without the source type the current
    # products prefix it with, maps to the well-known IRI
    assert list(graph.objects(gnisf["2"], gnis["citation"])) == [
        gnis["UnknownCitation"]
    ]
    assert list(graph.objects(gnisf["3"], gnis["citation"])) == [
        gnis["UnknownCitation"]
    ]
    # A date in neither format is skipped, an ISO date is accepted
    assert list(graph.objects(gnisf["2"], gnis["dateNameCreated"])) == []
    assert list(graph.objects(gnisf["3"], gnis["dateNameCreated"])) == [
        Literal("2001-02-03", datatype=XSD.date)
    ]
    # Surrounding whitespace is removed from a citation
    assert list(graph.objects(gnisf["4"], gnis["citation"])) == [
        Literal("Map U.S. Geological Survey 1981", lang="en")
    ]
    # A bare "Unknown" is a placeholder; "Unknown" followed by a source is kept
    assert list(graph.objects(gnisf["5"], gnis["citation"])) == [
        gnis["UnknownCitation"]
    ]
    assert list(graph.objects(gnisf["6"], gnis["citation"])) == [
        Literal("Unknown J. Smith 1902", lang="en")
    ]


def test_is_official_accepts_current_and_legacy_flags():
    assert NamesTriplifier._is_official({"feature_name_official": "Official"})
    assert not NamesTriplifier._is_official({"feature_name_official": "Variant"})
    assert NamesTriplifier._is_official({"feature_name_official": "Y"})
    assert not NamesTriplifier._is_official({"feature_name_official": "N"})
    assert not NamesTriplifier._is_official({})
