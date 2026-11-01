import re
from typing import Any


class FeatureIds:
    """
    Builds the local names of gnisf: and gnisf-alias: IRIs.
    """

    @staticmethod
    def normalize(raw: Any) -> str:
        """
        Converts a GNIS feature id to the form used in gnisf.

        :param raw: Feature id as read from a source file. Numbers are
            converted to integers; strings lose their leading zeros.
        :return: The id as a string; "0" for an empty or all-zero id.
        :raises ValueError: If the id is a string with a non-digit character.
        """
        if isinstance(raw, (int, float)):
            return str(int(raw))
        text = str(raw).strip()
        if text and not text.isdigit():
            raise ValueError(f"Feature id {raw!r} is not a number")
        return text.lstrip("0") or "0"

    @staticmethod
    def alias_part(text: str) -> str:
        """
        Converts a name to the form used in gnisf-alias IRIs, e.g.
        "San Juan Co." to "San_Juan_Co_".

        :param text: A state, county, country or feature name.
        :return: The name with every non-word character replaced by an underscore.
        """
        return re.sub(r"[^\w]", "_", text)
