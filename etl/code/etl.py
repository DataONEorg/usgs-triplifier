import logging
import sys

from config import EtlConfig
from pipeline import PipelineError, ReleasePublisher


def main() -> None:
    """
    Publishes the missing legacy releases and the current release with
    settings from the environment, logging to stdout. Exits with status 1
    when a release cannot be published.
    """
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    try:
        ReleasePublisher(EtlConfig()).run()
    except PipelineError as error:
        logging.getLogger("etl").error(str(error))
        sys.exit(1)


if __name__ == "__main__":
    main()
