import logging
import re
import unicodedata
import zipfile
from pathlib import Path
from typing import ClassVar

import numpy as np
from numpy.typing import ArrayLike
import pandas as pd
import requests

from ..config import Config
from ..output_files import OutputFiles
from ..states import States
from ..usgs_products import UsgsProduct, UsgsProducts
from .crosswalk import Crosswalk
from .gnis.identifiers import FeatureIds


class GeoNamesMatcher:
    """
    Pairs GNIS features with GeoNames records that are the same place.

    A GNIS feature and a GeoNames record are candidates when they share a
    normalized name (any of their names) and a state, their feature classes
    are compatible, and they are no farther apart than the class's distance
    limit. Each feature is paired with at most one record and each record
    with at most one feature. A feature whose best candidate fails the
    ambiguity checks in _resolve is left unpaired.
    """

    # Word expansions applied when normalizing names, because the two
    # gazetteers abbreviate differently ("St. Marys River", "Saint Marys River")
    NAME_ABBREVIATIONS: ClassVar[dict[str, str]] = {
        "st": "saint",
        "ste": "sainte",
        "mt": "mount",
        "mtn": "mountain",
        "ft": "fort",
    }

    # GeoNames feature classes (single letters) each GNIS feature class (spaces
    # removed) may pair with; a value of several letters allows any of them.
    # GNIS classes not listed here pair with any GeoNames class.
    CLASS_COMPATIBILITY: ClassVar[dict[str, str]] = {
        "Arroyo": "H",
        "Bay": "H",
        "Bend": "H",
        "Canal": "H",
        "Channel": "H",
        "Falls": "H",
        "Glacier": "H",
        "Gut": "H",
        "Harbor": "H",
        "Lake": "H",
        "Rapids": "H",
        "Reservoir": "H",
        "Sea": "H",
        "Spring": "H",
        "Stream": "H",
        "Swamp": "H",
        "Well": "H",
        "Arch": "T",
        "Bar": "T",
        "Basin": "T",
        "Beach": "T",
        "Bench": "T",
        "Cape": "T",
        "Cliff": "T",
        "Crater": "T",
        "Flat": "T",
        "Gap": "T",
        "Island": "T",
        "Isthmus": "T",
        "Lava": "T",
        "Levee": "T",
        "Pillar": "T",
        "Plain": "T",
        "Range": "T",
        "Ridge": "T",
        "Rock": "T",
        "Slope": "T",
        "Summit": "T",
        "Valley": "T",
        "PopulatedPlace": "P",
        "Census": "AL",
        "Civil": "A",
        "Military": "LS",
        "Area": "L",
        "Forest": "VL",
        "Oilfield": "L",
        "Park": "L",
        "Reserve": "L",
        "Woods": "V",
        "Airport": "S",
        "Bridge": "S",
        "Building": "S",
        "Cemetery": "S",
        "Church": "S",
        "Crossing": "RS",
        "Dam": "SH",
        "Hospital": "S",
        "Locale": "LS",
        "Mine": "S",
        "PostOffice": "S",
        "School": "S",
        "Tower": "S",
        "Trail": "R",
        "Tunnel": "RS",
    }

    # GNIS classes paired within geonames_point_max_distance_m instead of
    # geonames_max_distance_m, because the two gazetteers place them at
    # nearly the same coordinates
    POINT_CLASSES: ClassVar[frozenset[str]] = frozenset(
        {
            "PopulatedPlace",
            "Spring",
            "Well",
            "Airport",
            "Bridge",
            "Building",
            "Cemetery",
            "Church",
            "Crossing",
            "Dam",
            "Hospital",
            "Mine",
            "PostOffice",
            "School",
            "Tower",
        }
    )

    # Mean Earth radius used for distances
    EARTH_RADIUS_M: ClassVar[int] = 6_371_000

    def __init__(self, config: Config) -> None:
        """
        Creates the matcher.

        :param config: Settings holding the distance limits and the
            ambiguity ratio and gap.
        """
        self.config = config

    def match(self, gnis: pd.DataFrame, geonames: pd.DataFrame) -> pd.DataFrame:
        """
        Pairs features with records.

        :param gnis: One row per (feature, normalized name) with feature_id,
            key (the normalized name), state, class_key, lat and lon.
        :param geonames: One row per (record, normalized name) with
            geonameid, key, state, gn_class, lat and lon.
        :return: The accepted pairs: feature_id, geonameid, distance (metres)
            and shared (the number of normalized names the two have in common).
        """
        pairs = gnis.merge(
            geonames, on=["key", "state"], suffixes=("_gnis", "_geonames")
        )
        pairs = pairs[self._compatible(pairs["class_key"], pairs["gn_class"])]
        pairs["distance"] = self._haversine_m(
            pairs["lat_gnis"],
            pairs["lon_gnis"],
            pairs["lat_geonames"],
            pairs["lon_geonames"],
        )
        pairs = pairs[pairs["distance"] <= self._max_distance(pairs["class_key"])]
        # Reduce to one row per (feature, record) with the closest distance
        # between them and the number of normalized names they share
        pairs = pairs.groupby(["feature_id", "geonameid"], as_index=False).agg(
            distance=("distance", "min"), shared=("key", "size")
        )
        return self._resolve(pairs)

    def normalize_names(self, names: pd.Series) -> pd.Series:
        """
        Converts names to the form used to pair them, with accents,
        apostrophes and periods removed, letters lowercased, words separated
        by single spaces, and NAME_ABBREVIATIONS expanded.

        :param names: Names.
        :return: The normalized names; missing names stay missing.
        """
        unique = names.dropna().unique()
        mapping = {name: self._normalize_name(name) for name in unique}
        return names.map(mapping)

    def explode_names(self, geonames: pd.DataFrame) -> pd.DataFrame:
        """
        Expands GeoNames records to one row per normalized name, from the
        primary name and every alternate name, so a pair is found whichever
        name each gazetteer uses.

        :param geonames: Records with name and alternatenames (comma-separated) columns.
        :return: One row per (geonameid, key), without the alternatenames column.
        """
        primary = geonames.drop(columns=["alternatenames"]).assign(
            key=self.normalize_names(geonames["name"])
        )
        alternates = geonames.dropna(subset=["alternatenames"]).copy()
        alternates["key"] = alternates.pop("alternatenames").str.split(",")
        alternates = alternates.explode("key")
        alternates = alternates[alternates["key"].str.len() > 0]
        alternates["key"] = self.normalize_names(alternates["key"])
        exploded = pd.concat([primary, alternates.drop(columns=["name"])])
        return exploded.drop_duplicates(["geonameid", "key"])

    def _normalize_name(self, name: str) -> str:
        """
        Normalizes one name (see normalize_names).

        :param name: Name.
        :return: The normalized name.
        """
        decomposed = unicodedata.normalize("NFKD", str(name))
        flat = "".join(c for c in decomposed if not unicodedata.combining(c))
        flat = flat.lower().replace("'", "").replace(".", "")
        words = [w for w in re.split(r"[\s\-]+", flat) if w]
        return " ".join(self.NAME_ABBREVIATIONS.get(w, w) for w in words)

    def _compatible(self, class_key: pd.Series, gn_class: pd.Series) -> pd.Series:
        """
        Checks each candidate's classes against CLASS_COMPATIBILITY.

        :param class_key: GNIS feature classes, spaces removed.
        :param gn_class: GeoNames feature class letters.
        :return: True where the GeoNames class is allowed for the GNIS class,
            or where the GNIS class is not listed or the GeoNames class is missing.
        """
        allowed = class_key.map(self.CLASS_COMPATIBILITY)
        unrestricted = allowed.isna() | gn_class.isna()
        hits = pd.Series(
            [
                g in a if isinstance(a, str) and isinstance(g, str) else False
                for a, g in zip(allowed, gn_class)
            ],
            index=class_key.index,
        )
        return unrestricted | hits

    def _max_distance(self, class_key: pd.Series) -> pd.Series:
        """
        Looks up each candidate's distance limit.

        :param class_key: GNIS feature classes, spaces removed.
        :return: geonames_point_max_distance_m for POINT_CLASSES, otherwise
            geonames_max_distance_m, in metres.
        """
        return pd.Series(
            np.where(
                class_key.isin(self.POINT_CLASSES),
                self.config.geonames_point_max_distance_m,
                self.config.geonames_max_distance_m,
            ),
            index=class_key.index,
        )

    def _resolve(self, pairs: pd.DataFrame) -> pd.DataFrame:
        """
        Keeps at most one candidate per feature and one feature per record.

        Candidates are ranked by shared names (most first), then distance.
        A feature's top candidate is kept when there is no second candidate,
        when it shares more names than the second, or when the second is at
        least geonames_ambiguity_ratio times as far away or at least
        geonames_ambiguity_min_gap_m metres farther. The feature is otherwise
        left unpaired. A kept pair is then dropped unless the feature is also
        the top-ranked feature for that record, because two features paired
        with one record would be linked to each other through owl:sameAs.

        :param pairs: Candidates with feature_id, geonameid, shared and distance.
        :return: The accepted pairs.
        """
        pairs = pairs.sort_values(
            ["shared", "distance"], ascending=[False, True], kind="stable"
        )

        best = pairs.drop_duplicates("feature_id", keep="first")
        runners = pairs[~pairs.index.isin(best.index)].drop_duplicates(
            "feature_id", keep="first"
        )
        second_distance = best["feature_id"].map(
            runners.set_index("feature_id")["distance"]
        )
        second_shared = best["feature_id"].map(
            runners.set_index("feature_id")["shared"]
        )
        unambiguous = (
            second_distance.isna()
            | (best["shared"] > second_shared)
            | (
                second_distance
                >= self.config.geonames_ambiguity_ratio * best["distance"]
            )
            | (
                second_distance - best["distance"]
                >= self.config.geonames_ambiguity_min_gap_m
            )
        )
        best = best[unambiguous]

        top_per_record = pairs.drop_duplicates("geonameid", keep="first")
        return best[best.index.isin(top_per_record.index)]

    @classmethod
    def _haversine_m(
        cls, lat1: ArrayLike, lon1: ArrayLike, lat2: ArrayLike, lon2: ArrayLike
    ) -> np.ndarray:
        """
        Computes great-circle distances on a sphere of EARTH_RADIUS_M.

        :param lat1: Latitudes of the first points, in degrees.
        :param lon1: Longitudes of the first points, in degrees.
        :param lat2: Latitudes of the second points, in degrees.
        :param lon2: Longitudes of the second points, in degrees.
        :return: The distances in metres.
        """
        lat1, lon1, lat2, lon2 = (
            np.radians(np.asarray(v, dtype="float64")) for v in (lat1, lon1, lat2, lon2)
        )
        a = (
            np.sin((lat2 - lat1) / 2) ** 2
            + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
        )
        return 2 * cls.EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


class GeoNamesCrosswalk(Crosswalk):
    """
    Links GNIS features to the GeoNames records GeoNamesMatcher pairs them
    with, as owl:sameAs.

    Reads the features from the GNIS features file and their variant names
    from AllNames, and the records from the GeoNames US export, which is
    downloaded into the input directory when missing. When
    wikidata-geonames.csv exists, the links are also compared with the
    GeoNames ids Wikidata records for the same features.
    """

    output_name: ClassVar[str] = OutputFiles.GEONAMES_CROSSWALK

    # GeoNames US export, in the input directory
    US_EXPORT_NAME: ClassVar[str] = "US.zip"

    # Columns read from the GNIS features file. Legacy dumps use uppercase
    # names and give the state as a code (STATE_ALPHA).
    GNIS_COLUMNS: ClassVar[dict[str, str]] = {
        "feature_id": "feature_id",
        "feature_name": "name",
        "feature_class": "feature_class",
        "state_name": "state_name",
        "prim_lat_dec": "lat",
        "prim_long_dec": "lon",
    }
    LEGACY_GNIS_COLUMNS: ClassVar[dict[str, str]] = {
        "FEATURE_ID": "feature_id",
        "FEATURE_NAME": "name",
        "FEATURE_CLASS": "feature_class",
        "STATE_ALPHA": "state",
        "PRIM_LAT_DEC": "lat",
        "PRIM_LONG_DEC": "lon",
    }

    _log: ClassVar[logging.Logger] = logging.getLogger(__name__)

    def __init__(self, config: Config) -> None:
        """
        Creates the crosswalk.

        :param config: Settings holding the input and output directories, the
            GeoNames URL, and the matching limits.
        """
        super().__init__(config)
        self.matcher = GeoNamesMatcher(config)

    def build(self) -> Path | None:
        """
        Pairs the features with GeoNames records and writes the links.

        :return: Path of the written file, or None when the GeoNames export
            could not be downloaded.
        """
        export_path = self._fetch_export()
        if export_path is None:
            return None

        gnis = self._load_gnis()
        gnis["feature_id"] = gnis["feature_id"].map(FeatureIds.normalize)
        gnis["class_key"] = gnis["feature_class"].fillna("").str.replace(" ", "")
        gnis["key"] = self.matcher.normalize_names(gnis["name"])
        gnis = self._with_variant_names(gnis)
        geonames = self.matcher.explode_names(self._load_geonames(export_path))

        matches = self.matcher.match(gnis, geonames)
        self.write_lines(
            f"{self.feature_iri(row.feature_id)} {self.OWL_SAMEAS} "
            f"<http://sws.geonames.org/{row.geonameid}/> ."
            for row in matches.itertuples()
        )
        self._compare_with_wikidata(matches)
        return self.output_path

    def _fetch_export(self) -> Path | None:
        """
        Finds the GeoNames US export in the input directory, downloading it
        from geonames_url when missing.

        :return: Path of the export, or None when the download failed.
        """
        export_path = self.config.input_directory / self.US_EXPORT_NAME
        if export_path.exists():
            return export_path
        try:
            response = requests.get(self.config.geonames_url, stream=True, timeout=300)
            response.raise_for_status()
            self.config.input_directory.mkdir(parents=True, exist_ok=True)
            with open(export_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        except requests.RequestException as error:
            self._log.warning(
                f"GeoNames export unavailable; writing no GeoNames links: {error}"
            )
            return None
        return export_path

    def _load_gnis(self) -> pd.DataFrame:
        """
        Reads the GNIS features to pair, from the current features file or,
        for a legacy dump, NationalFile. The state names of the current file
        are converted to codes, which is how GeoNames and legacy dumps give them.

        :return: Rows with feature_id, name, feature_class, state, lat and
            lon, limited to features with a name, a state and a non-zero latitude.
        """
        if self.config.legacy_dump:
            gnis = self._read_gnis_text(UsgsProducts.FEATURES, self.LEGACY_GNIS_COLUMNS)
        else:
            gnis = self._read_gnis_text(UsgsProducts.FEATURES, self.GNIS_COLUMNS)
            gnis["state"] = gnis["state_name"].map(States.CODES)
        gnis = gnis.dropna(subset=["name", "state", "lat", "lon"])
        return gnis[gnis["lat"].astype(float) != 0.0]

    def _read_gnis_text(
        self, product: UsgsProduct, columns: dict[str, str]
    ) -> pd.DataFrame:
        """
        Reads columns from every .txt file inside a product's zips in the
        input directory.

        :param product: The product to read.
        :param columns: Source column name -> name in the returned frame.
        :return: The columns as strings, renamed.
        :raises ValueError: If the product has no zip, or a column is missing.
        """
        frames = []
        zip_paths = product.zip_paths(
            self.config.input_directory, self.config.legacy_dump
        )
        for zip_path in zip_paths:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for txt_name in (n for n in zf.namelist() if n.endswith(".txt")):
                    with zf.open(txt_name) as f:
                        frames.append(
                            pd.read_csv(
                                f,
                                sep="|",
                                dtype=str,
                                encoding="utf-8-sig",
                                quoting=UsgsProducts.quoting_for(
                                    self.config.legacy_dump
                                ),
                                usecols=list(columns),
                            )
                        )
        return pd.concat(frames, ignore_index=True).rename(columns=columns)

    def _with_variant_names(self, gnis: pd.DataFrame) -> pd.DataFrame:
        """
        Adds a row for every variant name of each feature, read from the
        AllNames zip in the input directory, so features are also paired by
        their variant names. Without an AllNames zip, only the features' own
        names are used.

        :param gnis: One row per feature, with feature_id and key.
        :return: One row per (feature_id, key).
        """
        zip_paths = UsgsProducts.NAMES.zip_paths(
            self.config.input_directory, self.config.legacy_dump
        )
        frames = []
        for zip_path in zip_paths:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for txt_name in (n for n in zf.namelist() if n.endswith(".txt")):
                    with zf.open(txt_name) as f:
                        frame = pd.read_csv(
                            f,
                            sep="|",
                            dtype=str,
                            encoding="utf-8-sig",
                            quoting=UsgsProducts.quoting_for(self.config.legacy_dump),
                            usecols=lambda c: (
                                c.strip().lower() in ("feature_id", "feature_name")
                            ),
                        )
                    frame.columns = [c.strip().lower() for c in frame.columns]
                    frames.append(frame)
        if not frames:
            self._log.info(
                "No AllNames zip in the input directory; pairing on feature names only"
            )
            return gnis
        variants = pd.concat(frames, ignore_index=True).dropna()
        variants["feature_id"] = variants["feature_id"].map(FeatureIds.normalize)
        variants["key"] = self.matcher.normalize_names(variants["feature_name"])
        extra = variants[["feature_id", "key"]].merge(
            gnis.drop(columns=["key"]), on="feature_id"
        )
        combined = pd.concat([gnis, extra], ignore_index=True)
        return combined.drop_duplicates(["feature_id", "key"])

    def _load_geonames(self, export_path: Path) -> pd.DataFrame:
        """
        Reads the records of the GeoNames US export.

        :param export_path: Path of US.zip.
        :return: geonameid, name, alternatenames, lat, lon, gn_class and
            state (the admin1 code), limited to records with a name, a state
            and coordinates.
        """
        with zipfile.ZipFile(export_path, "r") as zf:
            with zf.open("US.txt") as f:
                geonames = pd.read_csv(
                    f,
                    sep="\t",
                    header=None,
                    usecols=[0, 1, 3, 4, 5, 6, 10],
                    names=[
                        "geonameid",
                        "name",
                        "alternatenames",
                        "lat",
                        "lon",
                        "gn_class",
                        "state",
                    ],
                    dtype={
                        "geonameid": "int64",
                        "name": "string",
                        "alternatenames": "string",
                        "lat": "float64",
                        "lon": "float64",
                        "gn_class": "string",
                        "state": "string",
                    },
                    quoting=3,
                    na_filter=True,
                )
        return geonames.dropna(subset=["name", "state", "lat", "lon"])

    def _wikidata_pairs(self) -> dict[str, set[str]]:
        """
        Reads the GeoNames ids Wikidata records for GNIS features from
        wikidata-geonames.csv in the output directory.

        :return: GeoNames ids per feature id; empty when the file does not exist.
        """
        path = self.config.output_directory / OutputFiles.WIKIDATA_GEONAMES_PAIRS
        if not path.exists():
            return {}
        pairs: dict[str, set[str]] = {}
        with open(path, encoding="utf-8") as f:
            for line in f:
                feature_id, _, geonameid = line.strip().partition(",")
                if feature_id and geonameid:
                    pairs.setdefault(feature_id, set()).add(geonameid)
        return pairs

    def _compare_with_wikidata(self, matches: pd.DataFrame) -> None:
        """
        Logs how often the links agree with the GeoNames ids Wikidata records
        for the same features, and writes the disagreeing pairs to
        geonames-qa-disagreements.csv. Does nothing when there is no Wikidata
        pairs file or no linked feature appears in it.

        :param matches: Accepted pairs from GeoNamesMatcher.match.
        """
        wikidata = self._wikidata_pairs()
        if not wikidata:
            return
        overlap = matches[matches["feature_id"].isin(wikidata.keys())]
        if not len(overlap):
            return
        disagreements = [
            row
            for row in overlap.itertuples()
            if str(row.geonameid) not in wikidata[row.feature_id]
        ]
        agree = len(overlap) - len(disagreements)
        self._log.info(
            f"GeoNames links agree with Wikidata on {agree} of {len(overlap)} "
            f"features ({100 * agree / len(overlap):.1f}%)"
        )
        report_path = self.config.output_directory / OutputFiles.GEONAMES_QA_REPORT
        with open(report_path, "w", encoding="utf-8") as out:
            out.write("feature_id,aligned_geonameid,curated_geonameids\n")
            for row in disagreements:
                out.write(
                    f"{row.feature_id},{row.geonameid},"
                    f"{';'.join(sorted(wikidata[row.feature_id]))}\n"
                )
        self._log.info(
            f"Wrote {len(disagreements)} disagreements to {report_path.name}"
        )
