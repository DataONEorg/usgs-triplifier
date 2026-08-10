import pytest
from rdflib import BNode, Graph, Literal, URIRef

from conftest import make_gpkg_zip
from usgs_triplifier.config import config
from usgs_triplifier.lib.gnis.triplifier import (
    FieldDescriptor,
    TriplifierConfig,
    _add_pairs,
    _add_triple,
    _parse_object,
    _resolve_iri,
    clean,
    get_gpkg_zip_files,
    normalize_feature_id,
    triplify_all,
)

XSD_DOUBLE = URIRef("http://www.w3.org/2001/XMLSchema#double")
S = URIRef("http://example.org/s")
P = URIRef("http://example.org/p")


def test_normalize_feature_id():
    assert normalize_feature_id(1234.0) == "1234"
    assert normalize_feature_id(7) == "7"
    assert normalize_feature_id("0123") == "123"
    assert normalize_feature_id("000") == "0"
    assert normalize_feature_id("") == "0"


def test_clean_replaces_non_word_characters():
    assert clean("San Juan Co.") == "San_Juan_Co_"
    assert clean("word") == "word"


def test_parse_object_notations():
    assert _parse_object(">http://example.org/x") == URIRef("http://example.org/x")
    assert _parse_object('"hello') == Literal("hello")
    assert _parse_object('@en"hello') == Literal("hello", lang="en")
    assert _parse_object('^xsd:double"1.5') == Literal("1.5", datatype=XSD_DOUBLE)
    gnis = config.prefix_list["gnis"]
    assert _parse_object("gnis:Thing") == gnis["Thing"]
    assert _parse_object("plain value") == Literal("plain value")


def test_resolve_iri():
    assert _resolve_iri(">http://example.org/a") == URIRef("http://example.org/a")
    assert _resolve_iri("gnisf:123") == config.prefix_list["gnisf"]["123"]
    assert _resolve_iri("unknown:thing") == URIRef("unknown:thing")
    assert _resolve_iri("nocolon") == URIRef("nocolon")


def test_add_triple_literal_string_and_uri():
    g = Graph()
    _add_triple(g, S, P, Literal("x"))
    _add_triple(g, S, P, '"y')
    _add_triple(g, S, P, URIRef("http://example.org/o"))
    assert (S, P, Literal("x")) in g
    assert (S, P, Literal("y")) in g
    assert (S, P, URIRef("http://example.org/o")) in g


def test_add_triple_dict_becomes_blank_node():
    g = Graph()
    _add_triple(
        g, S, P, {"qudt:numericValue": ['^xsd:double"5280'], "qudt:unit": ["unit:FT"]}
    )
    nodes = list(g.objects(S, P))
    assert len(nodes) == 1 and isinstance(nodes[0], BNode)
    qudt = config.prefix_list["qudt"]
    assert list(g.objects(nodes[0], qudt["numericValue"])) == [
        Literal("5280", datatype=XSD_DOUBLE)
    ]
    assert list(g.objects(nodes[0], qudt["unit"])) == [
        URIRef("http://qudt.org/vocab/unit/FT")
    ]


def test_add_triple_unsupported_type_is_skipped(caplog):
    g = Graph()
    with caplog.at_level("WARNING"):
        _add_triple(g, S, P, 42)
    assert len(g) == 0
    assert "unsupported object type" in caplog.text


def test_add_pairs_wraps_scalars():
    g = Graph()
    _add_pairs(g, S, {"rdfs:label": '"single'})
    assert list(g.objects(S, config.prefix_list["rdfs"]["label"])) == [
        Literal("single")
    ]


def test_get_gpkg_zip_files_empty(data_dirs):
    assert get_gpkg_zip_files() == []


def test_triplify_all_without_zips_raises(data_dirs):
    cfg = TriplifierConfig(subject=lambda row, graph: None, fields={})
    with pytest.raises(ValueError):
        triplify_all(cfg, "Whatever")


def _test_config():
    def subject(row, graph):
        feature_id = str(row.get("feature_id", ""))
        if not feature_id:
            return None
        return f"gnisf:{normalize_feature_id(feature_id)}"

    return TriplifierConfig(
        subject=subject,
        fields={
            "name": FieldDescriptor(
                predicate="rdfs:label",
                object=lambda v, r, g: Literal(v, lang="en"),
            ),
            "code": FieldDescriptor(
                predicate="gnis:featureId",
                object=lambda v, r, g: Literal(v),
                optional=True,
            ),
            "note": lambda v, r, g: {"gnis:citation": [f'"{v}']} if v else None,
        },
    )


def test_triplify_all_end_to_end(data_dirs):
    input_dir, output_dir = data_dirs
    make_gpkg_zip(
        input_dir,
        "Test_GPKG.zip",
        {
            "TestTable": [
                {"feature_id": "1", "name": "Alpha", "code": "a", "note": "cited"},
                {"feature_id": "2", "name": "Beta", "code": None, "note": None},
                {"feature_id": "", "name": "skipped", "code": None, "note": None},
            ]
        },
    )
    # A zip without a .gpkg inside is skipped
    import zipfile

    with zipfile.ZipFile(input_dir / "Empty_GPKG.zip", "w") as zf:
        zf.writestr("readme.txt", "no gpkg here")

    graph = triplify_all(_test_config(), "TestTable", "test-output")

    output_path = output_dir / "test-output.ttl"
    assert output_path.exists()

    parsed = Graph()
    parsed.parse(output_path, format="turtle")
    gnisf = config.prefix_list["gnisf"]
    rdfs_label = config.prefix_list["rdfs"]["label"]
    assert (gnisf["1"], rdfs_label, Literal("Alpha", lang="en")) in parsed
    assert (gnisf["2"], rdfs_label, Literal("Beta", lang="en")) in parsed
    # Optional empty field skipped, subjectless row skipped
    assert (
        list(parsed.objects(gnisf["2"], config.prefix_list["gnis"]["featureId"])) == []
    )
    assert len(list(parsed.subjects(rdfs_label, Literal("skipped", lang="en")))) == 0
    assert len(graph) == len(parsed)


def test_triplify_all_missing_required_value_raises(data_dirs):
    input_dir, _ = data_dirs
    make_gpkg_zip(
        input_dir,
        "Test_GPKG.zip",
        {"TestTable": [{"feature_id": "1", "name": None, "code": None, "note": None}]},
    )
    with pytest.raises(ValueError, match="Missing value"):
        triplify_all(_test_config(), "TestTable")
