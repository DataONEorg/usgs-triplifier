from collections.abc import Callable
from typing import ClassVar

from rdflib import Literal, URIRef
from rdflib.namespace import OWL

from ...output_files import OutputFiles
from ...usgs_products import UsgsProduct, UsgsProducts
from .identifiers import FeatureIds
from .rdf import NTriplesWriter
from .triplifier import FieldDescriptor, Triplifier


class UnitsTriplifier(Triplifier):
    """
    Converts the GNIS government units (GovernmentUnits) into units.nt.gz.

    Each COUNTRY, STATE and COUNTY unit is written with its gnisf-alias: IRI
    (country, state, or state.county) as the subject, which is the IRI that
    features' gnis:country, gnis:state and gnis:county triples point at. The
    alias is written owl:sameAs the unit's gnisf: IRI, which has the
    gnis:featureId.
    """

    product: ClassVar[UsgsProduct] = UsgsProducts.UNITS
    output_name: ClassVar[str] = OutputFiles.UNITS

    def fields(self) -> dict[str, FieldDescriptor | Callable]:
        """
        Lists the unit columns that become triples.

        :return: Mapping of column name to its field mapping.
        """
        return {
            "unit_type": FieldDescriptor("rdf:type", self.unit_type_object),
            "county_numeric": FieldDescriptor(
                "gnis:countyCode", self.county_numeric_object, optional=True
            ),
            "county_name": FieldDescriptor(
                "gnis:countyName", self.county_name_object, optional=True
            ),
            "state_numeric": FieldDescriptor(
                "gnis:stateId", self.state_only_object, optional=True
            ),
            "state_alpha": FieldDescriptor(
                "gnis:stateCode", self.state_only_object, optional=True
            ),
            "state_name": self.state_name_field,
            "country_name": FieldDescriptor("gnis:country", self.country_name_object),
            "feature_name": FieldDescriptor("rdfs:label", self.english_literal),
        }

    def subject(self, row: dict[str, str], writer: NTriplesWriter) -> str | None:
        """
        Builds the unit's alias IRI and writes owl:sameAs from it to the
        unit's gnisf: IRI.

        :param row: Source row.
        :param writer: Writer the owl:sameAs triple is added to.
        :return: The unit's gnisf-alias: IRI, or None for a unit type other
            than COUNTRY, STATE or COUNTY.
        """
        unit_type = row.get("unit_type", "")
        state = FeatureIds.alias_part(row.get("state_name", ""))
        if unit_type == "COUNTY":
            alias = f"{state}.{FeatureIds.alias_part(row.get('county_name', ''))}"
        elif unit_type == "STATE":
            alias = state
        elif unit_type == "COUNTRY":
            alias = FeatureIds.alias_part(row.get("country_name", ""))
        else:
            return None

        feature_id = FeatureIds.normalize(row.get("feature_id", ""))
        writer.add(
            (
                self.config.prefix_list["gnisf-alias"][alias],
                OWL.sameAs,
                self.config.prefix_list["gnisf"][feature_id],
            )
        )
        return f"gnisf-alias:{alias}"

    def unit_type_object(self, value: str, row: dict) -> URIRef:
        """
        Builds the rdf:type of the unit, e.g. COUNTY to gnis:County.

        :param value: Unit type in capitals.
        :param row: Source row (unused).
        :return: The gnis: class IRI.
        """
        return self.config.prefix_list["gnis"][value.capitalize()]

    def county_numeric_object(self, value: str, row: dict) -> Literal | str:
        """
        Builds the gnis:countyCode literal, which only COUNTY units get.
        County FIPS codes have three digits, and the source drops leading
        zeros, so they are restored.

        :param value: County code.
        :param row: Source row; unit_type selects whether a triple is written.
        :return: The three-digit code as a plain literal for a COUNTY,
            otherwise an empty string.
        """
        return Literal(value.zfill(3)) if row.get("unit_type") == "COUNTY" else ""

    def county_name_object(self, value: str, row: dict) -> Literal | str:
        """
        Builds the gnis:countyName literal, which only COUNTY units get.

        :param value: County name.
        :param row: Source row; unit_type selects whether a triple is written.
        :return: The name as an English literal for a COUNTY, otherwise an
            empty string.
        """
        return (
            self.english_literal(value, row) if row.get("unit_type") == "COUNTY" else ""
        )

    def state_only_object(self, value: str, row: dict) -> Literal | str:
        """
        Builds the gnis:stateId or gnis:stateCode literal, which only STATE
        units get.

        :param value: State FIPS code or two-letter code.
        :param row: Source row; unit_type selects whether a triple is written.
        :return: The value as a plain literal for a STATE, otherwise an empty
            string.
        """
        return Literal(value) if row.get("unit_type") == "STATE" else ""

    def state_name_field(
        self, value: str, row: dict, writer: NTriplesWriter
    ) -> dict | None:
        """
        Builds gnis:state linking a COUNTY to its state's alias, or
        gnis:stateName with the name of a STATE.

        :param value: Full state name.
        :param row: Source row; unit_type selects the triple.
        :param writer: Writer the row's triples go to (unused).
        :return: The predicate-object pair, or None when the state name is empty.
        """
        if not value:
            return None
        if row.get("unit_type") == "COUNTY":
            return {"gnis:state": [f"gnisf-alias:{FeatureIds.alias_part(value)}"]}
        return {"gnis:stateName": [Literal(value, lang="en")]}

    def country_name_object(self, value: str, row: dict) -> URIRef | str:
        """
        Builds the gnis:country link from a STATE or COUNTY to the country's alias.

        :param value: Country name.
        :param row: Source row; a COUNTRY row gets no link to itself.
        :return: The country's gnisf-alias: IRI, or an empty string for a COUNTRY.
        """
        if row.get("unit_type") == "COUNTRY":
            return ""
        return self.config.prefix_list["gnisf-alias"][FeatureIds.alias_part(value)]
