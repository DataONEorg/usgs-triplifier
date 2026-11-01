import pytest
from rdflib import BNode, Graph, Literal, URIRef

from conftest import make_text_zip, parse_nt_gz
from usgs_triplifier.lib.gnis.identifiers import FeatureIds
from usgs_triplifier.lib.gnis.rdf import NTriplesWriter, Terms
from usgs_triplifier.lib.gnis.triplifier import FieldDescriptor, Triplifier
from usgs_triplifier.usgs_products import UsgsProduct

XSD_DOUBLE = URIRef("http://www.w3.org/2001/XMLSchema#double")
S = URIRef("http://example.org/s")
P = URIRef("http://example.org/p")


class SampleTriplifier(Triplifier):
    """
    Triplifier over Test_*.zip that maps name (required), code (optional)
    and note (field callable), and skips rows without a feature_id.
    """

    product = UsgsProduct(key="test", pattern="Test_*.zip")
    output_name = "test-output.nt.gz"

    def subject(self, row: dict, writer) -> str | None:
        """
        Builds the IRI of the row's feature.

        :param row: Source row.
        :param writer: Writer the row's triples go to (unused).
        :return: The gnisf: IRI, or None when feature_id is empty.
        """
        if not row.get("feature_id"):
            return None
        return f"gnisf:{FeatureIds.normalize(row['feature_id'])}"

    def fields(self) -> dict:
        """
        Lists the sample columns.

        :return: Mapping of column name to its field mapping.
        """
        return {
            "name": FieldDescriptor("rdfs:label", lambda v, r: Literal(v, lang="en")),
            "code": FieldDescriptor(
                "gnis:featureId", lambda v, r: Literal(v), optional=True
            ),
            "note": lambda v, r, w: {"gnis:citation": [f'"{v}']} if v else None,
        }


def test_normalize_feature_id():
    assert FeatureIds.normalize(1234.0) == "1234"
    assert FeatureIds.normalize(7) == "7"
    assert FeatureIds.normalize("0123") == "123"
    assert FeatureIds.normalize("000") == "0"
    assert FeatureIds.normalize("") == "0"
    assert FeatureIds.normalize(" 42 ") == "42"
    with pytest.raises(ValueError):
        FeatureIds.normalize("452 acres in size")


def test_alias_part_replaces_non_word_characters():
    assert FeatureIds.alias_part("San Juan Co.") == "San_Juan_Co_"
    assert FeatureIds.alias_part("word") == "word"


def test_parse_object_notations(config):
    assert Terms(config.prefix_list).parse_object(">http://example.org/x") == URIRef(
        "http://example.org/x"
    )
    assert Terms(config.prefix_list).parse_object('"hello') == Literal("hello")
    assert Terms(config.prefix_list).parse_object('@en"hello') == Literal(
        "hello", lang="en"
    )
    assert Terms(config.prefix_list).parse_object('^xsd:double"1.5') == Literal(
        "1.5", datatype=XSD_DOUBLE
    )
    gnis = config.prefix_list["gnis"]
    assert Terms(config.prefix_list).parse_object("gnis:Thing") == gnis["Thing"]
    assert Terms(config.prefix_list).parse_object("plain value") == Literal(
        "plain value"
    )


def test_resolve_iri(config):
    assert Terms(config.prefix_list).resolve_iri(">http://example.org/a") == URIRef(
        "http://example.org/a"
    )
    assert (
        Terms(config.prefix_list).resolve_iri("gnisf:123")
        == config.prefix_list["gnisf"]["123"]
    )
    assert Terms(config.prefix_list).resolve_iri("unknown:thing") == URIRef(
        "unknown:thing"
    )
    assert Terms(config.prefix_list).resolve_iri("nocolon") == URIRef("nocolon")


def test_add_object_literal_string_and_uri(config):
    g = Graph()
    Terms(config.prefix_list).add_object(g, S, P, Literal("x"))
    Terms(config.prefix_list).add_object(g, S, P, '"y')
    Terms(config.prefix_list).add_object(g, S, P, URIRef("http://example.org/o"))
    assert (S, P, Literal("x")) in g
    assert (S, P, Literal("y")) in g
    assert (S, P, URIRef("http://example.org/o")) in g


def test_add_object_dict_becomes_blank_node(config):
    g = Graph()
    Terms(config.prefix_list).add_object(
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


def test_add_object_unsupported_type_is_skipped(caplog, config):
    g = Graph()
    with caplog.at_level("WARNING"):
        Terms(config.prefix_list).add_object(g, S, P, 42)
    assert len(g) == 0
    assert "unsupported object type" in caplog.text


def test_add_pairs_wraps_scalars(config):
    g = Graph()
    Terms(config.prefix_list).add_pairs(g, S, {"rdfs:label": '"single'})
    assert list(g.objects(S, config.prefix_list["rdfs"]["label"])) == [
        Literal("single")
    ]


def test_writer_counts_every_line_it_writes(tmp_path):
    path = tmp_path / "sub" / "out.nt.gz"
    with NTriplesWriter(path) as writer:
        writer.add((S, P, Literal("x")))
        writer.add((S, P, Literal("x")))
    assert len(writer) == 2
    assert len(parse_nt_gz(path)) == 1


def test_triplifier_without_zips_raises(config):
    with pytest.raises(FileNotFoundError, match="Test_\\*.zip"):
        SampleTriplifier(config).run()


def test_triplifier_end_to_end(data_dirs, config):
    input_dir, output_dir = data_dirs
    make_text_zip(
        input_dir,
        "Test_Text.zip",
        "Text/Test.txt",
        [
            # Header case is normalized, as legacy dumps are uppercase
            "FEATURE_ID|Name|code|note",
            "1|Alpha|a|cited",
            "2|Beta||",
            "|skipped||",
            # A short row reads as empty fields, not missing keys
            "3|Gamma",
        ],
    )

    count = SampleTriplifier(config).run()

    parsed = parse_nt_gz(output_dir / "test-output.nt.gz")
    gnisf = config.prefix_list["gnisf"]
    rdfs_label = config.prefix_list["rdfs"]["label"]
    feature_id = config.prefix_list["gnis"]["featureId"]
    assert (gnisf["1"], rdfs_label, Literal("Alpha", lang="en")) in parsed
    assert (gnisf["2"], rdfs_label, Literal("Beta", lang="en")) in parsed
    assert (gnisf["3"], rdfs_label, Literal("Gamma", lang="en")) in parsed
    # Optional empty field skipped, subjectless row skipped
    assert list(parsed.objects(gnisf["2"], feature_id)) == []
    assert list(parsed.objects(gnisf["3"], feature_id)) == []
    assert len(list(parsed.subjects(rdfs_label, Literal("skipped", lang="en")))) == 0
    assert count == len(parsed)


def test_triplifier_missing_required_value_raises(data_dirs, config):
    input_dir, _ = data_dirs
    make_text_zip(
        input_dir,
        "Test_Text.zip",
        "Text/Test.txt",
        ["feature_id|name|code|note", "1||a|"],
    )
    with pytest.raises(ValueError, match="Missing value"):
        SampleTriplifier(config).run()


def test_triplifier_without_input_writes_nothing(data_dirs, config):
    _, output_dir = data_dirs
    with pytest.raises(FileNotFoundError):
        SampleTriplifier(config).run()
    assert not (output_dir / "test-output.nt.gz").exists()
