from datetime import datetime
import logging
import subprocess
from pathlib import Path
import sys


BASE_DIR = Path(__file__).resolve().parent      # metziah/downloaders
PROJECT_DIR = BASE_DIR.parent                   # metziah

PYTHON = sys.executable

LOG_FILE = PROJECT_DIR / "logs" / "scheduler.log"

LOG_FILE.parent.mkdir(
    parents=True,
    exist_ok=True
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE)
    ],
)

logger = logging.getLogger(__name__)



def run(script):

    logger.info(
        "Starting %s",
        script
    )

    try:

        module = (
            f"downloaders."
            f"{script.removesuffix('.py')}"
        )

        subprocess.run(
            [
                PYTHON,
                "-m",
                module,
            ],
            cwd=PROJECT_DIR,
            check=True,
            capture_output=True,
            text=True,
        )

        logger.info(
            "Finished %s",
            script
        )


    except subprocess.CalledProcessError as e:

        logger.error(
            "Failed %s (exit code %s)",
            script,
            e.returncode,
        )

        if e.stdout:
            logger.error(
                "stdout for %s:\n%s",
                script,
                e.stdout.strip(),
            )

        if e.stderr:
            logger.error(
                "stderr for %s:\n%s",
                script,
                e.stderr.strip(),
            )


def main():

    print(
        "SCHEDULER STARTED",
        sys.argv
    )


    # Manual execution mode
    if len(sys.argv) > 1:

        command = sys.argv[1]


        if command == "prices":

            run("prices.py")


        elif command == "pricesfull":

            run("pricesfull.py")


        elif command == "promosfull":

            run("promosfull.py")


        elif command == "all":

            run("pricesfull.py")
            run("promosfull.py")
            run("prices.py")


        else:

            logger.error(
                "Unknown command: %s",
                command
            )


        return



    # Cron mode
    now = datetime.now()

    hour = now.hour
    minute = now.minute


    # PriceFull + PromoFull every day 04:30 and 16:30
    if minute == 30 and hour in [4, 16]:

        run("pricesfull.py")
        run("promosfull.py")


    # Price every scheduler run
    run("prices.py")



if __name__ == "__main__":

    main()