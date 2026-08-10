import logging
import sys

import requests

from usgs_triplifier.lib.dataset_downloader import DatasetDownloader
from usgs_triplifier.lib.gnis import (
    UnitsTriplifier,
    FeaturesTriplifier,
    NamesTriplifier,
    HistoryTriplifier,
)
from config import config
from graphdb_adapter import GraphDBAdapter

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("etl")


def main() -> None:
    if config.download_data:
        logger.info("Downloading...")
        DatasetDownloader.download()
    else:
        logger.info("DOWNLOAD_DATA is disabled, skipping download")

    logger.info("Transforming into RDF...")
    for triplifier in [
        FeaturesTriplifier,
        NamesTriplifier,
        HistoryTriplifier,
        UnitsTriplifier,
    ]:
        triplifier()

    logger.info("Configuring GraphDB")
    graphdb_adapter = GraphDBAdapter()
    steps = [
        ("Enabling GraphDB security", graphdb_adapter.enable_security),
        ("Setting GraphDB password", graphdb_adapter.set_password),
        ("Creating repository", graphdb_adapter.create_repository_from_config),
        ("Copying triples to import directory", graphdb_adapter.copy_triples),
        ("Loading data into GraphDB", graphdb_adapter.upload),
        ("Setting GraphDB permissions", graphdb_adapter.enable_guest_access),
    ]
    for description, step in steps:
        logger.info(description)
        try:
            step()
        except requests.exceptions.RequestException as error:
            logger.error(f"{description} failed: {error}")
            if getattr(error, "response", None) is not None:
                logger.error(f"Response status code: {error.response.status_code}")
                logger.error(f"Response body: {error.response.text}")
            sys.exit(1)

    logger.info("ETL complete")


if __name__ == "__main__":
    main()
