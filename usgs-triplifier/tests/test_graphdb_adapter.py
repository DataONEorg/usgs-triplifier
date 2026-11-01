import pytest
import requests

import graphdb_adapter
from config import EtlConfig
from graphdb_adapter import GraphDBAdapter, GraphDBImportError

IMPORT_URL = "http://graphdb:7200/rest/repositories/gnis-ld/import/server"


class FakeResponse:
    """
    Stands in for a requests.Response.
    """

    def __init__(self, status_code: int = 200, payload=None, text: str = "") -> None:
        """
        Creates the response.

        :param status_code: HTTP status code.
        :param payload: Value json() returns.
        :param text: Response body as text.
        """
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        """
        Returns the payload.

        :return: The payload given at construction.
        """
        return self._payload

    def raise_for_status(self) -> None:
        """
        Raises for a 4xx or 5xx status code.

        :raises requests.HTTPError: If the status code is 400 or more.
        """
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}", response=self)


class FakeRequests:
    """
    Records the calls made through the requests module and answers GET
    requests of the import status from a queue.
    """

    # The adapter catches these through the module it imported
    RequestException = requests.RequestException
    HTTPError = requests.HTTPError

    def __init__(self, status_pages: list) -> None:
        """
        Creates the fake.

        :param status_pages: Answers to successive GETs, each a status list,
            an exception to raise, or a FakeResponse. The last one is repeated.
        """
        self.status_pages = list(status_pages)
        self.calls: list[tuple[str, str, dict]] = []

    def get(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append(("get", url, kwargs))
        page = (
            self.status_pages.pop(0)
            if len(self.status_pages) > 1
            else self.status_pages[0]
        )
        if isinstance(page, Exception):
            raise page
        if isinstance(page, FakeResponse):
            return page
        return FakeResponse(payload=page)

    def post(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append(("post", url, kwargs))
        return FakeResponse(status_code=202)


@pytest.fixture()
def sleeps(monkeypatch) -> list[float]:
    """
    Replaces time.sleep in the adapter module with a recorder.

    :param monkeypatch: pytest monkeypatch.
    :return: The list the requested sleep durations are appended to.
    """
    calls: list[float] = []
    monkeypatch.setattr(graphdb_adapter.time, "sleep", calls.append)
    return calls


@pytest.fixture()
def adapter(config, monkeypatch, sleeps) -> GraphDBAdapter:
    """
    Builds an adapter whose import directory holds two files, polling every
    30 recorded seconds on a clock stopped at 1,000,000.

    :param config: The test's settings.
    :param monkeypatch: pytest monkeypatch.
    :param sleeps: The sleep recorder.
    :return: The adapter.
    """
    import_dir = config.output_directory / "import"
    import_dir.mkdir()
    (import_dir / "features.nt.gz").write_bytes(b"")
    (import_dir / "dataset-metadata.ttl").write_text("")
    etl_config = EtlConfig(
        input_directory=config.input_directory,
        output_directory=config.output_directory,
        archive_output_directory=config.archive_output_directory,
        graphdb_url="http://graphdb:7200",
        graphdb_import_directory=str(import_dir),
        graphdb_admin_password="secret",
        graphdb_import_timeout=100,
        graphdb_import_poll=30,
    )
    monkeypatch.setattr(graphdb_adapter.time, "time", lambda: 1_000_000)
    return GraphDBAdapter(etl_config)


def _status(name: str, state: str, imported_ms: int, message: str = "") -> dict:
    """
    Builds a status object with the fields GraphDB's server import API returns.
    """
    return {
        "name": name,
        "status": state,
        "message": message,
        "imported": imported_ms,
        "lastModified": 1_000_000_000,
        "size": 10,
    }


# Statuses GraphDB kept from the previous run of the same files
PREVIOUS = [
    _status("features.nt.gz", "DONE", 900_000_000, "Imported successfully in 10s."),
    _status(
        "dataset-metadata.ttl", "DONE", 900_000_001, "Imported successfully in 1s."
    ),
]


def test_import_files_waits_until_every_file_is_done(adapter, monkeypatch, sleeps):
    fake = FakeRequests(
        [
            PREVIOUS,
            # First poll: the previous statuses are unchanged
            PREVIOUS,
            [
                _status("features.nt.gz", "IMPORTING", 900_000_000),
                _status("dataset-metadata.ttl", "PENDING", 900_000_001),
            ],
            [
                _status("features.nt.gz", "DONE", 1_000_000_500, "Imported in 9s."),
                _status("dataset-metadata.ttl", "DONE", 1_000_000_600),
            ],
        ]
    )
    monkeypatch.setattr(graphdb_adapter, "requests", fake)

    adapter.import_files()

    assert [call[0] for call in fake.calls] == ["get", "post", "get", "get", "get"]
    # One poll interval between each pair of polls
    assert sleeps == [30, 30]
    assert fake.calls[1][1] == IMPORT_URL
    assert sorted(fake.calls[1][2]["json"]["fileNames"]) == [
        "dataset-metadata.ttl",
        "features.nt.gz",
    ]


def test_wait_for_import_accepts_a_file_graphdb_had_no_status_for(adapter, monkeypatch):
    fake = FakeRequests([[_status("features.nt.gz", "DONE", 1_000_000_500)]])
    monkeypatch.setattr(graphdb_adapter, "requests", fake)

    adapter.wait_for_import(["features.nt.gz"], before={})

    assert [call[0] for call in fake.calls] == ["get"]


def test_wait_for_import_reports_every_failed_file_after_the_rest_finish(
    adapter, monkeypatch
):
    before = {s["name"]: s for s in PREVIOUS}
    fake = FakeRequests(
        [
            [
                _status("features.nt.gz", "IMPORTING", 900_000_000),
                _status(
                    "dataset-metadata.ttl", "ERROR", 1_000_000_100, "RDF Parse Error"
                ),
            ],
            [
                _status("features.nt.gz", "DONE", 1_000_000_900),
                _status(
                    "dataset-metadata.ttl", "ERROR", 1_000_000_100, "RDF Parse Error"
                ),
            ],
        ]
    )
    monkeypatch.setattr(graphdb_adapter, "requests", fake)

    with pytest.raises(GraphDBImportError) as error:
        adapter.wait_for_import(["features.nt.gz", "dataset-metadata.ttl"], before)

    assert "dataset-metadata.ttl (ERROR: RDF Parse Error)" in str(error.value)
    assert "features.nt.gz" not in str(error.value)
    # The loop kept polling until features.nt.gz was done too
    assert [call[0] for call in fake.calls] == ["get", "get"]


def test_wait_for_import_treats_an_interrupted_import_as_failed(adapter, monkeypatch):
    fake = FakeRequests([[_status("features.nt.gz", "INTERRUPTING", 1_000_000_100)]])
    monkeypatch.setattr(graphdb_adapter, "requests", fake)

    with pytest.raises(GraphDBImportError, match="features.nt.gz \\(INTERRUPTING"):
        adapter.wait_for_import(["features.nt.gz"], before={})


def test_wait_for_import_retries_after_a_failed_status_request(adapter, monkeypatch):
    fake = FakeRequests(
        [
            requests.ConnectionError("reset"),
            FakeResponse(status_code=503),
            [_status("features.nt.gz", "DONE", 1_000_000_100)],
        ]
    )
    monkeypatch.setattr(graphdb_adapter, "requests", fake)

    adapter.wait_for_import(["features.nt.gz"], before={})

    assert [call[0] for call in fake.calls] == ["get", "get", "get"]


def test_wait_for_import_raises_after_the_timeout(adapter, monkeypatch):
    fake = FakeRequests([[_status("features.nt.gz", "IMPORTING", 1_000_000_100)]])
    monkeypatch.setattr(graphdb_adapter, "requests", fake)
    clock = iter([1_000_000, 1_000_050, 1_000_200])
    monkeypatch.setattr(graphdb_adapter.time, "time", lambda: next(clock))

    with pytest.raises(
        GraphDBImportError, match="still waiting for features.nt.gz \\(IMPORTING\\)"
    ):
        adapter.wait_for_import(["features.nt.gz"], before={})


def test_timeout_names_a_file_graphdb_never_lists(adapter, monkeypatch):
    fake = FakeRequests([[]])
    monkeypatch.setattr(graphdb_adapter, "requests", fake)
    clock = iter([1_000_000, 1_000_200])
    monkeypatch.setattr(graphdb_adapter.time, "time", lambda: next(clock))

    with pytest.raises(GraphDBImportError, match="features.nt.gz \\(not listed"):
        adapter.wait_for_import(["features.nt.gz"], before={})


def test_timeout_reports_a_status_that_never_changed(adapter, monkeypatch):
    # GraphDB keeps answering with the previous run's statuses
    before = {s["name"]: s for s in PREVIOUS}
    fake = FakeRequests([PREVIOUS])
    monkeypatch.setattr(graphdb_adapter, "requests", fake)
    clock = iter([1_000_000, 1_000_200])
    monkeypatch.setattr(graphdb_adapter.time, "time", lambda: next(clock))

    with pytest.raises(GraphDBImportError, match="unchanged since before the import"):
        adapter.wait_for_import(["features.nt.gz"], before)


def test_wait_for_import_retries_408_and_429(adapter, monkeypatch):
    fake = FakeRequests(
        [
            FakeResponse(status_code=429),
            FakeResponse(status_code=408),
            [_status("features.nt.gz", "DONE", 1_000_000_100)],
        ]
    )
    monkeypatch.setattr(graphdb_adapter, "requests", fake)

    adapter.wait_for_import(["features.nt.gz"], before={})

    assert [call[0] for call in fake.calls] == ["get", "get", "get"]


def test_wait_for_import_times_out_while_status_requests_keep_failing(
    adapter, monkeypatch
):
    fake = FakeRequests([requests.ConnectionError("down")])
    monkeypatch.setattr(graphdb_adapter, "requests", fake)
    clock = iter([1_000_000, 1_000_050, 1_000_200])
    monkeypatch.setattr(graphdb_adapter.time, "time", lambda: next(clock))

    with pytest.raises(GraphDBImportError, match="features.nt.gz \\(not polled\\)"):
        adapter.wait_for_import(["features.nt.gz"], before={})

    assert len(fake.calls) == 2


def test_wait_for_import_accepts_a_status_without_an_imported_field(
    adapter, monkeypatch
):
    fake = FakeRequests([[{"name": "features.nt.gz", "status": "DONE"}]])
    monkeypatch.setattr(graphdb_adapter, "requests", fake)

    adapter.wait_for_import(["features.nt.gz"], before={})


def test_wait_for_import_detects_a_change_in_the_status_alone(adapter, monkeypatch):
    # Same imported time and message as the snapshot, only the status differs
    before = {"features.nt.gz": _status("features.nt.gz", "DONE", 900_000_000, "x")}
    fake = FakeRequests([[_status("features.nt.gz", "ERROR", 900_000_000, "x")]])
    monkeypatch.setattr(graphdb_adapter, "requests", fake)

    with pytest.raises(GraphDBImportError, match="features.nt.gz \\(ERROR: x\\)"):
        adapter.wait_for_import(["features.nt.gz"], before)

    assert len(fake.calls) == 1


def test_wait_for_import_does_not_retry_a_client_error(adapter, monkeypatch):
    fake = FakeRequests([FakeResponse(status_code=401)])
    monkeypatch.setattr(graphdb_adapter, "requests", fake)

    with pytest.raises(requests.HTTPError, match="401"):
        adapter.wait_for_import(["features.nt.gz"], before={})

    assert [call[0] for call in fake.calls] == ["get"]


def test_import_files_refuses_while_an_earlier_import_is_running(adapter, monkeypatch):
    fake = FakeRequests([[_status("features.nt.gz", "IMPORTING", 900_000_000)]])
    monkeypatch.setattr(graphdb_adapter, "requests", fake)

    with pytest.raises(
        GraphDBImportError, match="still importing \\['features.nt.gz'\\]"
    ):
        adapter.import_files()

    # Nothing was submitted
    assert [call[0] for call in fake.calls] == ["get"]


def test_import_files_without_files_makes_no_request(adapter, monkeypatch):
    for path in adapter.graphdb_import_path.iterdir():
        path.unlink()
    fake = FakeRequests([[]])
    monkeypatch.setattr(graphdb_adapter, "requests", fake)

    adapter.import_files()

    assert fake.calls == []


def test_repository_config_defaults_to_the_etl_directory(adapter):
    path = adapter.config.repository_config_path
    assert path.name == "gnis-ld-config.ttl"
    assert path.is_file()
