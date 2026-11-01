from rdflib import BNode, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from conftest import make_text_zip, parse_nt_gz
from usgs_triplifier.lib.geonames_crosswalk import GeoNamesCrosswalk
from usgs_triplifier.lib.gnis.features_triplifier import FeaturesTriplifier
from usgs_triplifier.lib.gnis.history_triplifier import HistoryTriplifier
from usgs_triplifier.lib.gnis.names_triplifier import NamesTriplifier
from usgs_triplifier.lib.gnis.units_triplifier import UnitsTriplifier

NATIONAL_FILE_HEADER = (
    "FEATURE_ID|FEATURE_NAME|FEATURE_CLASS|STATE_ALPHA|STATE_NUMERIC"
    "|COUNTY_NAME|COUNTY_NUMERIC|PRIMARY_LAT_DMS|PRIM_LONG_DMS|PRIM_LAT_DEC"
    "|PRIM_LONG_DEC|SOURCE_LAT_DMS|SOURCE_LONG_DMS|SOURCE_LAT_DEC"
    "|SOURCE_LONG_DEC|ELEV_IN_M|ELEV_IN_FT|MAP_NAME|DATE_CREATED|DATE_EDITED"
)


def _national_file_zip(input_dir):
    return make_text_zip(
        input_dir,
        "NationalFile.zip",
        "NationalFile_20210825.txt",
        [
            NATIONAL_FILE_HEADER,
            "1414314|Denali|Summit|AK|02|Denali|068|631712N|1510038W|63.0690949"
            "|-151.0063|||||6144|20157|Mount McKinley A-3|01/01/2000|",
            "999|Salt Pond|Lake|VI|78|St. Thomas|030|||0|0|||||0|0|Map|02/02/2001|",
        ],
    )


def test_features_from_legacy_national_file(data_dirs, monkeypatch, config):
    input_dir, output_dir = data_dirs
    config.legacy_dump = True
    _national_file_zip(input_dir)

    FeaturesTriplifier(config).run()

    graph = parse_nt_gz(output_dir / "features.nt.gz")
    gnisf = config.prefix_list["gnisf"]
    gnis = config.prefix_list["gnis"]
    usgs = config.prefix_list["usgs"]
    geosparql = config.prefix_list["geosparql"]
    gnisf_alias = config.prefix_list["gnisf-alias"]
    qudt = config.prefix_list["qudt"]

    assert (gnisf["1414314"], RDF.type, usgs["Summit"]) in graph

    # State code expanded to the full name for gnis:state and the alias
    assert list(graph.objects(gnisf["1414314"], gnis["state"])) == [
        gnisf_alias["Alaska"]
    ]
    aliases = parse_nt_gz(output_dir / "feature-aliases.nt.gz")
    assert list(
        aliases.objects(gnisf_alias["Alaska.Denali.Summit.Denali"], OWL.sameAs)
    ) == [gnisf["1414314"]]

    # Only legacy dumps have an elevation column
    elev_nodes = list(graph.objects(gnisf["1414314"], gnis["elevation"]))
    assert len(elev_nodes) == 1 and isinstance(elev_nodes[0], BNode)
    assert list(graph.objects(elev_nodes[0], qudt["numericValue"])) == [
        Literal("20157", datatype=XSD.double)
    ]

    # Geometry from the decimal coordinates; text-format "0" means unknown
    geom = URIRef(f"{config.geo_base}/point/gnisf.1414314")
    assert list(graph.objects(gnisf["1414314"], geosparql["hasGeometry"])) == [geom]
    wkt = list(graph.objects(geom, geosparql["asWKT"]))
    assert len(wkt) == 1 and "POINT(-151.0063 63.0690949)" in str(wkt[0])
    assert list(graph.objects(gnisf["999"], geosparql["hasGeometry"])) == []
    assert list(graph.objects(gnisf["999"], gnis["elevation"])) == []

    assert list(graph.objects(gnisf["999"], gnis["state"])) == [
        gnisf_alias["United_States_Virgin_Islands"]
    ]

    assert list(graph.objects(gnisf["1414314"], gnis["dateFeatureCreated"])) == [
        Literal("2000-01-01", datatype=XSD.date)
    ]


def test_row_whose_state_code_and_number_differ_is_skipped(data_dirs, config):
    input_dir, output_dir = data_dirs
    config.legacy_dump = True
    airport = (
        "|Boswell Bay Airport|Airport|{}|02||063|||60.42306|-146.14591|||||62|203"
        "|Cordova|07/01/1995|06/23/2021"
    )
    river = (
        "774784|North Fork Milk River|Stream|{}|{}|||||49.1373|-112.37589|||||1083"
        "|3553|Unknown|04/04/1980|12/14/2010"
    )
    make_text_zip(
        input_dir,
        "NationalFile.zip",
        "NationalFile_20210825.txt",
        [
            NATIONAL_FILE_HEADER,
            "1417597" + airport.format("AK"),
            # The 2021 file copies Chugach Census Area features under AZ
            # with Alaska's state number
            "1417597" + airport.format("AZ"),
            # A Canadian province code has its own numbering and is kept
            river.format("MT", "30"),
            river.format("AB", "01"),
        ],
    )

    FeaturesTriplifier(config).run()

    graph = parse_nt_gz(output_dir / "features.nt.gz")
    gnisf = config.prefix_list["gnisf"]
    gnis = config.prefix_list["gnis"]
    gnisf_alias = config.prefix_list["gnisf-alias"]
    assert list(graph.objects(gnisf["1417597"], gnis["state"])) == [
        gnisf_alias["Alaska"]
    ]
    assert len(list(graph.objects(gnisf["1417597"], gnis["elevation"]))) == 1
    assert set(graph.objects(gnisf["774784"], gnis["state"])) == {
        gnisf_alias["Montana"],
        gnisf_alias["AB"],
    }
    # The elevation repeated in every row of the feature is written once
    assert len(list(graph.objects(gnisf["774784"], gnis["elevation"]))) == 1


def test_names_from_legacy_all_names(data_dirs, monkeypatch, config):
    input_dir, output_dir = data_dirs
    config.legacy_dump = True
    make_text_zip(
        input_dir,
        "AllNames.zip",
        "AllNames_20210825.txt",
        [
            "FEATURE_ID|FEATURE_NAME|FEATURE_NAME_OFFICIAL|CITATION|DATE_CREATED",
            "1414314|Denali|Y|Board decision 2015|08/28/2015",
            "1414314|Mount McKinley|N||01/01/2000",
            '2102872|"Alson H Smith, Junior Library"|Y||01/01/2000',
        ],
    )
    # A current download left in the input directory is not read
    make_text_zip(
        input_dir,
        "AllNames_National_Text.zip",
        "Text/AllNames_National.txt",
        [
            "feature_id|feature_name|feature_name_official|citation|date_created",
            "1414314|Mount McKinley|Official|Executive order|01/20/2025",
        ],
    )

    NamesTriplifier(config).run()

    graph = parse_nt_gz(output_dir / "names.nt.gz")
    gnisf = config.prefix_list["gnisf"]
    gnis = config.prefix_list["gnis"]

    # In 2021 the official name was still Denali
    assert (gnisf["1414314"], RDFS.label, Literal("Denali", lang="en")) in graph
    assert list(graph.objects(gnisf["1414314"], gnis["officialName"])) == [
        Literal("Denali", lang="en")
    ]
    assert list(graph.objects(gnisf["1414314"], gnis["alternativeName"])) == [
        Literal("Mount McKinley", lang="en")
    ]
    # Legacy fields are not quoted, so a leading quote is part of the name
    assert list(graph.objects(gnisf["2102872"], gnis["officialName"])) == [
        Literal('"Alson H Smith, Junior Library"', lang="en")
    ]
    assert list(graph.objects(gnisf["1414314"], gnis["citation"])) == [
        Literal("Board decision 2015", lang="en")
    ]


def test_history_from_legacy_description_history(data_dirs, monkeypatch, config):
    input_dir, output_dir = data_dirs
    config.legacy_dump = True
    make_text_zip(
        input_dir,
        "Feature_Description_History.zip",
        "Feature_Description_History_20210825.txt",
        [
            "FEATURE_ID|DESCRIPTION|HISTORY",
            "1414314|Highest summit in North America|Named for a president.",
            '5213|A village|"The town plan divided the village',
            "5214|A lake|Named in 1901.",
        ],
    )

    HistoryTriplifier(config).run()

    graph = parse_nt_gz(output_dir / "history.nt.gz")
    gnisf = config.prefix_list["gnisf"]
    gnis = config.prefix_list["gnis"]
    assert list(graph.objects(gnisf["1414314"], gnis["description"])) == [
        Literal("Highest summit in North America", lang="en")
    ]
    assert list(graph.objects(gnisf["1414314"], gnis["history"])) == [
        Literal("Named for a president.", lang="en")
    ]
    # Legacy fields are not quoted, so an unclosed quote does not swallow
    # the next row
    assert list(graph.objects(gnisf["5213"], gnis["history"])) == [
        Literal('"The town plan divided the village', lang="en")
    ]
    assert list(graph.objects(gnisf["5214"], gnis["history"])) == [
        Literal("Named in 1901.", lang="en")
    ]


def test_units_from_legacy_govt_units(data_dirs, monkeypatch, config):
    input_dir, output_dir = data_dirs
    config.legacy_dump = True
    make_text_zip(
        input_dir,
        "GOVT_UNITS.zip",
        "GOVT_UNITS_20210825.txt",
        [
            "FEATURE_ID|UNIT_TYPE|COUNTY_NUMERIC|COUNTY_NAME|STATE_NUMERIC"
            "|STATE_ALPHA|STATE_NAME|COUNTRY_ALPHA|COUNTRY_NAME|FEATURE_NAME",
            "1419988|COUNTY|068|Denali|02|AK|Alaska|US|United States|Denali Borough",
            "1785533|STATE||;|02|AK|Alaska|US|United States|State of Alaska",
        ],
    )

    UnitsTriplifier(config).run()

    graph = parse_nt_gz(output_dir / "units.nt.gz")
    gnisf = config.prefix_list["gnisf"]
    gnis = config.prefix_list["gnis"]
    gnisf_alias = config.prefix_list["gnisf-alias"]

    denali = gnisf_alias["Alaska.Denali"]
    assert (denali, RDF.type, gnis["County"]) in graph
    assert list(graph.objects(denali, gnis["state"])) == [gnisf_alias["Alaska"]]
    assert list(graph.objects(denali, OWL.sameAs)) == [gnisf["1419988"]]
    assert (gnisf_alias["Alaska"], RDF.type, gnis["State"]) in graph
    # The ";" in the STATE row's COUNTY_NAME column is not a county name
    assert list(graph.objects(gnisf_alias["Alaska"], gnis["countyName"])) == []
    assert list(graph.objects(gnisf_alias["Alaska"], gnis["stateName"])) == [
        Literal("Alaska", lang="en")
    ]


def test_geonames_loader_reads_legacy_national_file(data_dirs, monkeypatch, config):
    input_dir, _ = data_dirs
    config.legacy_dump = True
    _national_file_zip(input_dir)

    gnis = GeoNamesCrosswalk(config)._load_gnis()

    # The zero-coordinate row is dropped; the state code passes through
    assert list(gnis["feature_id"]) == ["1414314"]
    assert list(gnis["state"]) == ["AK"]
    assert list(gnis["name"]) == ["Denali"]
