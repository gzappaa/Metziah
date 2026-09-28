from contextlib import contextmanager
from decimal import Decimal

import pytest

import analytics.notifications.promo_notifications as promo_notifications
from analytics.notifications.promo_notifications import build_digest_email
from database.repository import get_nearby_store_ids

CHAIN_ID = "7290661400001"
OTHER_CHAIN_ID = "9999999999999"

NEARBY_STORE_ID = "TST_NEAR"
FAR_STORE_ID = "TST_FAR"
UNRELATED_STORE_ID = "TST_OTHER"

TEST_PROMOTION_ID = "TESTPROMO1"
TEST_GROUP_ID = "1"
TEST_ITEM_CODE = "9999999999999"

NEAR_LAT, NEAR_LON = 32.317763, 34.846394
FAR_LAT, FAR_LON = 31.7683, 35.2137


def _event(
    chain_id=CHAIN_ID,
    store_id=NEARBY_STORE_ID,
    promotion_id=TEST_PROMOTION_ID,
    group_id=TEST_GROUP_ID,
    item_code=TEST_ITEM_CODE,
    chain_name="Test Chain",
):
    return {
        "chain_id": chain_id,
        "store_id": store_id,
        "promotion_id": promotion_id,
        "group_id": group_id,
        "item_code": item_code,
        "chain_name": chain_name,
        "name": f"Item {item_code}",
        "normal_price": Decimal("15"),
        "discounted_price": Decimal("11"),
        "discount_pct": Decimal("26.67"),
    }


def _insert_store(conn, store_id, lat, lon, name="Test Store"):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chains (
                chain_id,
                name_he_normalized,
                name_en_normalized
            )
            VALUES (%s, %s, %s)
            ON CONFLICT (chain_id) DO NOTHING
            """,
            (CHAIN_ID, "רשת בדיקה", "Test Chain"),
        )

        cur.execute(
            """
            INSERT INTO stores (
                chain_id,
                store_id,
                store_name,
                latitude,
                longitude
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (chain_id, store_id) DO UPDATE SET
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude
            """,
            (CHAIN_ID, store_id, name, lat, lon),
        )


@pytest.fixture
def use_conn_for_run(monkeypatch, conn):
    @contextmanager
    def fake_get_connection():
        yield conn

    monkeypatch.setattr(
        promo_notifications,
        "get_connection",
        fake_get_connection,
    )


@pytest.fixture
def notified_file(tmp_path, monkeypatch):
    path = tmp_path / "notified_promotions.log"
    monkeypatch.setattr(
        promo_notifications,
        "NOTIFIED_FILE",
        path,
    )
    return path


@pytest.fixture
def promo_logs(tmp_path, monkeypatch):
    logs = [
        tmp_path / "promo_changes.log",
        tmp_path / "promo_changes.log.1",
        tmp_path / "promo_changes.log.2",
    ]

    monkeypatch.setattr(
        promo_notifications,
        "PROMO_CHANGES_LOGS",
        logs,
    )

    return logs


@pytest.fixture
def reports_dir(tmp_path, monkeypatch):
    path = tmp_path / "reports"
    monkeypatch.setattr(
        promo_notifications,
        "REPORTS_DIR",
        path,
    )
    return path


def _set_user_location(
    monkeypatch,
    lat=NEAR_LAT,
    lon=NEAR_LON,
    max_km=5,
):
    monkeypatch.setattr(
        promo_notifications.settings,
        "USER_LAT",
        lat,
    )
    monkeypatch.setattr(
        promo_notifications.settings,
        "USER_LON",
        lon,
    )
    monkeypatch.setattr(
        promo_notifications.settings,
        "MAX_STORE_DISTANCE_KM",
        max_km,
    )


# ---------------------------------------------------------------------
# get_nearby_store_ids
# ---------------------------------------------------------------------


def test_store_within_distance_is_found(conn):
    _insert_store(
        conn,
        NEARBY_STORE_ID,
        lat=NEAR_LAT,
        lon=NEAR_LON,
    )

    result = get_nearby_store_ids(
        conn,
        NEAR_LAT,
        NEAR_LON,
        5,
        chain_id=CHAIN_ID,
    )

    assert (CHAIN_ID, NEARBY_STORE_ID) in result


def test_store_outside_distance_is_excluded(conn):
    _insert_store(
        conn,
        FAR_STORE_ID,
        lat=FAR_LAT,
        lon=FAR_LON,
    )

    result = get_nearby_store_ids(
        conn,
        NEAR_LAT,
        NEAR_LON,
        5,
        chain_id=CHAIN_ID,
    )

    assert (CHAIN_ID, FAR_STORE_ID) not in result


def test_nearby_store_search_can_include_all_chains(conn):
    _insert_store(
        conn,
        NEARBY_STORE_ID,
        lat=NEAR_LAT,
        lon=NEAR_LON,
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chains (
                chain_id,
                name_he_normalized,
                name_en_normalized
            )
            VALUES (%s, %s, %s)
            ON CONFLICT (chain_id) DO NOTHING
            """,
            (OTHER_CHAIN_ID, "רשת אחרת", "Other Chain"),
        )

        cur.execute(
            """
            INSERT INTO stores (
                chain_id,
                store_id,
                store_name,
                latitude,
                longitude
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                OTHER_CHAIN_ID,
                "OTHER_NEAR",
                "Other Store",
                NEAR_LAT,
                NEAR_LON,
            ),
        )

    result = get_nearby_store_ids(
        conn,
        NEAR_LAT,
        NEAR_LON,
        5,
        chain_id=None,
    )

    assert (CHAIN_ID, NEARBY_STORE_ID) in result
    assert (OTHER_CHAIN_ID, "OTHER_NEAR") in result


# ---------------------------------------------------------------------
# build_digest_email
# ---------------------------------------------------------------------


def test_digest_email_single_promotion():
    subject, body = build_digest_email(
        [_event()]
    )

    assert "(1)" in subject
    assert NEARBY_STORE_ID in body
    assert "1 new promotion" in body

    # No item-level details in email.
    assert TEST_ITEM_CODE not in body
    assert TEST_PROMOTION_ID not in body


def test_digest_email_multiple_promotions_same_store_are_summed():
    events = [
        _event(item_code=f"ITEM{i}")
        for i in range(5)
    ]

    subject, body = build_digest_email(events)

    assert "(5)" in subject
    assert NEARBY_STORE_ID in body
    assert "5 new promotions" in body

    for i in range(5):
        assert f"ITEM{i}" not in body


def test_digest_email_groups_by_store():
    events = (
        [
            _event(
                item_code=f"A{i}",
                store_id="STORE_A",
                chain_name="Chain A",
            )
            for i in range(2)
        ]
        + [
            _event(
                item_code=f"B{i}",
                store_id="STORE_B",
                chain_name="Chain B",
            )
            for i in range(3)
        ]
    )

    subject, body = build_digest_email(events)

    assert "(5)" in subject
    assert "Chain A store STORE_A: 2 new promotions" in body
    assert "Chain B store STORE_B: 3 new promotions" in body


def test_digest_email_has_no_volume_cap():
    events = [
        _event(item_code=f"ITEM{i}")
        for i in range(25)
    ]

    subject, body = build_digest_email(events)

    assert "(25)" in subject
    assert "25 new promotions" in body
    assert "more new promotion" not in body


# ---------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------


def test_run_sends_email_for_relevant_nearby_promotion(
    conn,
    monkeypatch,
    use_conn_for_run,
    notified_file,
    promo_logs,
    reports_dir,
):
    _insert_store(
        conn,
        NEARBY_STORE_ID,
        lat=NEAR_LAT,
        lon=NEAR_LON,
    )

    event = _event()

    _set_user_location(monkeypatch)

    monkeypatch.setattr(
        promo_notifications.promo_changes,
        "parse",
        lambda paths: (
            {
                "run_date": "2026-09-26",
                "item_added_events": [event],
            },
            None,
        ),
    )

    sent = []

    monkeypatch.setattr(
        promo_notifications,
        "send_email",
        lambda subject, body: sent.append((subject, body)) or True,
    )

    promo_notifications.run()

    assert len(sent) == 1

    subject, body = sent[0]

    assert "(1)" in subject
    assert NEARBY_STORE_ID in body
    assert "1 new promotion" in body

    expected_key = (
        f"{CHAIN_ID}|{NEARBY_STORE_ID}|"
        f"{TEST_PROMOTION_ID}|{TEST_GROUP_ID}|{TEST_ITEM_CODE}"
    )

    assert expected_key in notified_file.read_text()

    report = (
        reports_dir
        / "2026-09-26"
        / "report_promos_details.json"
    )

    assert report.exists()


def test_run_parses_all_rotated_logs(
    conn,
    monkeypatch,
    use_conn_for_run,
    notified_file,
    promo_logs,
    reports_dir,
):
    _insert_store(
        conn,
        NEARBY_STORE_ID,
        lat=NEAR_LAT,
        lon=NEAR_LON,
    )

    events = [
        _event(
            promotion_id="PROMO0",
            item_code="ITEM0",
        ),
        _event(
            promotion_id="PROMO1",
            item_code="ITEM1",
        ),
        _event(
            promotion_id="PROMO2",
            item_code="ITEM2",
        ),
    ]

    _set_user_location(monkeypatch)

    parsed_paths = []

    def fake_parse(paths):
        parsed_paths.extend(paths)

        return (
            {
                "run_date": "2026-09-26",
                "item_added_events": events,
            },
            None,
        )

    monkeypatch.setattr(
        promo_notifications.promo_changes,
        "parse",
        fake_parse,
    )

    sent = []

    monkeypatch.setattr(
        promo_notifications,
        "send_email",
        lambda subject, body: sent.append((subject, body)) or True,
    )

    promo_notifications.run()

    assert parsed_paths == promo_logs
    assert len(parsed_paths) == 3

    assert len(sent) == 1
    assert "(3)" in sent[0][0]
    assert "3 new promotions" in sent[0][1]


def test_run_ignores_unrelated_chain(
    conn,
    monkeypatch,
    use_conn_for_run,
    notified_file,
    promo_logs,
    reports_dir,
):
    _insert_store(
        conn,
        NEARBY_STORE_ID,
        lat=NEAR_LAT,
        lon=NEAR_LON,
    )

    _set_user_location(monkeypatch)

    event = _event(chain_id=OTHER_CHAIN_ID)

    monkeypatch.setattr(
        promo_notifications.promo_changes,
        "parse",
        lambda paths: (
            {
                "run_date": "2026-09-26",
                "item_added_events": [event],
            },
            None,
        ),
    )

    sent = []

    monkeypatch.setattr(
        promo_notifications,
        "send_email",
        lambda s, b: sent.append(1) or True,
    )

    promo_notifications.run()

    assert sent == []


def test_run_ignores_unrelated_store(
    conn,
    monkeypatch,
    use_conn_for_run,
    notified_file,
    promo_logs,
    reports_dir,
):
    _insert_store(
        conn,
        NEARBY_STORE_ID,
        lat=NEAR_LAT,
        lon=NEAR_LON,
    )

    _set_user_location(monkeypatch)

    event = _event(store_id=UNRELATED_STORE_ID)

    monkeypatch.setattr(
        promo_notifications.promo_changes,
        "parse",
        lambda paths: (
            {
                "run_date": "2026-09-26",
                "item_added_events": [event],
            },
            None,
        ),
    )

    sent = []

    monkeypatch.setattr(
        promo_notifications,
        "send_email",
        lambda s, b: sent.append(1) or True,
    )

    promo_notifications.run()

    assert sent == []


def test_run_does_not_duplicate_notification(
    conn,
    monkeypatch,
    use_conn_for_run,
    notified_file,
    promo_logs,
    reports_dir,
):
    _insert_store(
        conn,
        NEARBY_STORE_ID,
        lat=NEAR_LAT,
        lon=NEAR_LON,
    )

    event = _event()

    key = (
        f"{CHAIN_ID}|{NEARBY_STORE_ID}|"
        f"{TEST_PROMOTION_ID}|{TEST_GROUP_ID}|{TEST_ITEM_CODE}"
    )

    notified_file.write_text(
        key + "\n",
        encoding="utf-8",
    )

    _set_user_location(monkeypatch)

    monkeypatch.setattr(
        promo_notifications.promo_changes,
        "parse",
        lambda paths: (
            {
                "run_date": "2026-09-26",
                "item_added_events": [event],
            },
            None,
        ),
    )

    sent = []

    monkeypatch.setattr(
        promo_notifications,
        "send_email",
        lambda s, b: sent.append(1) or True,
    )

    promo_notifications.run()

    assert sent == []


def test_run_does_not_record_notification_on_email_failure(
    conn,
    monkeypatch,
    use_conn_for_run,
    notified_file,
    promo_logs,
    reports_dir,
):
    _insert_store(
        conn,
        NEARBY_STORE_ID,
        lat=NEAR_LAT,
        lon=NEAR_LON,
    )

    event = _event()

    _set_user_location(monkeypatch)

    monkeypatch.setattr(
        promo_notifications.promo_changes,
        "parse",
        lambda paths: (
            {
                "run_date": "2026-09-26",
                "item_added_events": [event],
            },
            None,
        ),
    )

    monkeypatch.setattr(
        promo_notifications,
        "send_email",
        lambda s, b: False,
    )

    promo_notifications.run()

    assert (
        not notified_file.exists()
        or notified_file.read_text() == ""
    )