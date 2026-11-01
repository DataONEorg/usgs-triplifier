from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

import pipeline
from config import EtlConfig
from graphdb_adapter import GraphDBAdapter, GraphDBImportError
from pipeline import Pipeline, PipelineError, ReleasePublisher


class FakeAdapter:
    """
    Records the GraphDBAdapter methods the pipeline calls, in order, and
    fails one of them on request.
    """

    failures: dict[str, Exception] = {}
    calls: list[str] = []
    # What copy_triples returns
    copied: list[str] = ["features.nt.gz"]

    def __init__(self, config: EtlConfig) -> None:
        """
        Creates the fake and clears the recorded calls.

        :param config: Settings (unused).
        """
        FakeAdapter.calls = []

    def __getattr__(self, name: str):
        def step() -> list[str] | None:
            FakeAdapter.calls.append(name)
            if name in FakeAdapter.failures:
                raise FakeAdapter.failures[name]
            return FakeAdapter.copied if name == "copy_triples" else None

        return step


@pytest.fixture()
def etl_config(config) -> EtlConfig:
    """
    Builds ETL settings on the test's directories.

    :param config: The test's settings.
    :return: The ETL settings.
    """
    return EtlConfig(
        input_directory=config.input_directory,
        output_directory=config.output_directory,
        archive_output_directory=config.archive_output_directory,
        graphdb_admin_password="secret",
    )


@pytest.fixture()
def fake_adapter(monkeypatch) -> type[FakeAdapter]:
    """
    Replaces the pipeline's GraphDBAdapter with the recording fake.

    :param monkeypatch: pytest monkeypatch.
    :return: The fake class.
    """
    FakeAdapter.failures = {}
    FakeAdapter.copied = ["features.nt.gz"]
    monkeypatch.setattr(pipeline, "GraphDBAdapter", FakeAdapter)
    return FakeAdapter


def test_load_graphdb_does_not_clear_when_there_is_nothing_to_load(
    etl_config, fake_adapter
):
    fake_adapter.copied = []

    with pytest.raises(PipelineError, match="No RDF files"):
        Pipeline(etl_config).load_graphdb()

    assert "clear_repository" not in fake_adapter.calls


def test_load_graphdb_copies_before_clearing_and_waits_for_the_import(
    etl_config, fake_adapter
):
    Pipeline(etl_config).load_graphdb()

    assert fake_adapter.calls == [
        "enable_security",
        "set_password",
        "create_repository_from_config",
        "copy_triples",
        "clear_repository",
        "import_files",
        "enable_guest_access",
    ]
    # The fake answers any name, so check each step exists on the real adapter
    for name in fake_adapter.calls:
        assert callable(getattr(GraphDBAdapter, name))


def test_load_graphdb_fails_when_the_import_fails(etl_config, fake_adapter):
    fake_adapter.failures = {"import_files": GraphDBImportError("ERROR: bad file")}

    with pytest.raises(PipelineError, match="Importing the RDF files failed"):
        Pipeline(etl_config).load_graphdb()

    # Nothing after the failed step runs
    assert fake_adapter.calls[-1] == "import_files"
    assert "enable_guest_access" not in fake_adapter.calls


def test_load_graphdb_wraps_request_errors(etl_config, fake_adapter):
    fake_adapter.failures = {
        "create_repository_from_config": requests.ConnectionError("down")
    }

    with pytest.raises(PipelineError, match="Creating the repository failed"):
        Pipeline(etl_config).load_graphdb()

    assert "copy_triples" not in fake_adapter.calls


def test_build_time_of_the_legacy_dump_is_its_date(etl_config):
    etl_config.release_date = "2026-10-17"
    assert Pipeline(etl_config).build_time() == datetime(
        2026, 10, 17, tzinfo=timezone.utc
    )

    etl_config.legacy_dump = True
    assert Pipeline(etl_config).build_time() == datetime(
        2021, 8, 25, tzinfo=timezone.utc
    )


@pytest.fixture()
def pipeline_runs(monkeypatch) -> list[bool]:
    """
    Replaces Pipeline.run with a recorder of each run's LEGACY_DUMP value.

    :param monkeypatch: pytest monkeypatch.
    :return: True for each legacy release, False for each current release.
    """
    runs: list[bool] = []
    monkeypatch.setattr(
        Pipeline, "run", lambda self: runs.append(self.config.legacy_dump)
    )
    return runs


def test_publisher_builds_a_missing_legacy_release_first(etl_config, pipeline_runs):
    ReleasePublisher(etl_config).run()
    assert pipeline_runs == [True, False]


def test_publisher_skips_the_legacy_release_when_disabled(etl_config, pipeline_runs):
    etl_config.publish_legacy_release = False
    ReleasePublisher(etl_config).run()
    assert pipeline_runs == [False]


def test_publisher_skips_a_legacy_release_in_the_archive(etl_config, pipeline_runs):
    etl_config.archive_output_directory.mkdir(parents=True, exist_ok=True)
    (etl_config.archive_output_directory / "gnis-ld-210825.nt.gz").touch()
    ReleasePublisher(etl_config).run()
    assert pipeline_runs == [False]


def test_publisher_only_builds_the_legacy_release_for_a_legacy_dump(
    etl_config, pipeline_runs
):
    etl_config.legacy_dump = True
    ReleasePublisher(etl_config).run()
    assert pipeline_runs == [True]


def test_publisher_stops_when_a_legacy_release_fails(etl_config, monkeypatch):
    def fail(self: Pipeline) -> None:
        raise PipelineError("SHACL validation failed")

    monkeypatch.setattr(Pipeline, "run", fail)
    with pytest.raises(PipelineError):
        ReleasePublisher(etl_config).run()


def _crosswalk(name: str, result: Path | None, built: list[str]) -> type:
    """
    Builds a crosswalk class whose build records its name and returns result.

    :param name: Name of the class.
    :param result: What build returns.
    :param built: List the class's name is appended to on build.
    :return: The class.
    """

    def build(self) -> Path | None:
        built.append(name)
        return result

    return type(name, (), {"__init__": lambda self, config: None, "build": build})


def test_add_crosswalks_fails_when_a_crosswalk_writes_nothing(etl_config, monkeypatch):
    built: list[str] = []
    crosswalks = (
        _crosswalk("FailingCrosswalk", None, built),
        _crosswalk("WorkingCrosswalk", Path("links.nt.gz"), built),
    )
    monkeypatch.setattr(Pipeline, "CROSSWALKS", crosswalks)

    with pytest.raises(PipelineError, match="by FailingCrosswalk;"):
        Pipeline(etl_config).add_crosswalks()
    # Every crosswalk runs, so the error names all that failed
    assert built == ["FailingCrosswalk", "WorkingCrosswalk"]


def test_add_crosswalks_passes_when_every_crosswalk_writes_links(
    etl_config, monkeypatch
):
    built: list[str] = []
    crosswalks = (_crosswalk("WorkingCrosswalk", Path("links.nt.gz"), built),)
    monkeypatch.setattr(Pipeline, "CROSSWALKS", crosswalks)
    Pipeline(etl_config).add_crosswalks()
    assert built == ["WorkingCrosswalk"]
