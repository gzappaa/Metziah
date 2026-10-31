"""
tests/utils/test_brand_resolution.py

Unit tests for shopper-facing brand resolution logic.
"""

import unittest
from utils.brand_resolution import resolve_shopper_brand, normalize_text_for_matching


class TestBrandResolution(unittest.TestCase):
    def test_hidden_brand_matching_store_name(self):
        # Technical chain Shufersal, store name contains "שלי"
        brands = ["דיל", "אקספרס", "שלי", "GOOD MARKET", "יש", "יוניברס", "יש חסד"]
        result = resolve_shopper_brand("שלי באר יעקב", brands, "שופרסל")
        self.assertEqual(result, "שלי")

        result2 = resolve_shopper_brand("שופרסל אקספרס ויצמן", brands, "שופרסל")
        self.assertEqual(result2, "אקספרס")

    def test_store_using_technical_chain_own_brand(self):
        # Chain name is Shufersal, store name is standard Shufersal without sub-brand
        brands = ["דיל", "אקספרס", "שלי", "GOOD MARKET", "יש"]
        result = resolve_shopper_brand("שופרסל סניף ראשי", brands, "שופרסל")
        self.assertEqual(result, "שופרסל")

    def test_no_configured_brand_matching(self):
        # Store name does not match any brand in array -> falls back to chain name
        brands = ["בר כל"]
        result = resolve_shopper_brand("סופר חסד ירושלים", brands, "נתיב החסד")
        self.assertEqual(result, "נתיב החסד")

    def test_overlapping_brand_names(self):
        # "יש" vs "יש חסד": store with "יש חסד" must match "יש חסד", not "יש"
        brands = ["יש", "יש חסד"]
        result = resolve_shopper_brand("שופרסל יש חסד בני ברק", brands, "שופרסל")
        self.assertEqual(result, "יש חסד")

        # But store with only "יש" matches "יש"
        result_sole = resolve_shopper_brand("שופרסל יש שכונת התקווה", brands, "שופרסל")
        self.assertEqual(result_sole, "יש")

    def test_hebrew_whitespace_and_normalization_variations(self):
        # Extra spaces and tabs
        brands = ["  מיני סופר  ", "am-pm"]
        result = resolve_shopper_brand("דור אלון   מיני   סופר   רמת גן", brands, "דור אלון")
        self.assertEqual(result, "מיני סופר")

        # AM:PM / AM-PM case-insensitivity and punctuation
        result_ampm = resolve_shopper_brand("AM:PM דיזנגוף תל אביב", brands, "דור אלון")
        self.assertEqual(result_ampm, "am-pm")

    def test_empty_brands_array(self):
        result = resolve_shopper_brand("אושר עד תלפיות", [], "אושר עד")
        self.assertEqual(result, "אושר עד")

        result_none = resolve_shopper_brand("טיב טעם סיטי", None, "טיב טעם")
        self.assertEqual(result_none, "טיב טעם")

    def test_avoid_false_positive_substring_matches(self):
        # "שלי" must NOT match inside "שליחים"
        brands = ["שלי", "דיל"]
        result = resolve_shopper_brand("מרכז שליחים ומשלוחים", brands, "שופרסל")
        self.assertEqual(result, "שופרסל")

        # "יש" must NOT match inside "איש" or "רישיון"
        brands_yesh = ["יש"]
        result_ish = resolve_shopper_brand("איש עסקים שיווק", brands_yesh, "שופרסל")
        self.assertEqual(result_ish, "שופרסל")


if __name__ == "__main__":
    unittest.main()
