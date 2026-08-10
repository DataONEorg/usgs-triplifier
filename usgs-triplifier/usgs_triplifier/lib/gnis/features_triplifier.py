from datetime import datetime

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, XSD

from .triplifier import (
    triplify_all,
    TriplifierConfig,
    FieldDescriptor,
    clean,
    normalize_feature_id,
)
from ...config import config

# Class name mappings
GNIS_CLASS_MAPPINGS = {
    "Range": "MountainRange",
    "Falls": "Waterfall",
    "Woods": "Woodland",
    "Oilfield": "OilField",
    "Civil": "CivilGovernment",
    "Pillar": "Rock",
}

# Track feature aliases for disambiguation
feature_aliases: dict[str, list[str]] = {}


class FeaturesTriplifier:
    """
    Abstraction over creating triples out of the features dataset.

    Uses the DomesticNames table from GPKG files which contains:
        - feature_id, feature_name, feature_class
        - state_name, state_numeric, county_name, county_numeric
        - map_name, date_created, date_edited
        - prim_lat_dec, prim_long_dec (coordinates)
    """

    def __init__(self):
        config.output_directory.mkdir(parents=True, exist_ok=True)
        geoms_file = open(config.output_directory / "geoms.tsv", "w")
        field_mappings = {
            "feature_id": FieldDescriptor(
                predicate="gnis:featureId",
                object=self.feature_id_object,
            ),
            "feature_class": FieldDescriptor(
                predicate="rdf:type",
                object=self.feature_class_object,
            ),
            "state_name": FieldDescriptor(
                predicate="gnis:state",
                object=self.state_object,
                optional=True,
            ),
            "county_name": FieldDescriptor(
                predicate="gnis:county",
                object=self.county_object,
                optional=True,
            ),
            "prim_lat_dec": self.make_prim_lat_dec_field(geoms_file),
            "elev_in_ft": self.elev_in_ft_field,
            "map_name": FieldDescriptor(
                predicate="gnis:mapName",
                object=self.map_name_object,
                optional=True,
            ),
            "date_created": FieldDescriptor(
                predicate="gnis:dateFeatureCreated",
                object=self.date_object,
                optional=True,
            ),
            "date_edited": FieldDescriptor(
                predicate="gnis:dateFeatureEdited",
                object=self.date_object,
                optional=True,
            ),
        }
        triples_mapping = TriplifierConfig(
            subject=self.get_subject,
            fields=field_mappings,
        )
        triplify_all(triples_mapping, "DomesticNames", "features")
        self._on_complete(geoms_file)

    def get_subject(self, row: dict, graph: Graph) -> str | None:
        """
        Generate subject IRI for a GNIS feature.

        :param row: Dictionary representing a row from the GPKG table.
        :param graph: RDF graph (unused but required by interface).
        :return: Subject IRI string or None if invalid.
        """
        feature_id = normalize_feature_id(row.get("feature_id", ""))

        # Get and normalize class name
        feature_class = str(row.get("feature_class", "")).replace(" ", "")
        if feature_class in GNIS_CLASS_MAPPINGS:
            feature_class = GNIS_CLASS_MAPPINGS[feature_class]

        # Get state name (GPKG uses state_name instead of state_alpha)
        state_name = str(row.get("state_name", ""))

        # Build feature alias
        feature_name = str(row.get("feature_name", ""))
        county_name = str(row.get("county_name", ""))
        alias_id = f"{clean(state_name)}.{clean(county_name)}.{feature_class}.{clean(feature_name)}"

        # Track aliases for later disambiguation
        if alias_id in feature_aliases:
            feature_aliases[alias_id].append(feature_id)
        else:
            feature_aliases[alias_id] = [feature_id]

        # Store class for later use
        row["_class"] = feature_class

        return f"gnisf:{feature_id}"

    def feature_id_object(self, value: str, row: dict, graph: Graph) -> Literal:
        """
        Convert feature ID to literal.

        :param value: Feature ID value.
        :param row: Dictionary representing a row from the GPKG table.
        :param graph: RDF graph (unused but required by interface).
        :return: RDF Literal containing the feature ID.
        """
        return Literal(value)

    def feature_class_object(self, value: str, row: dict, graph: Graph) -> URIRef:
        """
        Convert feature class to RDF type.

        :param value: Feature class name.
        :param row: Dictionary representing a row from the GPKG table.
        :param graph: RDF graph (unused but required by interface).
        :return: URIRef for the corresponding USGS ontology class.
        """
        class_name = value.replace(" ", "")
        if class_name in GNIS_CLASS_MAPPINGS:
            class_name = GNIS_CLASS_MAPPINGS[class_name]
        return config.prefix_list["usgs"][class_name]

    def state_object(self, value: str, row: dict, graph: Graph) -> URIRef | str:
        """
        Convert state name to feature alias URI.

        :param value: State name value.
        :param row: Dictionary representing a row from the GPKG table.
        :param graph: RDF graph (unused but required by interface).
        :return: URIRef for the state alias or empty string if no value.
        """
        if not value:
            return ""
        return config.prefix_list["gnisf-alias"][clean(value)]

    def county_object(self, value: str, row: dict, graph: Graph) -> URIRef:
        """
        Convert county name to feature alias URI.

        :param value: County name value.
        :param row: Dictionary representing a row from the GPKG table.
        :param graph: RDF graph (unused but required by interface).
        :return: URIRef for the county alias or UnknownCounty if no value.
        """
        if value:
            state_name = str(row.get("state_name", ""))
            return config.prefix_list["gnisf-alias"][
                f"{clean(state_name)}.{clean(value)}"
            ]
        return config.prefix_list["gnis"]["UnknownCounty"]

    def make_prim_lat_dec_field(self, geoms_file):
        """
        Create a field processor for primary latitude with geometry output.

        :param geoms_file: File handle for writing geometry TSV data.
        :return: Field processor function.
        """

        def prim_lat_dec_field(value: str, row: dict, graph: Graph) -> dict | None:
            """
            Process primary latitude and generate geometry.

            :param value: Primary latitude value.
            :param row: Dictionary representing a row from the GPKG table.
            :param graph: RDF graph to add geometry triples to.
            :return: Dictionary of predicate-object pairs or None if no geometry.
            """
            if not value or value == "0.0":
                return None

            lat = value
            lng_raw = row.get("prim_long_dec", "")
            # Skip the geometry entirely when the longitude is missing (None,
            # NaN, or empty) so no 'POINT(nan ...)' WKT is ever produced.
            if lng_raw is None or (isinstance(lng_raw, float) and lng_raw != lng_raw):
                return None
            lng = str(lng_raw)
            if not lng:
                return None

            feature_id = normalize_feature_id(row.get("feature_id", ""))

            geom_iri = f"{config.geo_base}/point/gnisf.{feature_id}"
            point_wkt = f"POINT({lng} {lat})"

            # Write to geometry TSV
            if geoms_file:
                geoms_file.write(f"{geom_iri}\tSRID=4326;{point_wkt}\n")

            # Add WKT literal to geometry node
            geom_uri = URIRef(geom_iri)
            geosparql = config.prefix_list["geosparql"]

            wkt_literal = Literal(
                f"<http://www.opengis.net/def/crs/OGC/1.3/CRS84>{point_wkt}",
                datatype=geosparql["wktLiteral"],
            )
            graph.add((geom_uri, geosparql["asWKT"], wkt_literal))

            return {
                "geosparql:hasGeometry": [f">{geom_iri}"],
            }

        return prim_lat_dec_field

    def elev_in_ft_field(self, value: str, row: dict, graph: Graph) -> dict | None:
        """
        Process elevation in feet and return nested blank node with QUDT properties.

        :param value: Elevation value in feet.
        :param row: Dictionary representing a row from the GPKG table.
        :param graph: RDF graph (unused but required by interface).
        :return: Dictionary with nested blank node properties or None if no elevation.
        """
        if not value or value == "" or value == "0":
            return None

        # Handle numeric values
        if isinstance(value, (int, float)):
            elev_value = str(int(value))
        else:
            elev_value = str(value).strip()
            if not elev_value:
                return None

        return {
            "gnis:elevation": {
                "qudt:numericValue": [f'^xsd:double"{elev_value}'],
                "qudt:unit": ["unit:FT"],
            },
        }

    def map_name_object(self, value: str, row: dict, graph: Graph) -> Literal:
        """
        Convert map name to language-tagged literal.

        :param value: Map name value.
        :param row: Dictionary representing a row from the GPKG table.
        :param graph: RDF graph (unused but required by interface).
        :return: RDF Literal with English language tag.
        """
        return Literal(value, lang="en")

    def date_object(self, value: str, row: dict, graph: Graph) -> Literal | str:
        """
        Convert date string to XSD date literal.

        :param value: Date string value.
        :param row: Dictionary representing a row from the GPKG table.
        :param graph: RDF graph (unused but required by interface).
        :return: RDF Literal with XSD date datatype or empty string if no value.
        """
        if not value:
            return ""
        try:
            # Handle ISO format from GPKG (e.g., '1998-10-06T06:13:42')
            if "T" in value:
                dt = datetime.fromisoformat(value)
            else:
                dt = datetime.strptime(value, "%m/%d/%Y")
            return Literal(dt.strftime("%Y-%m-%d"), datatype=XSD.date)
        except ValueError:
            return Literal(value)

    def _on_complete(self, geoms_file) -> None:
        """
        Handle completion: close geometry file and write feature aliases.

        :param geoms_file: File handle for geometry TSV data.
        """
        # Close geometry output
        if geoms_file:
            geoms_file.close()

        # Create aliases graph
        aliases_graph = Graph()
        for prefix, ns in config.prefix_list.items():
            aliases_graph.bind(prefix, ns)

        gnisf = config.prefix_list["gnisf"]
        gnisf_alias = config.prefix_list["gnisf-alias"]
        gnis = config.prefix_list["gnis"]

        # Process each alias
        for alias, features in feature_aliases.items():
            if alias:
                alias_uri = gnisf_alias[alias]

                if len(features) == 1:
                    # Unique - add owl:sameAs
                    aliases_graph.add((alias_uri, OWL.sameAs, gnisf[features[0]]))
                else:
                    # Ambiguous - add disambiguation links
                    for feature_id in features:
                        aliases_graph.add(
                            (alias_uri, gnis["disambiguatesTo"], gnisf[feature_id])
                        )

        # Write aliases file
        aliases_path = config.output_directory / "feature-aliases.ttl"
        aliases_graph.serialize(destination=str(aliases_path), format="turtle")
        print(f"Aliases written to {aliases_path}")


def main():
    """Run the features triplifier."""
    config.output_directory.mkdir(parents=True, exist_ok=True)
    FeaturesTriplifier()


if __name__ == "__main__":
    main()
