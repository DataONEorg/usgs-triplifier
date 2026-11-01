import logging
from pathlib import Path
from typing import ClassVar

import boto3
from botocore import UNSIGNED
from botocore.client import BaseClient
from botocore.config import Config as BotoConfig

from ..usgs_products import UsgsProducts


class DatasetDownloader:
    """
    Downloads the USGS GNIS products, or a legacy dump, from S3 into a
    directory.
    """

    _log: ClassVar[logging.Logger] = logging.getLogger(__name__)

    # Attempts per S3 request, including the first. A request that times out
    # is retried with exponential backoff. botocore's default is 5 attempts.
    # A download that fails on its last attempt fails the ETL run.
    ATTEMPTS: ClassVar[int] = 10

    def __init__(self, download_dir: Path, s3: BaseClient | None = None) -> None:
        """
        Creates a downloader.

        :param download_dir: Directory the files are saved to; created if missing.
        :param s3: S3 client to download with. Defaults to an anonymous boto3
            client that makes ATTEMPTS attempts per request. The USGS bucket
            is public.
        """
        self.download_dir = download_dir
        self.s3 = s3 or boto3.client(
            "s3",
            config=BotoConfig(
                signature_version=UNSIGNED,
                retries={"mode": "standard", "total_max_attempts": self.ATTEMPTS},
            ),
        )

    def download(self, legacy_dump: bool = False) -> list[Path]:
        """
        Downloads the files a release is built from, replacing any copies
        already in the download directory.

        :param legacy_dump: Whether to download the legacy dump instead of the
            GeoPackage and the current text products.
        :return: Paths of the downloaded files.
        """
        self.download_dir.mkdir(parents=True, exist_ok=True)
        keys = UsgsProducts.download_keys(legacy_dump)
        paths = [self._download_file(key) for key in keys]
        self._log.info(f"Downloaded {len(paths)} files to {self.download_dir}")
        return paths

    def _download_file(self, key: str) -> Path:
        """
        Downloads one object from the USGS bucket.

        :param key: Object key in the bucket.
        :return: Path of the saved file, named after the key's last path segment.
        """
        local_path = self.download_dir / key.split("/")[-1]
        self._log.info(f"Downloading {key}")
        self.s3.download_file(UsgsProducts.BUCKET, key, str(local_path))
        return local_path
