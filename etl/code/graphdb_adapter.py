import logging
import shutil
from pathlib import Path

import requests

from config import config


class GraphDBAdapter:
    def __init__(self):
        self.base_url = config.graphdb_url.rstrip("/")
        self.repository_id = config.repository_id
        self.graphdb_import_path = Path(config.graphdb_import_directory)
        self.rdf_output_path = config.output_directory
        self.logger = logging.getLogger("GraphDB Adapter")
        self.auth = (config.graphdb_admin_username, config.graphdb_admin_password)

    def set_password(self):
        """
        Set a new password for the administrator account. GraphDB comes with a default admin account
        which we authenticate with when changing the password.
        """
        response = requests.patch(
            f"{self.base_url}/rest/security/users/{config.graphdb_admin_username}",
            json={
                "password": config.graphdb_admin_password,
            },
            headers={"Content-Type": "application/json"},
            auth=(config.graphdb_admin_username, config.graphdb_default_password),
        )
        response.raise_for_status()
        self.logger.info("Set the GraphDB admin password.")

    def enable_security(self):
        """
        Enables security for GraphDB.
        """
        # First check if security is already enabled
        check_response = requests.get(
            f"{self.base_url}/rest/security",
            headers={"Accept": "application/json"},
        )
        if (
            check_response.status_code == 200
            and check_response.text.strip().lower() == "true"
        ):
            self.logger.info("GraphDB security is already enabled.")
            return

        security_response = requests.post(
            f"{self.base_url}/rest/security",
            json=True,
            headers={"Content-Type": "application/json", "Accept": "text/plain"},
        )
        security_response.raise_for_status()
        self.logger.info("Enabled GraphDB security.")

    def enable_guest_access(self):
        """
        Sets the repository to use the free access security feature.
        """
        response = requests.post(
            f"{self.base_url}/rest/security/free-access",
            json={
                "appSettings": {
                    "DEFAULT_SAMEAS": True,
                    "DEFAULT_INFERENCE": True,
                    "EXECUTE_COUNT": True,
                    "IGNORE_SHARED_QUERIES": False,
                },
                "authorities": [f"READ_REPO_{self.repository_id}"],
                "enabled": True,
            },
            headers={"Content-Type": "application/json"},
            auth=self.auth,
        )
        response.raise_for_status()
        self.logger.info(f"Set the '{self.repository_id}' repository to read-only.")

    def create_repository_from_config(self):
        """
        Creates a GraphDB repository from a configuration file. Does nothing if
        the repository already exists.
        """
        check_response = requests.get(
            f"{self.base_url}/rest/repositories/{self.repository_id}",
            headers={"Accept": "application/json"},
            auth=self.auth,
        )
        if check_response.status_code == 200:
            self.logger.info("GraphDB repository already exists, skipping creation.")
            return

        with open(config.repository_config_path, "rb") as f:
            response = requests.post(
                f"{self.base_url}/rest/repositories",
                files={"config": f},
                auth=self.auth,
            )
        response.raise_for_status()
        self.logger.info("Created the GraphDB repository.")

    def copy_triples(self):
        """Copies the triples that are generated to GRAPHDB_IMPORT_DIRECTORY"""
        self.graphdb_import_path.mkdir(parents=True, exist_ok=True)
        file_paths = list(self.rdf_output_path.glob("*.ttl"))

        if not file_paths:
            self.logger.warning("No triple files found to copy")
            return []

        copied = []
        for file_path in file_paths:
            dest = self.graphdb_import_path / file_path.name
            # Remove existing file if it exists
            if dest.exists():
                dest.unlink()
            shutil.copy2(file_path, dest)
            copied.append(file_path.name)
            self.logger.info(f"Copied {file_path.name} to {dest}")

        return copied

    def upload(self):
        """
        Uploads RDF files to GraphDB.
        """
        file_paths = list(self.graphdb_import_path.glob("*.ttl"))

        if not file_paths:
            self.logger.warning(
                "Failed to find any triple files that should be sent to GraphDB"
            )
            return

        file_names = [f.name for f in file_paths]

        response = requests.post(
            f"{self.base_url}/rest/repositories/{self.repository_id}/import/server",
            json={"fileNames": file_names},
            auth=self.auth,
        )
        response.raise_for_status()
        self.logger.info("Uploaded the triples to GraphDB.")
