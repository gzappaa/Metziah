import asyncio
import json

from pathlib import Path

import httpx

import logging

from logging_config import setup_general_logging

from config import settings


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STORES_DIR = DATA_DIR / "stores"


GOOGLE_GEOCODE_URL = (
    "https://maps.googleapis.com/maps/api/geocode/json"
)


API_KEY = settings.GEOCODE_API if settings.ENV == "dev" else None


REQUEST_DELAY_SECONDS = 0.1

setup_general_logging()
logger = logging.getLogger(__name__)

async def geocode(
    client: httpx.AsyncClient,
    address: str,
    city: str,
):

    query = f"{address}, {city}, Israel"

    params = {
        "address": query,
        "key": API_KEY,
        "language": "he",
    }


    try:
        response = await client.get(
            GOOGLE_GEOCODE_URL,
            params=params,
        )

        response.raise_for_status()

    except httpx.HTTPError:
        logger.exception(
            "Geocoding request failed for %s, %s",
            address,
            city,
        )
        return None, None

    data = response.json()


    if data.get("status") != "OK":
        logger.warning(
            "Geocoding failed for %s, %s: status=%s",
            address,
            city,
            data.get("status"),
        )
        return None, None


    result = data["results"][0]


    location = (
        result
        .get("geometry", {})
        .get("location", {})
    )


    lat = location.get("lat")
    lon = location.get("lng")


    return lat, lon



async def geocode_file(path: Path):

    with open(path, encoding="utf-8") as f:
        stores = json.load(f)


    async with httpx.AsyncClient(timeout=10) as client:

        for store in stores:

            if store.get("latitude") is not None:
                continue


            if not store.get("address") or not store.get("city"):
                logger.info(
                    "Skip %s: missing address/city",
                    store.get("store_id"),
                )
                continue


            lat, lon = await geocode(
                client,
                store["address"],
                store["city"],
            )


            store["latitude"] = lat
            store["longitude"] = lon


            status = "ok" if lat else "not found"


            logger.info(
                "%s %s -> %s",
                store["store_id"],
                store["address"],
                status,
            )


            await asyncio.sleep(
                REQUEST_DELAY_SECONDS
            )


    with open(path, "w", encoding="utf-8") as f:

        json.dump(
            stores,
            f,
            ensure_ascii=False,
            indent=4,
        )



async def main():

    if settings.ENV != "dev":
        raise RuntimeError(
            "Google Geocoding is only available in dev environment"
        )

    if not API_KEY:
        raise RuntimeError(
            "Missing GEOCODE_API in .env.dev"
        )

    for path in STORES_DIR.glob("*.json"):

        logger.info("Geocoding %s", path.name)

        await geocode_file(path)



if __name__ == "__main__":
    asyncio.run(main())