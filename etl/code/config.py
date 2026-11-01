from pathlib import Path
from typing import ClassVar

from pydantic import Field

from usgs_triplifier.config import Config


class EtlConfig(Config):
    """
    Settings for the ETL pipeline.
    """

    # Directory holding this file's parent, where gnis-ld-config.ttl is
    ETL_DIR: ClassVar[Path] = Path(__file__).resolve().parent.parent

    graphdb_url: str = Field(default="http://localhost:7200", alias="GRAPHDB_URL")

    # Directory GraphDB imports server files from
    graphdb_import_directory: str = Field(
        default="/root/graphdb-import/", alias="GRAPHDB_IMPORT_DIRECTORY"
    )

    # Seconds to wait for a server import to finish before the run fails
    graphdb_import_timeout: int = Field(
        default=4 * 60 * 60, alias="GRAPHDB_IMPORT_TIMEOUT"
    )

    # Seconds between two polls of the import status
    graphdb_import_poll: int = Field(default=30, alias="GRAPHDB_IMPORT_POLL")

    graphdb_admin_username: str = Field(default="admin", alias="GDB_USER")

    # Password the ETL sets for GDB_USER
    graphdb_admin_password: str = Field(alias="GDB_PASS")

    # Password GraphDB starts with for GDB_USER, used once to set GDB_PASS
    graphdb_default_password: str = Field(default="root", alias="GDB_DEFAULT_PASS")

    # Turtle file describing the repository, used when it does not exist yet
    repository_config_path: Path = Field(
        default=ETL_DIR / "gnis-ld-config.ttl", alias="REPOSITORY_CONFIG"
    )
    repository_id: str = Field(default="gnis-ld", alias="REPOSITORY_ID")

    # When false, the files already in the input directory are used
    download_data: bool = Field(default=True, alias="DOWNLOAD_DATA")

    # Whether the legacy dump is published as a release.
    publish_legacy_release: bool = Field(default=True, alias="PUBLISH_LEGACY_RELEASE")
