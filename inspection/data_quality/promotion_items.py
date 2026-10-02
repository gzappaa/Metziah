"""
inspection/data_quality/promotion_items.py

Metziah data quality inspection report for promo items

Generates an Excel workbook and a TXT summary containing database
statistics, promotion-item analysis, orphan analysis, matching analysis,
discount analysis, and store coverage.
"""

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from db import get_connection



REPORT_DIR = Path("inspection/reports")
SHEETS_DIR = Path("inspection/sheets")




def fetch_one(cursor, query):
    cursor.execute(query)
    row = cursor.fetchone()
    return row[0] if row else 0


def fetch_all(cursor, query):
    cursor.execute(query)
    return cursor.fetchall()


def get_overview(cursor):
    return {
        "Chains": fetch_one(cursor, "SELECT COUNT(*) FROM chains"),
        "Stores": fetch_one(cursor, "SELECT COUNT(*) FROM stores"),
        "Products": fetch_one(cursor, "SELECT COUNT(*) FROM products"),
        "Store Products": fetch_one(cursor, "SELECT COUNT(*) FROM store_products"),
        "Products + Store Products": (
            fetch_one(cursor, "SELECT COUNT(*) FROM products")
            + fetch_one(cursor, "SELECT COUNT(*) FROM store_products")
        ),
        "Promotions": fetch_one(cursor, "SELECT COUNT(*) FROM promotions"),
        "Promotion Items": fetch_one(cursor, "SELECT COUNT(*) FROM promotion_items"),
    }


def get_orphan_summary(cursor):
    query = """
        SELECT
            COUNT(*) AS orphan_items,
            COUNT(DISTINCT pi.item_code) AS unique_orphans
        FROM promotion_items pi
        LEFT JOIN products p
            ON p.item_code = pi.item_code
        LEFT JOIN store_products sp
            ON sp.chain_id = pi.chain_id
           AND sp.store_id = pi.store_id
           AND sp.item_code = pi.item_code
        WHERE p.item_code IS NULL
          AND sp.item_code IS NULL
    """

    cursor.execute(query)
    return cursor.fetchone()


def get_promo_by_chain(cursor):
    query = """
        SELECT
            c.name_en_normalized AS chain,
            COUNT(DISTINCT pi.store_id) AS stores,
            COUNT(*) AS promotion_items,
            ROUND(
                COUNT(*)::numeric
                / NULLIF(COUNT(DISTINCT pi.store_id), 0),
                2
            ) AS promotion_items_per_store,
            COUNT(DISTINCT pi.promotion_id) AS promotions,
            ROUND(
                COUNT(*)::numeric
                / NULLIF(COUNT(DISTINCT pi.promotion_id), 0),
                2
            ) AS items_per_promotion
        FROM promotion_items pi
        JOIN chains c
            ON c.chain_id = pi.chain_id
        GROUP BY c.name_en_normalized
        ORDER BY promotion_items DESC
    """
    return fetch_all(cursor, query)


def get_promo_by_store(cursor):
    query = """
        SELECT
            c.name_en_normalized AS chain,
            pi.store_id,
            s.store_name,
            s.city,
            COUNT(*) AS promotion_items,
            COUNT(DISTINCT pi.promotion_id) AS promotions,
            ROUND(
                COUNT(*)::numeric
                / NULLIF(COUNT(DISTINCT pi.promotion_id), 0),
                2
            ) AS items_per_promotion
        FROM promotion_items pi
        JOIN chains c
            ON c.chain_id = pi.chain_id
        LEFT JOIN stores s
            ON s.chain_id = pi.chain_id
           AND s.store_id = pi.store_id
        GROUP BY
            c.name_en_normalized,
            pi.chain_id,
            pi.store_id,
            s.store_name,
            s.city
        ORDER BY promotion_items DESC
    """
    return fetch_all(cursor, query)


def get_orphans_by_chain(cursor):
    query = """
        SELECT
            c.name_en_normalized AS chain,
            COUNT(DISTINCT pi.store_id) AS stores,
            COUNT(*) AS orphan_items,
            COUNT(DISTINCT pi.item_code) AS unique_orphans,
            (
                SELECT COUNT(*)
                FROM promotion_items pi2
                WHERE pi2.chain_id = pi.chain_id
            ) AS total_promotion_items
        FROM promotion_items pi
        JOIN chains c
            ON c.chain_id = pi.chain_id
        LEFT JOIN products p
            ON p.item_code = pi.item_code
        LEFT JOIN store_products sp
            ON sp.chain_id = pi.chain_id
           AND sp.store_id = pi.store_id
           AND sp.item_code = pi.item_code
        WHERE p.item_code IS NULL
          AND sp.item_code IS NULL
        GROUP BY c.name_en_normalized, pi.chain_id
        ORDER BY orphan_items DESC
    """
    return fetch_all(cursor, query)


def get_orphans_by_store(cursor):
    query = """
        SELECT
            c.name_en_normalized AS chain,
            pi.store_id,
            s.store_name,
            s.city,
            COUNT(*) AS orphan_items,
            COUNT(DISTINCT pi.item_code) AS unique_orphans,
            (
                SELECT COUNT(*)
                FROM promotion_items pi2
                WHERE pi2.chain_id = pi.chain_id
                  AND pi2.store_id = pi.store_id
            ) AS total_promotion_items
        FROM promotion_items pi
        JOIN chains c
            ON c.chain_id = pi.chain_id
        LEFT JOIN stores s
            ON s.chain_id = pi.chain_id
           AND s.store_id = pi.store_id
        LEFT JOIN products p
            ON p.item_code = pi.item_code
        LEFT JOIN store_products sp
            ON sp.chain_id = pi.chain_id
           AND sp.store_id = pi.store_id
           AND sp.item_code = pi.item_code
        WHERE p.item_code IS NULL
          AND sp.item_code IS NULL
        GROUP BY
            c.name_en_normalized,
            pi.chain_id,
            pi.store_id,
            s.store_name,
            s.city
        ORDER BY orphan_items DESC
    """
    return fetch_all(cursor, query)


def get_top_orphans(cursor):
    query = """
        SELECT
            c.name_en_normalized AS chain,
            pi.store_id,
            pi.item_code,
            COUNT(*) AS occurrences
        FROM promotion_items pi
        JOIN chains c
            ON c.chain_id = pi.chain_id
        LEFT JOIN products p
            ON p.item_code = pi.item_code
        LEFT JOIN store_products sp
            ON sp.chain_id = pi.chain_id
           AND sp.store_id = pi.store_id
           AND sp.item_code = pi.item_code
        WHERE p.item_code IS NULL
          AND sp.item_code IS NULL
        GROUP BY
            c.name_en_normalized,
            pi.store_id,
            pi.item_code
        ORDER BY occurrences DESC
        LIMIT 50
    """
    return fetch_all(cursor, query)


def get_orphan_details(cursor):
    query = """
        SELECT
            pi.item_code,
            COUNT(*) AS occurrences,
            COUNT(DISTINCT pi.chain_id) AS chains,
            COUNT(DISTINCT pi.store_id) AS stores,
            COUNT(*) FILTER (
                WHERE pi.discounted_price = 0
            ) AS zero_discount,
            COUNT(*) FILTER (
                WHERE pi.discounted_price > 0
            ) AS positive_discount,
            COUNT(*) FILTER (
                WHERE pi.discounted_price IS NULL
            ) AS null_discount
        FROM promotion_items pi
        LEFT JOIN products p
            ON p.item_code = pi.item_code
        LEFT JOIN store_products sp
            ON sp.chain_id = pi.chain_id
           AND sp.store_id = pi.store_id
           AND sp.item_code = pi.item_code
        WHERE p.item_code IS NULL
          AND sp.item_code IS NULL
        GROUP BY pi.item_code
        ORDER BY occurrences DESC
    """
    return fetch_all(cursor, query)


def get_match_summary(cursor):
    query = """
        SELECT
            CASE
                WHEN p.item_code IS NOT NULL
                 AND sp.item_code IS NOT NULL THEN 'Both'
                WHEN p.item_code IS NOT NULL THEN 'Product'
                WHEN sp.item_code IS NOT NULL THEN 'Store Product'
                ELSE 'Orphan'
            END AS match_type,
            COUNT(*) AS promotion_items
        FROM promotion_items pi
        LEFT JOIN products p
            ON p.item_code = pi.item_code
        LEFT JOIN store_products sp
            ON sp.chain_id = pi.chain_id
           AND sp.store_id = pi.store_id
           AND sp.item_code = pi.item_code
        GROUP BY match_type
        ORDER BY promotion_items DESC
    """
    return fetch_all(cursor, query)


def get_top_matched_items(cursor):
    query = """
        SELECT
            CASE
                WHEN p.item_code IS NOT NULL
                 AND sp.item_code IS NOT NULL THEN 'Both'
                WHEN p.item_code IS NOT NULL THEN 'Product'
                WHEN sp.item_code IS NOT NULL THEN 'Store Product'
                ELSE 'Orphan'
            END AS match_type,
            c.name_en_normalized AS chain,
            pi.store_id,
            pi.item_code,
            COUNT(*) AS occurrences
        FROM promotion_items pi
        JOIN chains c
            ON c.chain_id = pi.chain_id
        LEFT JOIN products p
            ON p.item_code = pi.item_code
        LEFT JOIN store_products sp
            ON sp.chain_id = pi.chain_id
           AND sp.store_id = pi.store_id
           AND sp.item_code = pi.item_code
        WHERE p.item_code IS NOT NULL
           OR sp.item_code IS NOT NULL
        GROUP BY
            match_type,
            c.name_en_normalized,
            pi.store_id,
            pi.item_code
        ORDER BY occurrences DESC
        LIMIT 50
    """
    return fetch_all(cursor, query)


def get_discount_analysis(cursor):
    query = """
        SELECT
            c.name_en_normalized AS chain,
            COUNT(*) AS promotion_items,
            COUNT(*) FILTER (
                WHERE pi.discounted_price = 0
            ) AS zero_discount,
            COUNT(*) FILTER (
                WHERE pi.discounted_price > 0
            ) AS positive_discount,
            COUNT(*) FILTER (
                WHERE pi.discounted_price IS NULL
            ) AS null_discount
        FROM promotion_items pi
        JOIN chains c
            ON c.chain_id = pi.chain_id
        GROUP BY c.name_en_normalized
        ORDER BY promotion_items DESC
    """
    return fetch_all(cursor, query)


def get_store_coverage(cursor):
    query = """
        SELECT
            c.name_en_normalized AS chain,
            COUNT(DISTINCT s.store_id) AS total_stores,
            COUNT(DISTINCT pi.store_id) AS stores_with_promos,
            COUNT(DISTINCT s.store_id)
                - COUNT(DISTINCT pi.store_id) AS stores_without_promos,
            ROUND(
                COUNT(DISTINCT pi.store_id)::numeric
                / NULLIF(COUNT(DISTINCT s.store_id), 0) * 100,
                2
            ) AS coverage_percent
        FROM stores s
        JOIN chains c
            ON c.chain_id = s.chain_id
        LEFT JOIN promotion_items pi
            ON pi.chain_id = s.chain_id
           AND pi.store_id = s.store_id
        GROUP BY c.name_en_normalized
        ORDER BY coverage_percent;
    """
    return fetch_all(cursor, query)


def style_sheet(ws):
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9EAF7")

    for column_cells in ws.columns:
        max_length = 0

        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            max_length = max(max_length, len(value))

        width = min(max(max_length + 2, 10), 40)
        ws.column_dimensions[get_column_letter(column_cells[0].column)].width = width


def write_table(ws, headers, rows):
    ws.append(headers)

    for row in rows:
        ws.append(list(row))

    style_sheet(ws)


def create_workbook(data):
    wb = Workbook()
    default = wb.active
    wb.remove(default)

    # ---------------------------------------------------------
    # Overview
    # ---------------------------------------------------------

    ws = wb.create_sheet("Overview")

    ws.append(["Metric", "Count"])

    for metric, value in data["overview"].items():
        ws.append([metric, value])

    ws.append([])
    ws.append(["Quality Metric", "Count"])

    total_items = data["overview"]["Promotion Items"]
    orphan_items, unique_orphans = data["orphan_summary"]

    matched_items = total_items - orphan_items
    orphan_percent = (
        orphan_items / total_items * 100
        if total_items
        else 0
    )

    ws.append(["Orphan Promotion Items", orphan_items])
    ws.append(["Unique Orphan Item Codes", unique_orphans])
    ws.append(["Matched Promotion Items", matched_items])
    ws.append(["Orphan Percentage", orphan_percent / 100])

    ws["B13"].number_format = "0.00%"

    style_sheet(ws)

    # ---------------------------------------------------------
    # Promo by chain
    # ---------------------------------------------------------

    write_table(
        wb.create_sheet("Promo by Chain"),
        [
            "Chain",
            "Stores",
            "Promotion Items",
            "Items / Store",
            "Promotions",
            "Items / Promotion",
        ],
        data["promo_by_chain"],
    )

    # ---------------------------------------------------------
    # Promo by store
    # ---------------------------------------------------------

    write_table(
        wb.create_sheet("Promo by Store"),
        [
            "Chain",
            "Store",
            "Store Name",
            "City",
            "Promotion Items",
            "Promotions",
            "Items / Promotion",
        ],
        data["promo_by_store"],
    )

    # ---------------------------------------------------------
    # Orphans
    # ---------------------------------------------------------

    ws = wb.create_sheet("Orphans")

    ws.append(["Metric", "Count"])
    ws.append(["Total Promotion Items", total_items])
    ws.append(["Orphan Promotion Items", orphan_items])
    ws.append(["Unique Orphan Codes", unique_orphans])
    ws.append([
        "Orphan Percentage",
        orphan_percent / 100,
    ])

    ws["B5"].number_format = "0.00%"

    ws.append([])
    ws.append(["Orphans by Chain"])

    chain_start = ws.max_row + 1

    headers = [
        "Chain",
        "Stores",
        "Orphan Items",
        "Unique Orphans",
        "Total Promotion Items",
    ]

    ws.append(headers)

    for row in data["orphans_by_chain"]:
        ws.append(list(row))

    chain_end = ws.max_row

    ws.append([])
    ws.append(["Top 50 Repeated Orphan Codes"])

    ws.append([
        "Chain",
        "Store",
        "Item Code",
        "Occurrences",
    ])

    for row in data["top_orphans"]:
        ws.append(list(row))

    style_sheet(ws)

    if chain_end >= chain_start:
        ws.conditional_formatting.add(
            f"C{chain_start}:C{chain_end}",
            ColorScaleRule(
                start_type="min",
                start_color="FFFFFF",
                mid_type="percentile",
                mid_value=50,
                mid_color="FFF2CC",
                end_type="max",
                end_color="F4CCCC",
            ),
        )

    # ---------------------------------------------------------
    # Orphans by Store
    # ---------------------------------------------------------

    write_table(
        wb.create_sheet("Orphans by Store"),
        [
            "Chain",
            "Store",
            "Store Name",
            "City",
            "Orphan Items",
            "Unique Orphans",
            "Total Promotion Items",
        ],
        data["orphans_by_store"],
    )

    # ---------------------------------------------------------
    # Orphan Details
    # ---------------------------------------------------------

    write_table(
        wb.create_sheet("Orphan Details"),
        [
            "Item Code",
            "Occurrences",
            "Chains",
            "Stores",
            "Zero Discount",
            "Positive Discount",
            "NULL Discount",
        ],
        data["orphan_details"],
    )

    # ---------------------------------------------------------
    # Matched Items
    # ---------------------------------------------------------

    write_table(
        wb.create_sheet("Matched Items"),
        [
            "Match Type",
            "Promotion Items",
        ],
        data["match_summary"],
    )

    # ---------------------------------------------------------
    # Top matched
    # ---------------------------------------------------------

    write_table(
        wb.create_sheet("Top Matched Items"),
        [
            "Match Type",
            "Chain",
            "Store",
            "Item Code",
            "Occurrences",
        ],
        data["top_matched_items"],
    )

    # ---------------------------------------------------------
    # Discount
    # ---------------------------------------------------------

    write_table(
        wb.create_sheet("Discount Analysis"),
        [
            "Chain",
            "Promotion Items",
            "Zero Discount",
            "Positive Discount",
            "NULL Discount",
        ],
        data["discount_analysis"],
    )

    # ---------------------------------------------------------
    # Store Coverage
    # ---------------------------------------------------------

    write_table(
        wb.create_sheet("Store Coverage"),
        [
            "Chain",
            "Total Stores",
            "Stores With Promos",
            "Stores Without Promos",
            "Coverage %",
        ],
        data["store_coverage"],
    )

    for row in wb["Store Coverage"].iter_rows(
        min_row=2,
        min_col=5,
        max_col=5,
    ):
        row[0].number_format = "0.00%"

    return wb


def build_txt_report(data):
    overview = data["overview"]
    orphan_items, unique_orphans = data["orphan_summary"]

    total_items = overview["Promotion Items"]
    matched_items = total_items - orphan_items

    orphan_percent = (
        orphan_items / total_items * 100
        if total_items
        else 0
    )

    lines = [
        "METZIAH DATA QUALITY REPORT",
        "=" * 80,
        f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "DATABASE OVERVIEW",
        "-" * 80,
    ]

    for metric, value in overview.items():
        lines.append(f"{metric:<30} {value:,}")

    lines.extend([
        "",
        "PROMOTION ITEM QUALITY",
        "-" * 80,
        f"{'Total promotion items':<30} {total_items:,}",
        f"{'Matched promotion items':<30} {matched_items:,}",
        f"{'Orphan promotion items':<30} {orphan_items:,}",
        f"{'Unique orphan item codes':<30} {unique_orphans:,}",
        f"{'Orphan percentage':<30} {orphan_percent:.2f}%",
        "",
        "TOP 20 ORPHAN CODES",
        "-" * 80,
    ])

    for index, row in enumerate(data["top_orphans"][:20], start=1):
        chain, store, item_code, occurrences = row

        lines.append(
            f"{index:>2}. "
            f"{chain} | "
            f"store={store} | "
            f"item={item_code} | "
            f"occurrences={occurrences:,}"
        )

    lines.extend([
        "",
        "PROMOTION ITEMS BY CHAIN",
        "-" * 80,
    ])

    for row in data["promo_by_chain"]:
        chain, stores, items, per_store, promotions, per_promotion = row

        lines.append(
            f"{chain:<35} "
            f"stores={stores:,} "
            f"items={items:,} "
            f"items/store={per_store:,.2f}"
        )

    lines.extend([
        "",
        "MATCH SUMMARY",
        "-" * 80,
    ])

    for match_type, count in data["match_summary"]:
        lines.append(
            f"{match_type:<20} {count:,}"
        )

    lines.extend([
        "",
        "END OF REPORT",
        "",
    ])

    return "\n".join(lines)


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    
    SHEETS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d")
    

    xlsx_path = SHEETS_DIR / f"data_quality_{timestamp}.xlsx"
    txt_path = REPORT_DIR / f"data_quality_{timestamp}.txt"

    with get_connection() as conn:
        with conn.cursor() as cursor:
            data = {
                "overview": get_overview(cursor),
                "orphan_summary": get_orphan_summary(cursor),
                "promo_by_chain": get_promo_by_chain(cursor),
                "promo_by_store": get_promo_by_store(cursor),
                "orphans_by_chain": get_orphans_by_chain(cursor),
                "orphans_by_store": get_orphans_by_store(cursor),
                "top_orphans": get_top_orphans(cursor),
                "orphan_details": get_orphan_details(cursor),
                "match_summary": get_match_summary(cursor),
                "top_matched_items": get_top_matched_items(cursor),
                "discount_analysis": get_discount_analysis(cursor),
                "store_coverage": get_store_coverage(cursor),
            }

    workbook = create_workbook(data)
    workbook.save(xlsx_path)

    txt_path.write_text(
        build_txt_report(data),
        encoding="utf-8",
    )

    print(f"Excel report: {xlsx_path}")
    print(f"TXT report:   {txt_path}")


if __name__ == "__main__":
    main()