# yellow_stores.py
#
# Run from the Metziah project root:
#
#     python yellow_stores.py
#
# Reads:
#     data/reference/yellow_stations.csv
#
# Uses:
#     Paz publishedprices account
#
# Writes:
#     data/stores/yellow.json
#
# Store IDs come from published PriceFull files.
# Metadata comes from yellow_stations.csv.
#
# CSV-only stations are ignored.
# publishedprices-only stations are included with unknown metadata.

import csv
import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://url.publishedprices.co.il"

USERNAME = "Paz_bo"
PASSWORD = "paz468"

CHAIN_ID = "7290644700005"

PROJECT_ROOT = Path(__file__).resolve().parents[3]

CSV_FILE = PROJECT_ROOT / "data/reference/yellow_stations.csv"
OUTPUT_FILE = PROJECT_ROOT / "data/stores/yellow.json"

TIMEOUT = 30


FILE_RE = re.compile(
    rf"^PriceFull{CHAIN_ID}-(?P<subchain>\d+)-"
    rf"(?P<store_id>\d+)-"
    rf"\d{{8}}-\d{{6}}\.gz$",
    re.IGNORECASE,
)


def login(session):
    response = session.get(
        f"{BASE_URL}/login",
        timeout=TIMEOUT,
    )
    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    csrf = soup.find(
        "meta",
        {"name": "csrftoken"},
    )

    if csrf is None:
        raise RuntimeError("Could not find CSRF token")

    response = session.post(
        f"{BASE_URL}/login/user",
        data={
            "r": "",
            "username": USERNAME,
            "password": PASSWORD,
            "Submit": "Sign in",
            "csrftoken": csrf.get("content"),
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()

    if f"Logged in as '{USERNAME}'" not in response.text:
        raise RuntimeError("Login failed")

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    csrf = soup.find(
        "meta",
        {"name": "csrftoken"},
    )

    if csrf is None:
        raise RuntimeError(
            "Could not find CSRF token after login"
        )

    token = csrf.get("content")

    if not token:
        raise RuntimeError(
            "CSRF token after login is empty"
        )

    return token


def get_files(session, csrf_token):
    response = session.post(
        f"{BASE_URL}/file/json/dir",
        data={
            "sEcho": "1",
            "iColumns": "5",
            "sColumns": ",,,,",
            "iDisplayStart": "0",
            "iDisplayLength": "10000",
            "mDataProp_0": "fname",
            "sSearch_0": "",
            "bRegex_0": "false",
            "bSearchable_0": "true",
            "bSortable_0": "true",
            "mDataProp_1": "typeLabel",
            "sSearch_1": "",
            "bRegex_1": "false",
            "bSearchable_1": "true",
            "bSortable_1": "false",
            "mDataProp_2": "size",
            "sSearch_2": "",
            "bRegex_2": "false",
            "bSearchable_2": "true",
            "bSortable_2": "true",
            "mDataProp_3": "ftime",
            "sSearch_3": "",
            "bRegex_3": "false",
            "bSearchable_3": "true",
            "bSortable_3": "true",
            "mDataProp_4": "",
            "sSearch_4": "",
            "bRegex_4": "false",
            "bSearchable_4": "true",
            "bSortable_4": "false",
            "sSearch": "",
            "bRegex": "false",
            "iSortingCols": "0",
            "cd": "/",
            "csrftoken": csrf_token,
        },
        timeout=TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


def get_published_store_ids(response_json):
    store_ids = set()

    for file in response_json.get("aaData", []):
        filename = file.get("fname")

        if not filename:
            continue

        match = FILE_RE.match(filename)

        if match:
            store_ids.add(
                str(int(match.group("store_id")))
            )

    return store_ids


def load_csv_stations():
    stations = {}

    with CSV_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        reader = csv.DictReader(f)

        required_columns = {
            "station_id",
            "name",
            "address",
            "city",
            "services",
        }

        if not required_columns.issubset(reader.fieldnames or []):
            raise RuntimeError(
                "yellow_stations.csv is missing required columns"
            )

        for row in reader:
            station_id = (row["station_id"] or "").strip()

            if not station_id.isdigit():
                continue

            station_id = str(int(station_id))

            stations[station_id] = {
                "name": (row["name"] or "").strip(),
                "address": (row["address"] or "").strip(),
                "city": (row["city"] or "").strip(),
            }

    return stations


def build_stores(published_ids, csv_stations):
    stores = []

    for store_id in sorted(published_ids, key=int):
        station = csv_stations.get(store_id)

        if station is None:
            store = {
                "chain_id": CHAIN_ID,
                "store_id": store_id,
                "name": "unknown",
                "address": "",
                "city": "",
                "zip_code": None,
                "latitude": None,
                "longitude": None,
            }
        else:
            store = {
                "chain_id": CHAIN_ID,
                "store_id": store_id,
                "name": station["name"],
                "address": station["address"],
                "city": station["city"],
                "zip_code": None,
                "latitude": None,
                "longitude": None,
            }

        stores.append(store)

    return stores


def write_json(stores):
    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            stores,
            f,
            ensure_ascii=False,
            indent=4,
        )

        f.write("\n")


def main():
    print("Loading yellow_stations.csv...")

    csv_stations = load_csv_stations()

    print(
        f"CSV stations: {len(csv_stations)}"
    )

    session = requests.Session()

    print("Logging in to publishedprices...")

    csrf_token = login(session)

    print("Requesting files...")

    response_json = get_files(
        session,
        csrf_token,
    )

    published_ids = get_published_store_ids(
        response_json
    )

    print(
        f"Published PriceFull stores: "
        f"{len(published_ids)}"
    )

    both = published_ids & csv_stations.keys()
    only_published = published_ids - csv_stations.keys()
    only_csv = csv_stations.keys() - published_ids

    print()
    print("=" * 70)
    print("YELLOW STORE REGISTRY")
    print("=" * 70)

    print(
        f"Present in both:          {len(both)}"
    )

    print(
        f"Only in publishedprices:  {len(only_published)}"
    )

    print(
        f"Only in CSV:              {len(only_csv)}"
    )

    if only_published:
        print()
        print("Published-only stores:")

        for store_id in sorted(
            only_published,
            key=int,
        ):
            print(f"  {store_id}")

    stores = build_stores(
        published_ids,
        csv_stations,
    )

    write_json(stores)

    print()
    print(
        f"Wrote {len(stores)} stores to "
        f"{OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()