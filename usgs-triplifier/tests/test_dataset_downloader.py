from usgs_triplifier.lib import dataset_downloader
from usgs_triplifier.lib.dataset_downloader import (
    BUCKET,
    GPKG_KEY,
    TEXT_DATASETS,
    DatasetDownloader,
)


class FakeS3:
    def __init__(self):
        self.calls = []

    def download_file(self, bucket, key, path):
        self.calls.append((bucket, key, path))


def _fake_client(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(dataset_downloader.boto3, "client", lambda *a, **kw: fake)
    return fake


def test_download_fetches_gpkg_and_text_datasets(data_dirs, monkeypatch):
    input_dir, _ = data_dirs
    fake = _fake_client(monkeypatch)

    DatasetDownloader.download()

    keys = [call[1] for call in fake.calls]
    assert keys == [GPKG_KEY, *TEXT_DATASETS]
    assert all(call[0] == BUCKET for call in fake.calls)
    assert all(call[2].startswith(str(input_dir)) for call in fake.calls)


def test_download_gpkg_only(data_dirs, monkeypatch):
    fake = _fake_client(monkeypatch)
    DatasetDownloader.download_gpkg()
    assert [call[1] for call in fake.calls] == [GPKG_KEY]


def test_download_text_only(data_dirs, monkeypatch):
    fake = _fake_client(monkeypatch)
    DatasetDownloader.download_text()
    assert [call[1] for call in fake.calls] == list(TEXT_DATASETS)
