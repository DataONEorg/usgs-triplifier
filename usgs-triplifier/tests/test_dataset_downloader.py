from usgs_triplifier.lib.dataset_downloader import DatasetDownloader
from usgs_triplifier.usgs_products import UsgsProducts


class FakeS3:
    """Records download_file calls instead of contacting S3."""

    def __init__(self) -> None:
        """
        Creates the fake with no recorded calls.
        """
        self.calls: list[tuple[str, str, str]] = []

    def download_file(self, bucket: str, key: str, path: str) -> None:
        """
        Records one download request.

        :param bucket: Bucket name.
        :param key: Object key.
        :param path: Local path the object would be saved to.
        """
        self.calls.append((bucket, key, path))


def test_download_fetches_gpkg_and_text_datasets(tmp_path):
    fake = FakeS3()
    download_dir = tmp_path / "input"

    paths = DatasetDownloader(download_dir, s3=fake).download()

    keys = [call[1] for call in fake.calls]
    assert keys == [
        UsgsProducts.GEOPACKAGE.key,
        UsgsProducts.FEATURES.key,
        UsgsProducts.NAMES.key,
        UsgsProducts.UNITS.key,
        UsgsProducts.HISTORY.key,
    ]
    assert all(call[0] == UsgsProducts.BUCKET for call in fake.calls)
    assert [str(p) for p in paths] == [call[2] for call in fake.calls]
    assert all(p.parent == download_dir for p in paths)
    assert download_dir.is_dir()


def test_legacy_download_fetches_the_legacy_dump(tmp_path):
    fake = FakeS3()

    paths = DatasetDownloader(tmp_path, s3=fake).download(legacy_dump=True)

    assert [call[1] for call in fake.calls] == [
        UsgsProducts.FEATURES.legacy_key,
        UsgsProducts.NAMES.legacy_key,
        UsgsProducts.UNITS.legacy_key,
        UsgsProducts.HISTORY.legacy_key,
    ]
    assert [p.name for p in paths] == [
        "NationalFile.zip",
        "AllNames.zip",
        "GOVT_UNITS.zip",
        "Feature_Description_History.zip",
    ]


def test_default_client_retries_requests(tmp_path):
    s3 = DatasetDownloader(tmp_path).s3
    assert s3.meta.config.retries == {
        "mode": "standard",
        "total_max_attempts": DatasetDownloader.ATTEMPTS,
    }
