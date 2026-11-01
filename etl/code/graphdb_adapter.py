import logging
import shutil
import time
from pathlib import Path
from typing import ClassVar

import requests

from config import EtlConfig


class GraphDBImportError(Exception):
    """
    Raised when a server import fails or does not finish in time.
    """


class GraphDBAdapter:
    """
    Calls the GraphDB REST API to secure the server, create and clear the
    repository, and import the generated RDF files.
    """

    _log: ClassVar[logging.Logger] = logging.getLogger(__name__)

    def __init__(self, config: EtlConfig) -> None:
        """
        Creates the adapter.

        :param config: Settings holding the GraphDB URL, import directory,
            credentials and repository, and the output directory of the RDF files.
        """
        self.config = config
        self.base_url = config.graphdb_url.rstrip("/")
        self.repository_id = config.repository_id
        self.graphdb_import_path = Path(config.graphdb_import_directory)
        self.rdf_output_path = config.output_directory
        self.auth = (config.graphdb_admin_username, config.graphdb_admin_password)

    def set_password(self) -> None:
        """
        Sets the GDB_USER password to GDB_PASS. GraphDB starts with the
        password GDB_DEFAULT_PASS and keeps its home directory between runs,
        so the password is only changed when GraphDB does not already accept
        GDB_PASS.

        :raises requests.HTTPError: If GraphDB rejects the password change.
        """
        user_url = (
            f"{self.base_url}/rest/security/users/{self.config.graphdb_admin_username}"
        )
        if requests.get(user_url, auth=self.auth).status_code == 200:
            self._log.info("The GraphDB admin password is already set.")
            return

        response = requests.patch(
            user_url,
            json={"password": self.config.graphdb_admin_password},
            headers={"Content-Type": "application/json"},
            auth=(
                self.config.graphdb_admin_username,
                self.config.graphdb_default_password,
            ),
        )
        response.raise_for_status()
        self._log.info("The GraphDB admin password was set.")

    def enable_security(self) -> None:
        """
        Turns on GraphDB security, unless GraphDB reports it is already on.

        :raises requests.HTTPError: If GraphDB rejects the request.
        """
        check_response = requests.get(
            f"{self.base_url}/rest/security",
            headers={"Accept": "application/json"},
        )
        if (
            check_response.status_code == 200
            and check_response.text.strip().lower() == "true"
        ):
            self._log.info("GraphDB security is already enabled.")
            return

        response = requests.post(
            f"{self.base_url}/rest/security",
            json=True,
            headers={"Content-Type": "application/json", "Accept": "text/plain"},
        )
        response.raise_for_status()
        self._log.info("Enabled GraphDB security.")

    def enable_guest_access(self) -> None:
        """
        Turns on GraphDB free access.

        :raises requests.HTTPError: If GraphDB rejects the request.
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
        self._log.info(
            f"Granted anonymous read access to the '{self.repository_id}' repository."
        )

    def create_repository_from_config(self) -> None:
        """
        Creates the repository from the Turtle file at REPOSITORY_CONFIG.
        Does nothing if the repository already exists.

        :raises FileNotFoundError: If the REPOSITORY_CONFIG file does not exist.
        :raises requests.HTTPError: If GraphDB rejects the request.
        """
        check_response = requests.get(
            f"{self.base_url}/rest/repositories/{self.repository_id}",
            headers={"Accept": "application/json"},
            auth=self.auth,
        )
        if check_response.status_code == 200:
            self._log.info("GraphDB repository already exists, skipping creation.")
            return

        with open(self.config.repository_config_path, "rb") as f:
            response = requests.post(
                f"{self.base_url}/rest/repositories",
                files={"config": f},
                auth=self.auth,
            )
        response.raise_for_status()
        self._log.info("Created the GraphDB repository.")

    def clear_repository(self) -> None:
        """
        Removes every statement from the repository.

        :raises requests.HTTPError: If GraphDB rejects the request.
        """
        response = requests.delete(
            f"{self.base_url}/repositories/{self.repository_id}/statements",
            auth=self.auth,
        )
        response.raise_for_status()
        self._log.info("Cleared the previous release from the repository.")

    def copy_triples(self) -> list[str]:
        """
        Replaces the .nt.gz and .ttl files in the GraphDB import directory
        with the ones in the output directory.

        :return: Names of the copied files; empty when the output directory has none.
        """
        self.graphdb_import_path.mkdir(parents=True, exist_ok=True)

        for pattern in ("*.nt.gz", "*.ttl"):
            for stale in self.graphdb_import_path.glob(pattern):
                stale.unlink()

        file_paths = list(self.rdf_output_path.glob("*.nt.gz")) + list(
            self.rdf_output_path.glob("*.ttl")
        )

        if not file_paths:
            self._log.warning("No triple files found to copy")
            return []

        copied = []
        for file_path in file_paths:
            dest = self.graphdb_import_path / file_path.name
            shutil.copy2(file_path, dest)
            copied.append(file_path.name)
            self._log.info(f"Copied {file_path.name} to {dest}")

        return copied

    # Import statuses for failures
    FAILED_STATES: ClassVar[tuple[str, ...]] = ("ERROR", "INTERRUPTING", "INTERRUPTED")

    # Import statuses of a file GraphDB has queued or is importing
    RUNNING_STATES: ClassVar[tuple[str, ...]] = ("PENDING", "IMPORTING")

    # Status fields that change when a file is imported again
    STATUS_FIELDS: ClassVar[tuple[str, ...]] = (
        "status",
        "imported",
        "timestamp",
        "message",
    )

    def import_files(self) -> None:
        """
        Imports every .nt.gz and .ttl file in the import directory into the
        repository and waits for the import to finish.

        :raises requests.HTTPError: If GraphDB rejects a request.
        :raises GraphDBImportError: If GraphDB is still importing one of the
            files from an earlier run, a file fails to import, or the import
            does not finish within GRAPHDB_IMPORT_TIMEOUT.
        """
        names = self._import_file_names()
        if not names:
            self._log.warning("No triple files in the import directory to import")
            return
        before = self.import_statuses()
        running = [
            name
            for name in names
            if before.get(name, {}).get("status") in self.RUNNING_STATES
        ]
        if running:
            raise GraphDBImportError(
                f"GraphDB is still importing {running} from an earlier run"
            )
        self.start_import(names)
        self.wait_for_import(names, before)

    def _import_file_names(self) -> list[str]:
        """
        Lists the files in the import directory.

        :return: Names of the .nt.gz and .ttl files.
        """
        paths = list(self.graphdb_import_path.glob("*.nt.gz")) + list(
            self.graphdb_import_path.glob("*.ttl")
        )
        return [path.name for path in paths]

    def import_statuses(self) -> dict[str, dict]:
        """
        Fetches the server import status of every file GraphDB knows.

        :return: Status objects keyed by file name.
        :raises requests.RequestException: If the request fails.
        """
        response = requests.get(
            f"{self.base_url}/rest/repositories/{self.repository_id}/import/server",
            headers={"Accept": "application/json"},
            auth=self.auth,
            timeout=60,
        )
        response.raise_for_status()
        return {s["name"]: s for s in response.json() if s.get("name")}

    def start_import(self, names: list[str]) -> None:
        """
        Starts a GraphDB server import of files in the import directory.

        :param names: Names of the files to import.
        :raises requests.HTTPError: If GraphDB rejects the request.
        """
        response = requests.post(
            f"{self.base_url}/rest/repositories/{self.repository_id}/import/server",
            json={"fileNames": names},
            auth=self.auth,
        )
        response.raise_for_status()
        self._log.info(f"Started the GraphDB import of {len(names)} files.")

    def wait_for_import(self, names: list[str], before: dict[str, dict]) -> None:
        """
        Polls the server import status until every file is DONE or failed.


        :param names: Names of the submitted files.
        :param before: Statuses from import_statuses() before the import started.
        :raises requests.HTTPError: If GraphDB answers a status request with
            a 4xx response other than 408 or 429.
        :raises GraphDBImportError: If a file's status is one of
            FAILED_STATES, or GRAPHDB_IMPORT_TIMEOUT passes before every
            file is DONE. Every failed file is listed, and on a timeout the
            last status seen for each unfinished file.
        """
        deadline = time.time() + self.config.graphdb_import_timeout
        pending = set(names)
        failed: dict[str, str] = {}
        last_seen: dict[str, str] = {}
        while True:
            try:
                statuses = self.import_statuses()
            except requests.HTTPError as error:
                code = error.response.status_code if error.response is not None else 0
                if 400 <= code < 500 and code not in (408, 429):
                    raise
                self._log.warning(f"Import status request failed: {error}")
                statuses = None
            except requests.RequestException as error:
                self._log.warning(f"Import status request failed: {error}")
                statuses = None
            if statuses is not None:
                for name in sorted(pending):
                    status = statuses.get(name)
                    if status is None:
                        last_seen[name] = "not listed by GraphDB"
                        continue
                    state = status.get("status")
                    message = status.get("message", "")
                    if not self._changed(status, before.get(name)):
                        last_seen[name] = f"unchanged since before the import, {state}"
                        continue
                    last_seen[name] = f"{state}: {message}" if message else str(state)
                    if state == "DONE":
                        self._log.info(f"Imported {name}: {message}")
                        pending.discard(name)
                    elif state in self.FAILED_STATES:
                        self._log.error(
                            f"Import of {name} ended with {state}: {message}"
                        )
                        failed[name] = f"{name} ({state}: {message})"
                        pending.discard(name)
                if not pending:
                    if failed:
                        raise GraphDBImportError(
                            f"Import failed for {', '.join(failed[n] for n in sorted(failed))}"
                        )
                    return
            if time.time() >= deadline:
                waiting = ", ".join(
                    f"{name} ({last_seen.get(name, 'not polled')})"
                    for name in sorted(pending)
                )
                raise GraphDBImportError(
                    f"Import not finished after {self.config.graphdb_import_timeout}s; "
                    f"still waiting for {waiting}"
                    + (f"; failed: {sorted(failed)}" if failed else "")
                )
            time.sleep(self.config.graphdb_import_poll)

    @classmethod
    def _changed(cls, status: dict, before: dict | None) -> bool:
        """
        Checks whether a file's status differs from the one recorded before
        the import started.

        :param status: Current status object.
        :param before: Status object before the import, or None when GraphDB
            had none for the file.
        :return: True when there was no earlier status or one of
            STATUS_FIELDS differs.
        """
        if before is None:
            return True
        return any(status.get(f) != before.get(f) for f in cls.STATUS_FIELDS)
