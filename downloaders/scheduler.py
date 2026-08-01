from datetime import datetime
import subprocess
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def run(script):
    subprocess.run(
        [
            "python",
            str(BASE_DIR / "downloaders" / script)
        ]
    )


def main():

    now = datetime.now()

    hour = now.hour
    minute = now.minute


    # PriceFull + PromoFull every day 04:30 and 16:30
    if minute == 30 and hour in [4, 16]:
        run("pricefull.py")
        run("promofull.py")


    # Price every 80 minutes
    # later replace this with checking last download time
    run("price.py")


if __name__ == "__main__":
    main()