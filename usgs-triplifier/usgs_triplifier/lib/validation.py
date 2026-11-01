import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from ..config import Config


class ShaclValidationError(RuntimeError):
    """
    Raised when the Jena loader or validator does not run to completion.
    """


@dataclass(frozen=True)
class ShaclResult:
    """
    The validation results of one severity, result path and constraint
    component.
    """

    severity: str
    count: int
    path: str
    component: str
    focus_node: str
    message: str


class ReleaseValidator:
    """
    Checks the generated N-Triples files against the SHACL shapes in
    shapes/release-shapes.ttl with Apache Jena before a release is exported.

    Every file is loaded into a temporary TDB2 store in the output directory,
    and the whole store is validated, so no triple is skipped and a subject's
    triples from different files are checked together.
    """

    SHAPES_PATH: ClassVar[Path] = (
        Path(__file__).parent.parent / "shapes" / "release-shapes.ttl"
    )

    STORE_NAME: ClassVar[str] = "shacl-store"
    VALIDATOR_JAR: ClassVar[str] = "validate-release.jar"
    VALIDATOR_CLASS: ClassVar[str] = "ValidateRelease"

    # Number of results of each kind that are logged
    LOGGED_RESULTS: ClassVar[int] = 20

    _log: ClassVar[logging.Logger] = logging.getLogger(__name__)

    def __init__(self, config: Config) -> None:
        """
        Creates the validator.

        :param config: Settings holding the output directory, lod_base and
            the Jena settings.
        """
        self.config = config

    def validate(self) -> bool:
        """
        Validates every .nt.gz in the output directory.

        :return: False when any violation is found, True otherwise.
        :raises ShaclValidationError: If the Jena loader or validator fails.
        """
        paths = sorted(self.config.output_directory.glob("*.nt.gz"))
        if not paths:
            self._log.warning("No generated files to validate")
            return True

        store = self.config.output_directory / self.STORE_NAME
        shutil.rmtree(store, ignore_errors=True)
        try:
            self._load(store, paths)
            results = self._run_validator(store)
        finally:
            shutil.rmtree(store, ignore_errors=True)

        violations = [r for r in results if r.severity == "Violation"]
        others = [r for r in results if r.severity != "Violation"]
        self._log.info(
            f"SHACL: validated {len(paths)} files: "
            f"{sum(r.count for r in violations)} violations, "
            f"{sum(r.count for r in others)} warnings"
        )
        for result in others[: self.LOGGED_RESULTS]:
            self._log.warning(f"SHACL warning: {self._describe(result)}")
        for result in violations[: self.LOGGED_RESULTS]:
            self._log.error(f"SHACL violation: {self._describe(result)}")
        return not violations

    def _load(self, store: Path, paths: list[Path]) -> None:
        """
        Loads files into a new TDB2 store with tdb2.tdbloader.

        :param store: Directory of the store.
        :param paths: Gzipped N-Triples files.
        :raises ShaclValidationError: If the loader fails.
        """
        loader = self.config.jena_home / "bin" / "tdb2.tdbloader"
        self._run([str(loader), "--loc", str(store), *map(str, paths)], "loader")

    def _run_validator(self, store: Path) -> list[ShaclResult]:
        """
        Validates the default graph of a TDB2 store with ValidateRelease.

        :param store: Directory of the store.
        :return: One result per severity, result path and constraint component.
        :raises ShaclValidationError: If the validator fails.
        """
        jena = self.config.jena_home
        classpath = f"{jena / self.VALIDATOR_JAR}{os.pathsep}{jena / 'lib' / '*'}"
        command = [
            str(self.config.jena_java_home / "bin" / "java"),
            *self.config.jena_jvm_args.split(),
            "-cp",
            classpath,
            self.VALIDATOR_CLASS,
            str(store),
            str(self.SHAPES_PATH),
            f"{self.config.lod_base}/",
        ]
        output = self._run(command, "validator")
        return [self._parse(line) for line in output.splitlines() if line.strip()]

    def _run(self, command: list[str], name: str) -> str:
        """
        Runs a Jena command with the configured Java runtime and JVM options.

        :param command: The command and its arguments.
        :param name: Name of the command used in the error message.
        :return: The command's standard output.
        :raises ShaclValidationError: If the command exits with a non-zero
            status or cannot be started.
        """
        env = {
            **os.environ,
            "JAVA_HOME": str(self.config.jena_java_home),
            "JVM_ARGS": self.config.jena_jvm_args,
        }
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, env=env, check=False
            )
        except OSError as error:
            raise ShaclValidationError(f"The Jena {name} could not be started: {error}")
        if completed.returncode != 0:
            stderr = completed.stderr.strip().splitlines()[-20:]
            raise ShaclValidationError(
                f"The Jena {name} exited with status {completed.returncode}:\n"
                + "\n".join(stderr)
            )
        return completed.stdout

    @staticmethod
    def _parse(line: str) -> ShaclResult:
        """
        Parses one line of ValidateRelease output.

        :param line: Tab-separated severity, count, path, component, focus
            node and message.
        :return: The result.
        """
        severity, count, path, component, focus_node, message = line.rstrip("\n").split(
            "\t", 5
        )
        return ShaclResult(severity, int(count), path, component, focus_node, message)

    @staticmethod
    def _describe(result: ShaclResult) -> str:
        """
        Formats a result for the log.

        :param result: The result.
        :return: The count, path, constraint component and one example.
        """
        return (
            f"{result.count} x {result.path} {result.component}, "
            f"e.g. {result.focus_node}: {result.message}"
        )
