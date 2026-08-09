from datetime import datetime
import logging
import subprocess
from pathlib import Path
import sys
import time

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

sys.path.insert(0, str(PROJECT_DIR))

from db import get_connection
from utils.update_prices import load_files

FEEDS_DIR = PROJECT_DIR / "data" / "feeds"

PYTHON = sys.executable
LOG_FILE = PROJECT_DIR / "logs" / "scheduler.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE)],
)
logger = logging.getLogger(__name__)

def run(script) -> bool:
    logger.info("Starting %s", script)

    try:
        module = f"downloaders.{script.removesuffix('.py')}"
        subprocess.run(
            [PYTHON, "-m", module],
            cwd=PROJECT_DIR,
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info("Finished %s", script)
        return True

    except subprocess.CalledProcessError as e:
        logger.error("Failed %s (exit code %s)", script, e.returncode)
        if e.stdout:
            logger.error("stdout for %s:\n%s", script, e.stdout.strip())
        if e.stderr:
            logger.error("stderr for %s:\n%s", script, e.stderr.strip())
        return False


def run_prices_and_load():
    start_time = time.time()

    success = run("prices.py")
    if not success:
        logger.error("Skipping DB load -- prices.py download failed")
        return

    new_files = [
        f for f in FEEDS_DIR.glob("*/*/*/prices/*.gz")
        if f.stat().st_mtime >= start_time
    ]

    if not new_files:
        logger.warning("prices.py succeeded but no new .gz files found")
        return

    logger.info("Loading %d new price file(s) into DB", len(new_files))
    with get_connection() as conn:
        load_files(conn, new_files, FEEDS_DIR)

def main():
    print("SCHEDULER STARTED", sys.argv)

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "prices":
            run_prices_and_load()
        elif command == "pricesfull":
            run("pricesfull.py")
        elif command == "promosfull":
            run("promosfull.py")
        elif command == "all":
            run("pricesfull.py")
            run("promosfull.py")
            run_prices_and_load()
        else:
            logger.error("Unknown command: %s", command)

        return

    now = datetime.now()
    hour = now.hour
    minute = now.minute

    if minute == 30 and hour in [4, 16]:
        run("pricesfull.py")
        run("promosfull.py")

    run_prices_and_load()


if __name__ == "__main__":
    main()