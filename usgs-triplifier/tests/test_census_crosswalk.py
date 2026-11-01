import gzip
import io
import zipfile

import requests

from usgs_triplifier.lib import census_crosswalk
from usgs_triplifier.lib.census_crosswalk import CensusCrosswalk
from usgs_triplifier.output_files import OutputFiles

# 2025+ vintages are pipe-delimited with a GEOIDFQ column
COUNTIES = (
    "USPS|GEOID|GEOIDFQ|ANSICODE|NAME|ALAND\n"
    "AK|02068|0500000US02068|01419988|Denali Borough|32777.0\n"
)
# trailing whitespace in the header happens in real vintages
PLACES = (
    "USPS\tGEOID\tANSICODE\tNAME\tLSAD  \n"
    "IL\t1772000\t00428803\tSpringfield city\t25\n"
    "XX\t9999999\tnot-numeric\tBad Row\t25\n"
)


def _zip_bytes(txt_name, content):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(txt_name, content)
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


def test_ansi_codes_join_to_geoids(data_dirs, monkeypatch, config):
    _, output_dir = data_dirs
    responses = {
        "counties": FakeResponse(
            _zip_bytes("2025_Gaz_counties_national.txt", COUNTIES)
        ),
        "place": FakeResponse(_zip_bytes("2025_Gaz_place_national.txt", PLACES)),
    }
    monkeypatch.setattr(
        census_crosswalk.requests,
        "get",
        lambda url, **kw: responses["counties" if "counties" in url else "place"],
    )

    path = CensusCrosswalk(config).build()

    assert path == output_dir / OutputFiles.CENSUS_CROSSWALK
    with gzip.open(path, "rt", encoding="utf-8") as f:
        lines = f.read().splitlines()
    prop = f"<{config.lod_base}/gnis/ontology/censusGeoid>"
    # Leading zeros are stripped from the GNIS id and kept in the GEOID
    assert f'<{config.lod_base}/gnis/feature/1419988> {prop} "02068" .' in lines
    assert f'<{config.lod_base}/gnis/feature/428803> {prop} "1772000" .' in lines
    # the GEOID doubles as the Data Commons key
    sameas = "<http://www.w3.org/2002/07/owl#sameAs>"
    assert (
        f"<{config.lod_base}/gnis/feature/1419988> {sameas} "
        "<https://datacommons.org/browser/geoId/02068> ." in lines
    )
    assert len(lines) == 4  # the non-numeric ANSI row is skipped


def test_each_feature_gets_one_geoid(data_dirs, monkeypatch, config):
    counties = "USPS|GEOID|ANSICODE|NAME\nVA|51810|01498559|Virginia Beach city\n"
    places = (
        "USPS|GEOID|ANSICODE|NAME\n"
        "VA|5182000|01498559|Virginia Beach city\n"
        "VA|5118428|02832523|Colonial Forge CDP\n"
        "VA|5125736|02832523|Embrey Mill CDP\n"
    )
    responses = {
        "counties": FakeResponse(
            _zip_bytes("2025_Gaz_counties_national.txt", counties)
        ),
        "place": FakeResponse(_zip_bytes("2025_Gaz_place_national.txt", places)),
    }
    monkeypatch.setattr(
        census_crosswalk.requests,
        "get",
        lambda url, **kw: responses["counties" if "counties" in url else "place"],
    )

    with gzip.open(CensusCrosswalk(config).build(), "rt", encoding="utf-8") as f:
        lines = f.read().splitlines()

    prop = f"<{config.lod_base}/gnis/ontology/censusGeoid>"
    # An independent city in both files gets its county GEOID
    assert [line for line in lines if "/1498559>" in line and prop in line] == [
        f'<{config.lod_base}/gnis/feature/1498559> {prop} "51810" .'
    ]
    # A code shared by two places in one file is not linked
    assert not [line for line in lines if "/2832523>" in line]
    assert len(lines) == 2


def test_unreachable_gazetteer_is_not_fatal(data_dirs, monkeypatch, config):
    def boom(*a, **kw):
        raise requests.ConnectionError("census is down")

    monkeypatch.setattr(census_crosswalk.requests, "get", boom)
    assert CensusCrosswalk(config).build() is None
