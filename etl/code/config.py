from pydantic import Field

from usgs_triplifier.config import Config as TriplifierConfig


class Config(TriplifierConfig):
    """
    ETL settings.

    Extends the triplifier package settings so the data directories resolve
    identically here and inside the triplifiers, and adds the GraphDB-only
    fields.
    """

    # GraphDB configuration
    graphdb_url: str = Field(default="http://localhost:7200", alias="GRAPHDB_URL")
    graphdb_import_directory: str = Field(
        default="/root/graphdb-import/", alias="GRAPHDB_IMPORT_DIRECTORY"
    )
    graphdb_admin_username: str = Field(default="admin", alias="GDB_USER")
    graphdb_admin_password: str = Field(alias="GDB_PASS")
    graphdb_default_password: str = Field(default="root", alias="GDB_DEFAULT_PASS")
    repository_config_path: str = Field(
        default="gnis-ld-config.ttl", alias="REPOSITORY_CONFIG"
    )
    repository_id: str = Field(default="gnis-ld", alias="REPOSITORY_ID")

    download_data: bool = Field(default=True, alias="DOWNLOAD_DATA")


config = Config()
