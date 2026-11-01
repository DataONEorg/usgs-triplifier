import json
import logging
import re
import time
from collections.abc import Iterable, Iterator
from itertools import batched
from pathlib import Path
from typing import ClassVar, TextIO

import requests

from ..output_files import OutputFiles
from .crosswalk import Crosswalk
from .gnis.identifiers import FeatureIds


class WikidataQueryError(Exception):
    """
    Raised when a Wikidata query fails on every attempt.
    """


class WikidataCrosswalk(Crosswalk):
    """
    Links GNIS features to Wikidata and the datasets Wikidata links them to.

    Wikidata items record their GNIS feature id in property P590. For every
    such item the crosswalk writes these links.

        - owl:sameAs the Wikidata item
        - owl:sameAs the DBpedia resource of the item's English Wikipedia article
        - owl:sameAs the Who's On First place (P6766)
        - skos:closeMatch the Library of Congress authority (P244)
        - skos:closeMatch the Getty Thesaurus of Geographic Names place (P1667)

    The items' GeoNames ids (P1566) are written to wikidata-geonames.csv.

    The items and their GNIS ids are listed with one query. Their links are
    queried in batches of BATCH_SIZE items, because a single query for every
    item's links runs past the endpoint's 60 second limit.
    """

    output_name: ClassVar[str] = OutputFiles.WIKIDATA_CROSSWALK

    ITEMS_QUERY: ClassVar[str] = "SELECT ?item ?gnisId WHERE { ?item wdt:P590 ?gnisId }"

    # ITEMS is replaced by the batch's item terms, e.g. "wd:Q130018 wd:Q999"
    LINKS_QUERY: ClassVar[
        str
    ] = """SELECT ?item ?article ?geonamesId ?wofId ?locId ?tgnId WHERE {
  VALUES ?item { ITEMS }
  OPTIONAL { ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . }
  OPTIONAL { ?item wdt:P1566 ?geonamesId . }
  OPTIONAL { ?item wdt:P6766 ?wofId . }
  OPTIONAL { ?item wdt:P244 ?locId . }
  OPTIONAL { ?item wdt:P1667 ?tgnId . }
}"""

    # A batch of 10,000 items took about 12 s on 2026-10-29
    BATCH_SIZE: ClassVar[int] = 10_000

    ITEM_PREFIX: ClassVar[str] = "http://www.wikidata.org/entity/"
    R_ITEM_ID: ClassVar[re.Pattern] = re.compile(r"^Q\d+$")

    # The endpoint sometimes returns errors or truncated results under load,
    # so a failed query is retried, waiting RETRY_WAIT_S times the attempt
    # number in between
    ATTEMPTS: ClassVar[int] = 6
    RETRY_WAIT_S: ClassVar[int] = 15

    _log: ClassVar[logging.Logger] = logging.getLogger(__name__)

    def build(self) -> Path | None:
        """
        Queries Wikidata and writes the links and the GeoNames pairs. When a
        query fails on every attempt, the files written so far are deleted.

        :return: Path of the links file, or None when a query failed.
        """
        pairs_path = self.config.output_directory / OutputFiles.WIKIDATA_GEONAMES_PAIRS
        try:
            gnis_ids = self._gnis_ids()
            with open(pairs_path, "w", encoding="utf-8") as pairs:
                self.write_lines(self._links(self._link_bindings(gnis_ids), pairs))
        except WikidataQueryError as error:
            self._log.warning(f"{error}; writing no Wikidata links")
            self.output_path.unlink(missing_ok=True)
            pairs_path.unlink(missing_ok=True)
            return None
        return self.output_path

    def _gnis_ids(self) -> dict[str, list[str]]:
        """
        Lists the Wikidata items that have a GNIS id.

        :return: Item id (e.g. Q130018) -> the item's GNIS ids.
        :raises WikidataQueryError: If the query failed on every attempt.
        """
        gnis_ids: dict[str, list[str]] = {}
        for binding in self._query(self.ITEMS_QUERY):
            item_id = binding["item"]["value"].removeprefix(self.ITEM_PREFIX)
            # An id that is not Q followed by digits can't be written as a
            # wd: term in LINKS_QUERY
            if self.R_ITEM_ID.match(item_id):
                gnis_ids.setdefault(item_id, []).append(binding["gnisId"]["value"])
        self._log.info(f"{len(gnis_ids)} Wikidata items have a GNIS id")
        return gnis_ids

    def _link_bindings(self, gnis_ids: dict[str, list[str]]) -> Iterator[dict]:
        """
        Queries the links of the items in batches of BATCH_SIZE.

        :param gnis_ids: Item id -> the item's GNIS ids.
        :return: Iterator of LINKS_QUERY bindings, one per GNIS id of the
            binding's item, each with the GNIS id added as "gnisId".
        :raises WikidataQueryError: If a batch's query failed on every attempt.
        """
        batches = list(batched(sorted(gnis_ids), self.BATCH_SIZE))
        for number, batch in enumerate(batches, 1):
            self._log.info(f"Querying Wikidata links, batch {number} of {len(batches)}")
            terms = " ".join(f"wd:{item_id}" for item_id in batch)
            for binding in self._query(self.LINKS_QUERY.replace("ITEMS", terms)):
                item_id = binding["item"]["value"].removeprefix(self.ITEM_PREFIX)
                for gnis_id in gnis_ids.get(item_id, []):
                    yield {**binding, "gnisId": {"value": gnis_id}}

    def _query(self, query: str) -> list[dict]:
        """
        Runs a query against the Wikidata SPARQL endpoint.

        :param query: SPARQL SELECT query.
        :return: The result bindings.
        :raises WikidataQueryError: If every attempt failed.
        """
        for attempt in range(1, self.ATTEMPTS + 1):
            try:
                response = requests.post(
                    self.config.wikidata_endpoint,
                    data={"query": query},
                    headers={
                        "Accept": "application/sparql-results+json",
                        "User-Agent": "usgs-triplifier (support@dataone.org)",
                    },
                    timeout=300,
                )
                response.raise_for_status()
                # Some returned values contain raw control characters, which
                # json.loads rejects unless strict is False. A query that runs
                # past the endpoint's time limit returns a truncated body,
                # which json.loads rejects.
                return json.loads(response.text, strict=False)["results"]["bindings"]
            except (requests.RequestException, ValueError, KeyError) as error:
                self._log.warning(f"Wikidata query attempt {attempt} failed: {error}")
                if attempt < self.ATTEMPTS:
                    time.sleep(self.RETRY_WAIT_S * attempt)
        raise WikidataQueryError(f"Wikidata query failed {self.ATTEMPTS} times")

    def _links(self, bindings: Iterable[dict], pairs: TextIO) -> Iterator[str]:
        """
        Yields the link lines for the query results and writes each GeoNames
        pair to the pairs file. Results whose GNIS id is not a number are skipped.

        :param bindings: Query result bindings.
        :param pairs: Open text file the "feature_id,geonameid" lines are written to.
        :return: Iterator of N-Triples lines.
        """
        for binding in bindings:
            gnis_id = binding["gnisId"]["value"].strip()
            if not gnis_id.isdigit():
                continue
            feature = self.feature_iri(gnis_id)

            yield f"{feature} {self.OWL_SAMEAS} <{binding['item']['value']}> ."
            if "article" in binding:
                title = binding["article"]["value"].rsplit("/wiki/", 1)[-1]
                yield f"{feature} {self.OWL_SAMEAS} <http://dbpedia.org/resource/{title}> ."
            if self._numeric(binding, "geonamesId"):
                feature_id = FeatureIds.normalize(gnis_id)
                pairs.write(f"{feature_id},{binding['geonamesId']['value']}\n")
            if self._numeric(binding, "wofId"):
                wof_id = binding["wofId"]["value"]
                yield f"{feature} {self.OWL_SAMEAS} <https://whosonfirst.org/id/{wof_id}/> ."
            if "locId" in binding:
                loc_uri = self._loc_authority_uri(binding["locId"]["value"])
                yield f"{feature} {self.SKOS_CLOSEMATCH} <{loc_uri}> ."
            if self._numeric(binding, "tgnId"):
                tgn_id = binding["tgnId"]["value"]
                yield f"{feature} {self.SKOS_CLOSEMATCH} <http://vocab.getty.edu/tgn/{tgn_id}> ."

    @staticmethod
    def _numeric(binding: dict, variable: str) -> bool:
        """
        Checks whether a query result has a numeric value for a variable.

        :param binding: One query result binding.
        :param variable: Variable name, e.g. "wofId".
        :return: True when the variable is bound to a string of digits.
        """
        return variable in binding and binding[variable]["value"].isdigit()

    @staticmethod
    def _loc_authority_uri(loc_id: str) -> str:
        """
        Builds the id.loc.gov URI of a Library of Congress authority.

        :param loc_id: P244 value. Ids starting with "sh" are subject headings;
            all others are name authorities.
        :return: The authority URI.
        """
        namespace = "subjects" if loc_id.startswith("sh") else "names"
        return f"http://id.loc.gov/authorities/{namespace}/{loc_id}"
