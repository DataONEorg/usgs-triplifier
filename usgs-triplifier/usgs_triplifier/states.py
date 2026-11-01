from typing import ClassVar


class States:
    """
    Two-letter codes and full names of the US states and territories,
    spelled as USGS writes them in the state_name column of its GNIS products.

    Legacy dumps and GeoNames give a feature's state as the code, while the
    current products give the full name. Feature-alias and gnis:state IRIs
    are built from the full name, so both directions of the lookup must use
    these exact spellings.
    """

    # Code -> name, spelled as in the STATE rows of
    # GovernmentUnits_National_Text
    NAMES: ClassVar[dict[str, str]] = {
        "AL": "Alabama",
        "AK": "Alaska",
        "AZ": "Arizona",
        "AR": "Arkansas",
        "CA": "California",
        "CO": "Colorado",
        "CT": "Connecticut",
        "DE": "Delaware",
        "DC": "District of Columbia",
        "FL": "Florida",
        "GA": "Georgia",
        "HI": "Hawaii",
        "ID": "Idaho",
        "IL": "Illinois",
        "IN": "Indiana",
        "IA": "Iowa",
        "KS": "Kansas",
        "KY": "Kentucky",
        "LA": "Louisiana",
        "ME": "Maine",
        "MD": "Maryland",
        "MA": "Massachusetts",
        "MI": "Michigan",
        "MN": "Minnesota",
        "MS": "Mississippi",
        "MO": "Missouri",
        "MT": "Montana",
        "NE": "Nebraska",
        "NV": "Nevada",
        "NH": "New Hampshire",
        "NJ": "New Jersey",
        "NM": "New Mexico",
        "NY": "New York",
        "NC": "North Carolina",
        "ND": "North Dakota",
        "OH": "Ohio",
        "OK": "Oklahoma",
        "OR": "Oregon",
        "PA": "Pennsylvania",
        "RI": "Rhode Island",
        "SC": "South Carolina",
        "SD": "South Dakota",
        "TN": "Tennessee",
        "TX": "Texas",
        "UT": "Utah",
        "VT": "Vermont",
        "VA": "Virginia",
        "WA": "Washington",
        "WV": "West Virginia",
        "WI": "Wisconsin",
        "WY": "Wyoming",
        "AS": "American Samoa",
        "GU": "Guam",
        "MP": "Commonwealth of the Northern Mariana Islands",
        "PR": "Puerto Rico",
        "UM": "U.S. Minor Outlying Islands",
        "VI": "United States Virgin Islands",
        "FM": "Federated States of Micronesia",
        "MH": "Marshall Islands",
        "PW": "Palau",
    }

    # Name -> code mapping
    CODES: ClassVar[dict[str, str]] = {name: code for code, name in NAMES.items()}

    # Code -> FIPS state number, as written in the state_numeric column
    NUMBERS: ClassVar[dict[str, str]] = {
        "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08",
        "CT": "09", "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15",
        "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
        "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
        "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
        "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
        "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
        "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
        "WV": "54", "WI": "55", "WY": "56", "AS": "60", "GU": "66", "MP": "69",
        "PR": "72", "UM": "74", "VI": "78", "FM": "64", "MH": "68", "PW": "70",
    }  # fmt: skip

    @classmethod
    def name_for(cls, code: str) -> str | None:
        """
        Looks up the full name of a state or territory.

        :param code: Two-letter state code.
        :return: The name as USGS spells it or None for an unknown code.
        """
        return cls.NAMES.get(code)

    @classmethod
    def code_for(cls, name: str) -> str | None:
        """
        Looks up the two-letter code of a state or territory.

        :param name: Full name as USGS spells it, e.g. "United States Virgin Islands".
        :return: The two-letter code or None for an unknown name.
        """
        return cls.CODES.get(name)

    @classmethod
    def number_for(cls, code: str) -> str | None:
        """
        Looks up the FIPS number of a state or territory.

        :param code: Two-letter state code.
        :return: The two-digit number, or None for an unknown code.
        """
        return cls.NUMBERS.get(code)
