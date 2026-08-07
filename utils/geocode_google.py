import asyncio
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv


load_dotenv()


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STORES_DIR = DATA_DIR / "stores"


GOOGLE_GEOCODE_URL = (
    "https://maps.googleapis.com/maps/api/geocode/json"
)


API_KEY = os.getenv("GEOCODE_API")


REQUEST_DELAY_SECONDS = 0.1


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


    response = await client.get(
        GOOGLE_GEOCODE_URL,
        params=params,
    )

    response.raise_for_status()

    data = response.json()


    if data.get("status") != "OK":
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
                print(
                    f"  skip {store.get('store_id')}: missing address/city"
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


            print(
                f"  {store['store_id']} "
                f"{store['address']} -> {status}"
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

    if not API_KEY:
        raise RuntimeError(
            "Missing GEOCODE_API in .env"
        )


    for path in STORES_DIR.glob("*.json"):

        print(f"\nGeocoding {path.name}")

        await geocode_file(path)



if __name__ == "__main__":
    asyncio.run(main())