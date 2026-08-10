from usgs_triplifier.config import Config, config


def test_default_bases_are_absolute_uris():
    assert config.lod_base.startswith("http://")
    assert config.geo_base.startswith("http://")


def test_prefix_list_contains_static_and_computed_namespaces():
    prefixes = config.prefix_list
    assert str(prefixes["rdf"]) == "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    assert str(prefixes["gnisf"]) == f"{config.lod_base}/gnis/feature/"
    assert str(prefixes["usgeo-point"]) == f"{config.geo_base}/point/"


def test_prefixes_follow_configured_bases():
    custom = Config(
        lod_base="http://example.org/lod", geo_base="http://example.org/geo"
    )
    assert str(custom.prefix_list["gnis"]) == "http://example.org/lod/gnis/ontology/"
    assert str(custom.prefix_list["usgeo-polygon"]) == "http://example.org/geo/polygon/"
