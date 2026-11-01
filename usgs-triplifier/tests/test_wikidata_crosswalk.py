import gzip
import json
import re

import requests

from usgs_triplifier.lib import wikidata_crosswalk
from usgs_triplifier.lib.wikidata_crosswalk import WikidataCrosswalk
from usgs_triplifier.output_files import OutputFiles

WD = "http://www.wikidata.org/entity"


def _links(item, article=None, geonames_id=None, wof_id=None, loc_id=None, tgn_id=None):
    """
    Builds one LINKS_QUERY result binding.
    """
    b = {"item": {"value": f"{WD}/{item}"}}
    if article:
        b["article"] = {"value": f"https://en.wikipedia.org/wiki/{article}"}
    if geonames_id:
        b["geonamesId"] = {"value": geonames_id}
    if wof_id:
        b["wofId"] = {"value": wof_id}
    if loc_id:
        b["locId"] = {"value": loc_id}
    if tgn_id:
        b["tgnId"] = {"value": tgn_id}
    return b


class FakeEndpoint:
    """
    Answers ITEMS_QUERY with the given GNIS ids and LINKS_QUERY with the
    links of the items in its VALUES block, recording each batch.
    """

    def __init__(self, gnis_ids: dict[str, list[str]], links: list[dict]) -> None:
        self.gnis_ids = gnis_ids
        self.links = links
        self.batches: list[list[str]] = []

    def post(self, url, data, **kwargs) -> "FakeResponse":
        query = data["query"]
        if "VALUES ?item" not in query:
            return FakeResponse(
                [
                    {"item": {"value": f"{WD}/{item}"}, "gnisId": {"value": gnis_id}}
                    for item, ids in self.gnis_ids.items()
                    for gnis_id in ids
                ]
            )
        batch = re.findall(r"wd:(Q\d+)", query)
        self.batches.append(batch)
        return FakeResponse(
            [b for b in self.links if b["item"]["value"].rsplit("/", 1)[-1] in batch]
        )


class FakeResponse:
    def __init__(self, bindings):
        self.text = json.dumps({"results": {"bindings": bindings}})

    def raise_for_status(self):
        pass


def _lines(path) -> list[str]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return f.read().splitlines()


def test_harvest_writes_ntriples_links(data_dirs, monkeypatch, config):
    _, output_dir = data_dirs
    endpoint = FakeEndpoint(
        {"Q130018": ["1414314"], "Q999": ["0426595"], "Q777": ["not-a-gnis-id"]},
        [
            _links(
                "Q130018",
                article="Denali",
                geonames_id="5868589",
                wof_id="102030739",
                loc_id="sh85082617",
                tgn_id="1116119",
            ),
            _links("Q999", loc_id="n81070921"),
            _links("Q777"),
        ],
    )
    monkeypatch.setattr(wikidata_crosswalk.requests, "post", endpoint.post)

    path = WikidataCrosswalk(config).build()

    assert path == output_dir / OutputFiles.WIKIDATA_CROSSWALK
    lines = _lines(path)
    feature = f"<{config.lod_base}/gnis/feature/1414314>"
    assert f"{feature} <http://www.w3.org/2002/07/owl#sameAs> <{WD}/Q130018> ." in lines
    assert (
        f"{feature} <http://www.w3.org/2002/07/owl#sameAs> <http://dbpedia.org/resource/Denali> ."
        in lines
    )
    # GeoNames ids are written to the pairs file and not as triples
    assert not any("sws.geonames.org" in line for line in lines)
    reference = (
        (output_dir / OutputFiles.WIKIDATA_GEONAMES_PAIRS).read_text().splitlines()
    )
    assert "1414314,5868589" in reference
    assert (
        f"{feature} <http://www.w3.org/2002/07/owl#sameAs> <https://whosonfirst.org/id/102030739/> ."
        in lines
    )
    assert (
        f"{feature} <http://www.w3.org/2004/02/skos/core#closeMatch> <http://vocab.getty.edu/tgn/1116119> ."
        in lines
    )
    # sh* ids are subject headings, everything else names; leading zeros are
    # normalized off the feature id
    assert (
        f"{feature} <http://www.w3.org/2004/02/skos/core#closeMatch> <http://id.loc.gov/authorities/subjects/sh85082617> ."
        in lines
    )
    assert (
        f"<{config.lod_base}/gnis/feature/426595> <http://www.w3.org/2004/02/skos/core#closeMatch> <http://id.loc.gov/authorities/names/n81070921> ."
        in lines
    )
    # malformed GNIS ids are skipped entirely
    assert not any("Q777" in line for line in lines)


def test_links_are_queried_in_batches(data_dirs, monkeypatch, config):
    items = {f"Q{n}": [str(n)] for n in range(1, 6)}
    endpoint = FakeEndpoint(items, [_links(item) for item in items])
    monkeypatch.setattr(wikidata_crosswalk.requests, "post", endpoint.post)
    monkeypatch.setattr(WikidataCrosswalk, "BATCH_SIZE", 2)

    lines = _lines(WikidataCrosswalk(config).build())

    assert [len(batch) for batch in endpoint.batches] == [2, 2, 1]
    assert sorted(sum(endpoint.batches, [])) == sorted(items)
    assert len(lines) == 5


def test_an_item_with_two_gnis_ids_links_both_features(data_dirs, monkeypatch, config):
    endpoint = FakeEndpoint({"Q5": ["100", "200"]}, [_links("Q5")])
    monkeypatch.setattr(wikidata_crosswalk.requests, "post", endpoint.post)

    lines = _lines(WikidataCrosswalk(config).build())

    for feature_id in ("100", "200"):
        feature = f"<{config.lod_base}/gnis/feature/{feature_id}>"
        assert f"{feature} <http://www.w3.org/2002/07/owl#sameAs> <{WD}/Q5> ." in lines


def test_a_failed_batch_writes_no_files(data_dirs, monkeypatch, config):
    items = {f"Q{n}": [str(n)] for n in range(1, 6)}
    endpoint = FakeEndpoint(items, [_links(item) for item in items])

    def post(url, data, **kwargs):
        if "wd:Q5" in data["query"]:
            raise requests.ConnectionError("timed out")
        return endpoint.post(url, data, **kwargs)

    monkeypatch.setattr(wikidata_crosswalk.requests, "post", post)
    monkeypatch.setattr(wikidata_crosswalk.time, "sleep", lambda *_: None)
    monkeypatch.setattr(WikidataCrosswalk, "BATCH_SIZE", 2)

    assert WikidataCrosswalk(config).build() is None
    assert not (config.output_directory / OutputFiles.WIKIDATA_CROSSWALK).exists()
    assert not (config.output_directory / OutputFiles.WIKIDATA_GEONAMES_PAIRS).exists()


def test_a_truncated_response_is_retried(data_dirs, monkeypatch, config):
    endpoint = FakeEndpoint({"Q5": ["100"]}, [_links("Q5")])
    calls = []

    def post(url, data, **kwargs):
        calls.append(data["query"])
        response = endpoint.post(url, data, **kwargs)
        if len(calls) == 2:
            response.text = response.text[:20]
        return response

    monkeypatch.setattr(wikidata_crosswalk.requests, "post", post)
    monkeypatch.setattr(wikidata_crosswalk.time, "sleep", lambda *_: None)

    assert WikidataCrosswalk(config).build() is not None
    assert len(calls) == 3


def test_harvest_failure_writes_no_file(data_dirs, monkeypatch, config):
    def boom(*a, **kw):
        raise requests.ConnectionError("no route to wikidata")

    monkeypatch.setattr(wikidata_crosswalk.requests, "post", boom)
    monkeypatch.setattr(wikidata_crosswalk.time, "sleep", lambda *_: None)
    assert WikidataCrosswalk(config).build() is None
    assert not (config.output_directory / OutputFiles.WIKIDATA_CROSSWALK).exists()
