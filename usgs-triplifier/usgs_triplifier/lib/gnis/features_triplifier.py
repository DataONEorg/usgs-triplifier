from collections.abc import Callable
from typing import ClassVar

from rdflib import Literal, URIRef
from rdflib.namespace import OWL

from ...config import Config
from ...output_files import OutputFiles
from ...states import States
from ...usgs_products import UsgsProduct, UsgsProducts
from .identifiers import FeatureIds
from .rdf import NTriplesWriter, Terms
from .triplifier import FieldDescriptor, Triplifier


class FeaturesTriplifier(Triplifier):
    """
    Converts the GNIS features (DomesticNames, or NationalFile in a legacy
    dump) into features.nt.gz. Each feature gets its id, class, state,
    county, point geometry, map name and dates, and for legacy dumps its
    elevation.
    """

    product: ClassVar[UsgsProduct] = UsgsProducts.FEATURES
    output_name: ClassVar[str] = OutputFiles.FEATURES

    # GNIS feature classes (spaces removed) whose usgs: class has a
    # different local name
    CLASS_RENAMES: ClassVar[dict[str, str]] = {
        "Range": "MountainRange",
        "Falls": "Waterfall",
        "Woods": "Woodland",
        "Oilfield": "OilField",
        "Civil": "CivilGovernment",
        "Pillar": "Rock",
    }

    def __init__(self, config: Config) -> None:
        """
        Creates the triplifier with no aliases recorded.

        :param config: Settings, as for Triplifier.
        """
        super().__init__(config)
        # Alias id -> ids of the features with that alias, filled by subject()
        self._aliases: dict[str, list[str]] = {}
        # Rows skipped by subject() because their state code and number differ
        self._mismatched_rows = 0
        # Ids of the features whose elevation has been written
        self._elevated_features: set[str] = set()

    def run(self) -> int:
        """
        Writes features.nt.gz, then feature-aliases.nt.gz from the aliases
        recorded while the features were read.

        :return: Number of triples written to features.nt.gz.
        :raises FileNotFoundError: If the input directory has no features zip.
        :raises ValueError: If a feature has no id or class.
        """
        self._aliases = {}
        self._mismatched_rows = 0
        self._elevated_features = set()
        count = super().run()
        if self._mismatched_rows:
            self._log.warning(
                f"Skipped {self._mismatched_rows} rows whose state code does not "
                "match their state number"
            )
        self._write_aliases()
        return count

    def fields(self) -> dict[str, FieldDescriptor | Callable]:
        """
        Lists the feature columns that become triples.

        :return: Mapping of column name to its field mapping.
        """
        fields = {
            "feature_id": FieldDescriptor("gnis:featureId", self.feature_id_object),
            "feature_class": FieldDescriptor("rdf:type", self.feature_class_object),
            "state_name": FieldDescriptor(
                "gnis:state", self.state_object, optional=True
            ),
            "county_name": FieldDescriptor(
                "gnis:county", self.county_object, optional=True
            ),
            "prim_lat_dec": self.prim_lat_dec_field,
            "map_name": FieldDescriptor(
                "gnis:mapName", self.english_literal, optional=True
            ),
            "date_created": FieldDescriptor(
                "gnis:dateFeatureCreated", self.date_object, optional=True
            ),
            "date_edited": FieldDescriptor(
                "gnis:dateFeatureEdited", self.date_object, optional=True
            ),
        }
        if self.config.legacy_dump:
            fields["elev_in_ft"] = self.elev_in_ft_field
        return fields

    def subject(self, row: dict[str, str], writer: NTriplesWriter) -> str | None:
        """
        Builds the feature's IRI and records its alias.

        Legacy dumps give only the state code (state_alpha), so this sets
        row["state_name"] to the full name. A legacy row whose U.S. state code
        does not match its state number (state_numeric) is skipped. The 2021
        NationalFile has 52 such rows, which copy Alaska features in the
        Chugach Census Area under Arizona.

        :param row: Source row.
        :param writer: Writer the row's triples go to (unused).
        :return: The feature's gnisf: IRI, or None to skip the row.
        """
        feature_id = FeatureIds.normalize(row.get("feature_id", ""))

        if not row.get("state_name") and row.get("state_alpha"):
            alpha = row["state_alpha"]
            number = States.number_for(alpha)
            if number and row.get("state_numeric") and row["state_numeric"] != number:
                self._mismatched_rows += 1
                return None
            row["state_name"] = States.name_for(alpha) or alpha

        alias = ".".join(
            [
                FeatureIds.alias_part(row.get("state_name", "")),
                FeatureIds.alias_part(row.get("county_name", "")),
                self._class_name(row.get("feature_class", "")),
                FeatureIds.alias_part(row.get("feature_name", "")),
            ]
        )
        self._aliases.setdefault(alias, []).append(feature_id)

        return f"gnisf:{feature_id}"

    @staticmethod
    def feature_id_object(value: str, row: dict) -> Literal:
        """
        Builds the gnis:featureId literal, in the form used in the IRI.

        :param value: Feature id as read from the source.
        :param row: Source row (unused).
        :return: The id without leading zeros, as a plain literal.
        """
        return Literal(FeatureIds.normalize(value))

    def feature_class_object(self, value: str, row: dict) -> URIRef:
        """
        Builds the rdf:type of the feature.

        :param value: GNIS feature class, e.g. "Populated Place".
        :param row: Source row (unused).
        :return: The usgs: class IRI.
        """
        return self.config.prefix_list["usgs"][self._class_name(value)]

    def state_object(self, value: str, row: dict) -> URIRef:
        """
        Builds the gnis:state link to the state's alias.

        :param value: Full state name.
        :param row: Source row (unused).
        :return: The state's gnisf-alias: IRI.
        """
        return self.config.prefix_list["gnisf-alias"][FeatureIds.alias_part(value)]

    def county_object(self, value: str, row: dict) -> URIRef:
        """
        Builds the gnis:county link to the county's alias (state.county).

        :param value: County name.
        :param row: Source row.
        :return: The county's gnisf-alias: IRI, or gnis:UnknownCounty for an
            empty value.
        """
        if value:
            state = FeatureIds.alias_part(row.get("state_name", ""))
            county = FeatureIds.alias_part(value)
            return self.config.prefix_list["gnisf-alias"][f"{state}.{county}"]
        return self.config.prefix_list["gnis"]["UnknownCounty"]

    def prim_lat_dec_field(
        self, value: str, row: dict, writer: NTriplesWriter
    ) -> dict | None:
        """
        Writes the feature's point geometry and links the feature to it.

        :param value: Primary latitude in decimal degrees.
        :param row: Source row; prim_long_dec and feature_id are read from it.
        :param writer: Writer the asWKT triple is added to.
        :return: The geosparql:hasGeometry pair, or None when no geometry is
            written because a coordinate is missing, not a number or zero.
        """
        lng = row.get("prim_long_dec") or ""
        try:
            if float(value) == 0 or float(lng) == 0:
                return None
        except ValueError:
            return None

        feature_id = FeatureIds.normalize(row.get("feature_id", ""))
        geometry = URIRef(f"{self.config.geo_base}/point/gnisf.{feature_id}")
        geosparql = self.config.prefix_list["geosparql"]
        writer.add(
            (geometry, geosparql["asWKT"], Terms.wkt_literal(f"POINT({lng} {value})"))
        )
        return {"geosparql:hasGeometry": [geometry]}

    def elev_in_ft_field(
        self, value: str, row: dict, writer: NTriplesWriter
    ) -> dict | None:
        """
        Builds the gnis:elevation blank node, with the elevation as a
        qudt:numericValue (xsd:double) and qudt:unit unit:FT.

        A legacy dump lists a feature that crosses a state or national border
        once per state and county, with the same elevation in every row, so
        only the feature's first elevation is written.

        :param value: Elevation in feet.
        :param row: Source row; feature_id is read from it.
        :param writer: Writer the row's triples go to (unused).
        :return: The gnis:elevation pair, or None when the value is blank or
            "0" or the feature already has an elevation.
        """
        elevation = value.strip()
        if not elevation or elevation == "0":
            return None
        feature_id = FeatureIds.normalize(row.get("feature_id", ""))
        if feature_id in self._elevated_features:
            return None
        self._elevated_features.add(feature_id)
        return {
            "gnis:elevation": {
                "qudt:numericValue": [f'^xsd:double"{elevation}'],
                "qudt:unit": ["unit:FT"],
            },
        }

    def date_object(self, value: str, row: dict) -> Literal | str:
        """
        Builds a creation or edit date literal.

        :param value: Date as MM/DD/YYYY, or an ISO 8601 timestamp such as
            1998-10-06T06:13:42.
        :param row: Source row (unused).
        :return: An xsd:date literal, or an empty string when the value is
            in neither format, so no triple is written.
        """
        return self.date_literal(value) or ""

    def _class_name(self, feature_class: str) -> str:
        """
        Converts a GNIS feature class to the local name of its usgs: class.

        :param feature_class: GNIS feature class, e.g. "Populated Place".
        :return: The class with spaces removed and CLASS_RENAMES applied,
            e.g. "PopulatedPlace".
        """
        name = feature_class.replace(" ", "")
        return self.CLASS_RENAMES.get(name, name)

    def _write_aliases(self) -> None:
        """
        Writes feature-aliases.nt.gz from the aliases recorded by subject().
        """
        gnisf = self.config.prefix_list["gnisf"]
        gnisf_alias = self.config.prefix_list["gnisf-alias"]
        disambiguates_to = self.config.prefix_list["gnis"]["disambiguatesTo"]

        path = self.config.output_directory / OutputFiles.FEATURE_ALIASES
        with NTriplesWriter(path) as writer:
            for alias, feature_ids in self._aliases.items():
                alias_iri = gnisf_alias[alias]
                if len(feature_ids) == 1:
                    writer.add((alias_iri, OWL.sameAs, gnisf[feature_ids[0]]))
                else:
                    for feature_id in feature_ids:
                        writer.add((alias_iri, disambiguates_to, gnisf[feature_id]))
        self._log.info(f"Wrote {len(writer)} alias triples to {path}")
