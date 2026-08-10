import boto3
from botocore import UNSIGNED
from botocore.config import Config as BotoConfig

from ..config import config

# S3 bucket for USGS data
BUCKET = "prd-tnm"

# GPKG dataset (main features)
GPKG_KEY = "StagedProducts/GeographicNames/FullModel/Gazetteer_National_GPKG.zip"

# Text datasets with additional data (names, citations, dates, history)
TEXT_DATASETS = [
    "StagedProducts/GeographicNames/Topical/AllNames_National_Text.zip",
    "StagedProducts/GeographicNames/Topical/PopulatedPlaces_National_Text.zip",
    "StagedProducts/GeographicNames/Topical/HistoricalFeatures_National_Text.zip",
    "StagedProducts/GeographicNames/Topical/GovernmentUnits_National_Text.zip",
    "StagedProducts/GeographicNames/Topical/FeatureDescriptionHistory_National_Text.zip",
]


class DatasetDownloader:
    def __init__(self):
        pass

    @staticmethod
    def download():
        """
        Downloads the GNIS datasets (GPKG and text files).
        """
        download_dir = config.input_directory
        download_dir.mkdir(parents=True, exist_ok=True)
        s3 = boto3.client("s3", config=BotoConfig(signature_version=UNSIGNED))

        # Download GPKG dataset
        DatasetDownloader._download_file(s3, GPKG_KEY, download_dir)

        # Download text datasets
        for key in TEXT_DATASETS:
            DatasetDownloader._download_file(s3, key, download_dir)

        print("Done!")

    @staticmethod
    def download_gpkg():
        """Downloads only the GPKG dataset."""
        download_dir = config.input_directory
        download_dir.mkdir(parents=True, exist_ok=True)
        s3 = boto3.client("s3", config=BotoConfig(signature_version=UNSIGNED))
        DatasetDownloader._download_file(s3, GPKG_KEY, download_dir)
        print("Done!")

    @staticmethod
    def download_text():
        """Downloads only the text datasets."""
        download_dir = config.input_directory
        download_dir.mkdir(parents=True, exist_ok=True)
        s3 = boto3.client("s3", config=BotoConfig(signature_version=UNSIGNED))
        for key in TEXT_DATASETS:
            DatasetDownloader._download_file(s3, key, download_dir)
        print("Done!")

    @staticmethod
    def _download_file(s3, key: str, download_dir):
        """Download a single file from S3."""
        filename = key.split("/")[-1]
        local_path = download_dir / filename
        print(f"Downloading {key}...")
        s3.download_file(BUCKET, key, str(local_path))
        print(f"  Saved to {local_path}")


if __name__ == "__main__":
    DatasetDownloader.download()
