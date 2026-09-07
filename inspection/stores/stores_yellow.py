# inspection/stores/stores_yellow.py
#
# Run from anywhere:
#
#     python -m inspection.stores.yellow
#
# It reads:
#     data/reference/yellow_stations.csv
#
# and compares the station IDs in the CSV against
# PriceFull files from Paz's publishedprices account.

import csv
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup


PROJECT_ROOT = Path(__file__).resolve().parents[2]

BASE_URL = "https://url.publishedprices.co.il"

USERNAME = "Paz_bo"
PASSWORD = "paz468"

CHAIN_ID = "7290644700005"

CSV_FILE = PROJECT_ROOT / "data/reference/yellow_stations.csv"

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


def get_csv_stations():
    stations = {}

    with CSV_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:

        reader = csv.reader(f)

        for row in reader:
            if not row:
                continue

            station_id = row[0].strip()

            if not station_id.isdigit():
                continue

            station_id = str(int(station_id))

            stations[station_id] = row

    return stations


def main():
    print("Loading yellow_stations.csv...")

    stations = get_csv_stations()

    print(
        f"CSV stations: {len(stations)}"
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

    only_published = sorted(
        published_ids - stations.keys(),
        key=int,
    )

    only_csv = sorted(
        stations.keys() - published_ids,
        key=int,
    )

    both = published_ids & stations.keys()

    print()
    print("=" * 70)
    print("YELLOW STORE ID COMPARISON")
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

    print()
    print("-" * 70)
    print("ONLY IN PUBLISHEDPRICES")
    print("-" * 70)

    for station_id in only_published:
        print(station_id)

    print()
    print("-" * 70)
    print("ONLY IN CSV")
    print("-" * 70)

    for station_id in only_csv:
        row = stations[station_id]

        print(
            f"{station_id}: "
            f"{','.join(row[1:])}"
        )


if __name__ == "__main__":
    main()