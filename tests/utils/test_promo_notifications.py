from contextlib import contextmanager
from decimal import Decimal

import pytest

import utils.promo_notifications as promo_notifications
from utils.promo_notifications import parse_added_line, build_digest_email


CHAIN_ID = "7290661400001"
OTHER_CHAIN_ID = "9999999999999"

NEARBY_STORE_ID = "TST_NEAR"
FAR_STORE_ID = "TST_FAR"
UNRELATED_STORE_ID = "TST_OTHER"

TEST_PROMOTION_ID = "TESTPROMO1"
TEST_GROUP_ID = "1"
TEST_ITEM_CODE = "9999999999999"

NEAR_LAT, NEAR_LON = 32.317763, 34.846394
FAR_LAT, FAR_LON = 31.7683, 35.2137  # Jerusalem, ~60km from NEAR

ADDED_LINE = (
    "2026-08-23 13:15:08,645 [INFO] promo_changes: PROMO ITEM ADDED "
    "chain_id={chain_id} store_id={store_id} promotion_id={promotion_id} "
    "group_id={group_id} item_code={item_code} "
    "name=test discounted_price=11"
)


def _added_line(chain_id=CHAIN_ID, store_id=NEARBY_STORE_ID,
                 promotion_id=TEST_PROMOTION_ID, group_id=TEST_GROUP_ID,
                 item_code=TEST_ITEM_CODE):
    return ADDED_LINE.format(
        chain_id=chain_id,
        store_id=store_id,
        promotion_id=promotion_id,
        group_id=group_id,
        item_code=item_code,
    )


def _insert_store(conn, store_id, lat, lon, name="Test Store"):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO chains (chain_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (CHAIN_ID,),
        )
        cur.execute(
            """
            INSERT INTO stores (chain_id, store_id, store_name, latitude, longitude)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (chain_id, store_id) DO UPDATE SET
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude
            """,
            (CHAIN_ID, store_id, name, lat, lon),
        )


def _insert_promotion(
    conn,
    store_id,
    promotion_id=TEST_PROMOTION_ID,
    group_id=TEST_GROUP_ID,
    item_code=TEST_ITEM_CODE,
    item_name="Test Item",
    discounted_price=Decimal("11"),
    description="Test promo description",
):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO promotions (chain_id, promotion_id, store_id, description)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (chain_id, promotion_id, store_id) DO UPDATE SET
                description = EXCLUDED.description
            """,
            (CHAIN_ID, promotion_id, store_id, description),
        )
        cur.execute(
            """
            INSERT INTO promotion_groups (chain_id, promotion_id, store_id, group_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (chain_id, promotion_id, store_id, group_id) DO NOTHING
            """,
            (CHAIN_ID, promotion_id, store_id, group_id),
        )
        cur.execute(
            """
            INSERT INTO promotion_items (
                chain_id, promotion_id, store_id, group_id, item_code,
                discounted_price
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (chain_id, promotion_id, store_id, group_id, item_code)
            DO UPDATE SET discounted_price = EXCLUDED.discounted_price
            """,
            (CHAIN_ID, promotion_id, store_id, group_id, item_code, discounted_price),
        )
        cur.execute(
            """
            INSERT INTO store_products (chain_id, store_id, item_code, name)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (chain_id, store_id, item_code) DO UPDATE SET
                name = EXCLUDED.name
            """,
            (CHAIN_ID, store_id, item_code, item_name),
        )


@pytest.fixture
def use_conn_for_run(monkeypatch, conn):
    """
    Makes promo_notifications.run() reuse the test's own (uncommitted)
    transaction instead of opening a separate DB connection, so it can
    see data the test just inserted via `conn`.
    """

    @contextmanager
    def fake_get_connection():
        yield conn

    monkeypatch.setattr(promo_notifications, "get_connection", fake_get_connection)


@pytest.fixture
def notified_file(tmp_path, monkeypatch):
    path = tmp_path / "notified_promotions.log"
    monkeypatch.setattr(promo_notifications, "NOTIFIED_FILE", path)
    return path


@pytest.fixture
def promo_log(tmp_path, monkeypatch):
    path = tmp_path / "promo_changes.log"
    monkeypatch.setattr(promo_notifications, "PROMO_CHANGES_LOG", path)
    return path


def _write_log(path, *lines):
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _set_user_location(monkeypatch, lat=NEAR_LAT, lon=NEAR_LON, max_km=5):
    monkeypatch.setattr(promo_notifications.settings, "USER_LAT", lat)
    monkeypatch.setattr(promo_notifications.settings, "USER_LON", lon)
    monkeypatch.setattr(promo_notifications.settings, "MAX_STORE_DISTANCE_KM", max_km)


def _fake_details(item_code, promotion_id=TEST_PROMOTION_ID,
                   store_id=NEARBY_STORE_ID, store_name="Test Store"):
    return {
        "store_name": store_name,
        "store_id": store_id,
        "item_name": f"Item {item_code}",
        "item_code": item_code,
        "promotion_id": promotion_id,
        "group_id": TEST_GROUP_ID,
        "description": "Test promo description",
        "discounted_price": Decimal("11"),
        "discounted_price_per_mida": None,
        "discount_rate": None,
        "min_qty": None,
        "max_qty": None,
        "start_datetime": None,
        "end_datetime": None,
    }


# ---------------------------------------------------------------------
# parse_added_line
# ---------------------------------------------------------------------

def test_parse_added_line_extracts_fields():
    event = parse_added_line(_added_line())

    assert event == {
        "chain_id": CHAIN_ID,
        "store_id": NEARBY_STORE_ID,
        "promotion_id": TEST_PROMOTION_ID,
        "group_id": TEST_GROUP_ID,
        "item_code": TEST_ITEM_CODE,
    }


def test_parse_added_line_ignores_unrelated_lines():
    assert parse_added_line("PROMO ITEM CHANGED chain_id=1 store_id=1") is None
    assert parse_added_line("some unrelated log line") is None


# ---------------------------------------------------------------------
# get_nearby_store_ids
# ---------------------------------------------------------------------

def test_store_within_distance_is_found(conn):
    from database.repository import get_nearby_store_ids

    _insert_store(conn, NEARBY_STORE_ID, lat=NEAR_LAT, lon=NEAR_LON)

    result = get_nearby_store_ids(conn, CHAIN_ID, NEAR_LAT, NEAR_LON, 5)

    assert NEARBY_STORE_ID in result


def test_store_outside_distance_is_excluded(conn):
    from database.repository import get_nearby_store_ids

    _insert_store(conn, FAR_STORE_ID, lat=FAR_LAT, lon=FAR_LON)

    result = get_nearby_store_ids(conn, CHAIN_ID, NEAR_LAT, NEAR_LON, 5)

    assert FAR_STORE_ID not in result


# ---------------------------------------------------------------------
# get_promotion_details
# ---------------------------------------------------------------------

def test_get_promotion_details_returns_expected_fields(conn):
    from database.repository import get_promotion_details

    _insert_store(conn, NEARBY_STORE_ID, lat=NEAR_LAT, lon=NEAR_LON)
    _insert_promotion(conn, NEARBY_STORE_ID)

    details = get_promotion_details(
        conn, CHAIN_ID, NEARBY_STORE_ID, TEST_PROMOTION_ID, TEST_GROUP_ID, TEST_ITEM_CODE
    )

    assert details["store_id"] == NEARBY_STORE_ID
    assert details["item_code"] == TEST_ITEM_CODE
    assert details["discounted_price"] == Decimal("11")
    assert details["description"] == "Test promo description"


def test_get_promotion_details_returns_none_when_missing(conn):
    from database.repository import get_promotion_details

    _insert_store(conn, NEARBY_STORE_ID, lat=NEAR_LAT, lon=NEAR_LON)

    details = get_promotion_details(
        conn, CHAIN_ID, NEARBY_STORE_ID, "does-not-exist", "1", "0000000000000"
    )

    assert details is None


# ---------------------------------------------------------------------
# build_digest_email
# ---------------------------------------------------------------------

def test_digest_email_single_promotion():
    subject, body = build_digest_email([_fake_details(TEST_ITEM_CODE)])

    assert "(1)" in subject
    assert NEARBY_STORE_ID in body
    assert "1 new promotion" in body
    # no item-level detail should leak into the digest anymore
    assert TEST_ITEM_CODE not in body
    assert TEST_PROMOTION_ID not in body
    assert "item_type" not in body.lower()


def test_digest_email_multiple_promotions_same_store_are_summed():
    details_list = [_fake_details(f"ITEM{i}") for i in range(5)]

    subject, body = build_digest_email(details_list)

    assert "(5)" in subject
    assert NEARBY_STORE_ID in body
    assert "5 new promotions" in body
    # still no per-item detail
    for i in range(5):
        assert f"ITEM{i}" not in body


def test_digest_email_groups_by_store():
    details_list = (
        [_fake_details(f"A{i}", store_id="STORE_A", store_name="Store A") for i in range(2)]
        + [_fake_details(f"B{i}", store_id="STORE_B", store_name="Store B") for i in range(3)]
    )

    subject, body = build_digest_email(details_list)

    assert "(5)" in subject
    assert "Store A" in body
    assert "Store B" in body
    assert "2 new promotion" in body
    assert "3 new promotions" in body


def test_digest_email_handles_large_volume_without_a_cap():
    details_list = [_fake_details(f"ITEM{i}") for i in range(25)]

    subject, body = build_digest_email(details_list)

    assert "(25)" in subject
    assert "25 new promotions" in body
    # no overflow/cap wording anymore -- it's just a count
    assert "more new promotion" not in body


# ---------------------------------------------------------------------
# run() end-to-end
# ---------------------------------------------------------------------

def test_run_sends_email_for_relevant_nearby_promotion(
    conn, monkeypatch, use_conn_for_run, notified_file, promo_log
):
    _insert_store(conn, NEARBY_STORE_ID, lat=NEAR_LAT, lon=NEAR_LON)
    _insert_promotion(conn, NEARBY_STORE_ID)
    _write_log(promo_log, _added_line())

    _set_user_location(monkeypatch)

    sent = []
    monkeypatch.setattr(
        promo_notifications,
        "send_email",
        lambda subject, body: sent.append((subject, body)) or True,
    )

    promo_notifications.run()

    assert len(sent) == 1
    subject, body = sent[0]
    assert NEARBY_STORE_ID in body
    assert "1 new promotion" in body
    assert notified_file.exists()
    expected_key = f"{CHAIN_ID}|{NEARBY_STORE_ID}|{TEST_PROMOTION_ID}|{TEST_GROUP_ID}|{TEST_ITEM_CODE}"
    assert expected_key in notified_file.read_text()


def test_run_sends_single_digest_email_for_multiple_promotions(
    conn, monkeypatch, use_conn_for_run, notified_file, promo_log
):
    """
    Several distinct new promotion items at nearby stores in one run
    must produce exactly ONE email, not one per promotion.
    """
    _insert_store(conn, NEARBY_STORE_ID, lat=NEAR_LAT, lon=NEAR_LON)

    item_codes = [f"888800000000{i}" for i in range(3)]
    lines = []

    for i, item_code in enumerate(item_codes):
        promotion_id = f"MULTIPROMO{i}"
        _insert_promotion(
            conn,
            NEARBY_STORE_ID,
            promotion_id=promotion_id,
            item_code=item_code,
        )
        lines.append(
            _added_line(promotion_id=promotion_id, item_code=item_code)
        )

    _write_log(promo_log, *lines)

    _set_user_location(monkeypatch)

    sent = []
    monkeypatch.setattr(
        promo_notifications,
        "send_email",
        lambda subject, body: sent.append((subject, body)) or True,
    )

    promo_notifications.run()

    assert len(sent) == 1  # one digest, not three separate emails

    subject, body = sent[0]
    assert "(3)" in subject
    assert NEARBY_STORE_ID in body
    assert "3 new promotions" in body

    notified_text = notified_file.read_text()
    for i, item_code in enumerate(item_codes):
        assert f"{CHAIN_ID}|{NEARBY_STORE_ID}|MULTIPROMO{i}|{TEST_GROUP_ID}|{item_code}" in notified_text


def test_run_ignores_unrelated_chain(
    conn, monkeypatch, use_conn_for_run, notified_file, promo_log
):
    _insert_store(conn, NEARBY_STORE_ID, lat=NEAR_LAT, lon=NEAR_LON)

    _write_log(promo_log, _added_line(chain_id=OTHER_CHAIN_ID))

    _set_user_location(monkeypatch)

    sent = []
    monkeypatch.setattr(
        promo_notifications, "send_email", lambda s, b: sent.append(1) or True
    )

    promo_notifications.run()

    assert sent == []


def test_run_ignores_unrelated_store(
    conn, monkeypatch, use_conn_for_run, notified_file, promo_log
):
    _insert_store(conn, NEARBY_STORE_ID, lat=NEAR_LAT, lon=NEAR_LON)
    _write_log(promo_log, _added_line(store_id=UNRELATED_STORE_ID))

    _set_user_location(monkeypatch)

    sent = []
    monkeypatch.setattr(
        promo_notifications, "send_email", lambda s, b: sent.append(1) or True
    )

    promo_notifications.run()

    assert sent == []


def test_run_does_not_duplicate_notification(
    conn, monkeypatch, use_conn_for_run, notified_file, promo_log
):
    _insert_store(conn, NEARBY_STORE_ID, lat=NEAR_LAT, lon=NEAR_LON)
    _insert_promotion(conn, NEARBY_STORE_ID)
    _write_log(promo_log, _added_line())

    key = f"{CHAIN_ID}|{NEARBY_STORE_ID}|{TEST_PROMOTION_ID}|{TEST_GROUP_ID}|{TEST_ITEM_CODE}"
    notified_file.write_text(key + "\n", encoding="utf-8")

    _set_user_location(monkeypatch)

    sent = []
    monkeypatch.setattr(
        promo_notifications, "send_email", lambda s, b: sent.append(1) or True
    )

    promo_notifications.run()

    assert sent == []


def test_run_does_not_record_notification_on_email_failure(
    conn, monkeypatch, use_conn_for_run, notified_file, promo_log
):
    _insert_store(conn, NEARBY_STORE_ID, lat=NEAR_LAT, lon=NEAR_LON)
    _insert_promotion(conn, NEARBY_STORE_ID)
    _write_log(promo_log, _added_line())

    _set_user_location(monkeypatch)

    monkeypatch.setattr(promo_notifications, "send_email", lambda s, b: False)

    promo_notifications.run()

    assert not notified_file.exists() or notified_file.read_text() == ""