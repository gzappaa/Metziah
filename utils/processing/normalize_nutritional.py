"""
utils/processing/normalize_nutritional.py

Normalizes scraped nutrition rows into clean, comparable rows for `product_nutrition`.

Input  (per row): label, value, unit, size, lt   -- exactly as scraped, messy
Output (per row): NutritionRow(nutrient, amount, unit, basis, bound, flags, ...)

What it fixes:
  1. LABEL  ~120 Hebrew/English spellings -> one canonical key        (SPEC, LABELS)
  2. UNIT   the number is converted to the nutrient's canonical unit  (resolve_unit)
  3. BASIS  the "size" field -> what the number is per: 100g, 100ml, serving, %DV...
  4. DUPES  same nutrient + basis twice in one product -> only the first is canonical

Nothing is dropped silently. Unknown labels and unit problems are kept and flagged, so
the mapping can be fixed later and rows rebuilt from `nutrition_raw`.
Flags: unmapped | unit_missing | unit_mismatch
Pure logic: no DB access, no I/O.
"""

import re
from dataclasses import dataclass, field

# ---------- 1. nutrient spec ----------
# key -> (kind, canonical_unit, [labels exactly as scraped])
# To support a new spelling from a new supermarket, add it to the label list of the right key.
# Labels are matched after clean(), so invisible characters and double spaces don't matter.
SPEC = {
 # energy
 "calories":            ("energy", "kcal", ["Calories", "אנרגיה (קלוריות)"]),
 "calories_from_fat":   ("energy", "kcal", ["Calories From Fat"]),
 "metabolic_energy":    ("energy", "kcal", ["אנרגיה מטבולית"]),
 # fats
 "total_fat":           ("macro", "g",  ["Total Fat", "שומנים (גרם)"]),
 "saturated_fat":       ("macro", "g",  ["Saturated Fat", "חומצות שומן רוויות (גרם)", "חומצות שומן רוויות (גרם) מתוך סך השומנים"]),
 "trans_fat":           ("macro", "g",  ["Trans Fat", "חומצות שומן טראנס (גרם)", "חומצות שומן טראנס (גרם) מתוך סך השומנים"]),
 "monounsaturated_fat": ("macro", "g",  ["Monounsaturated Fat", "שומן חד בלתי רווי (גרם)"]),
 "polyunsaturated_fat": ("macro", "g",  ["Polyunsaturated Fat", "שומן רב בלתי רווי (גרם)"]),
 "cholesterol":         ("macro", "mg", ["Cholesterol", "כולסטרול (מג)", 'כולסטרול (מ"ג) מתוך סך השומנים']),
 # carbs / fiber / protein / salt
 "total_carbs":         ("macro", "g",  ["Total Carbohydrates", "סך הפחמימות (גרם)"]),
 "sugars":              ("macro", "g",  ["Sugar", "סוכרים מתוך פחמימות (גרם)"]),
 "added_sugars":        ("macro", "g",  ["מתוכם סוכר מוסף (גרם)"]),
 "lactose":             ("macro", "g",  ["מתוך הפחמימות לקטוז (גרם)", "סוכרים: לקטוז"]),
 "sugar_teaspoons":     ("macro", "tsp",["כפיות סוכר מתוך סך הפחמימות", "מתוכן כפיות סוכר"]),
 "organic_acids":       ("macro", "g",  ["מתוך סוכרים חומצות אורגניות (גרם)"]),
 "starch":              ("macro", "g",  ["עמילנים (גר`)"]),
 "polyols":             ("macro", "g",  ["רב כהלים (גרם)"]),
 "dietary_fiber":       ("macro", "g",  ["Dietary Fiber", "סיבים תזונתיים (גרם)"]),
 "soluble_fiber":       ("macro", "g",  ["מתוכם סיבים מסיסים (גרם)"]),
 "cellulose":           ("macro", "g",  ["תאית"]),
 "protein":             ("macro", "g",  ["Protein", "חלבונים (גרם)", "חלבונים (אלבומין|קזאין 40|60)"]),
 "sodium":              ("mineral", "mg", ["Sodium", "נתרן (מג)"]),
 "salt":                ("macro", "g",  ["מלח"]),
 # minerals
 "calcium":             ("mineral", "mg",  ["Calcium", "סידן (מג)"]),
 "iron":                ("mineral", "mg",  ["Iron", "ברזל (מג)"]),
 "phosphorus":          ("mineral", "mg",  ["Phosphorous", "זרחן (מג)"]),
 "potassium":           ("mineral", "mg",  ["Potassium", "אשלגן (מג)"]),
 "potassium_chloride":  ("mineral", "mg",  ["אשלגן כלוריד (מג)"]),
 "magnesium":           ("mineral", "mg",  ["מגנזיום (מג)"]),
 "zinc":                ("mineral", "mg",  ["אבץ (מג)"]),
 "copper":              ("mineral", "mg",  ["נחושת (מג או מקג)"]),
 "manganese":           ("mineral", "mcg", ["מנגן (מקג)"]),
 "selenium":            ("mineral", "mcg", ["סלניום (מקג)"]),
 "iodine":              ("mineral", "mcg", ["יוד (מקג)"]),
 "fluoride":            ("mineral", "mg",  ["פלואור (מג)", "פלואוריד (מג)"]),
 "chloride":            ("mineral", "mg",  ["כלור (מג)", "כלוריד (מג)"]),
 "strontium":           ("mineral", "mg",  ["סטרונציום (מג)"]),
 "sulfates":            ("mineral", "mg",  ["גפרות (מג)"]),
 "bicarbonate":         ("mineral", "mg",  ["דו פחמות (מג)"]),
 "nitrates":            ("mineral", "mg",  ["חנקות (מג)"]),
 "silica":              ("mineral", "mg",  ["סילקה (מג)"]),
 # vitamins
 "vitamin_a":   ("vitamin", "mcg", ["Vitamin A", "ויטמין A (מקג)", "ויטמין A (מקג, יבל)", "ויטמין A שווי רטינול (מקג)"]),
 "vitamin_b1":  ("vitamin", "mg",  ["ויטמין B1 (תיאמין) (מג או מקג)"]),
 "vitamin_b2":  ("vitamin", "mg",  ["ויטמין B2 (ריבופלאבין) (מג או מקג)"]),
 "vitamin_b3":  ("vitamin", "mg",  ["ויטמין B3 (מג)", "ויטמין B3 ניקוטינאמיד שווי חומצה ניקוטינית (מג)",
                                    "ויטמין B3 (ניאצין) (מג)", "ויטמין B3(ניקוטינאמיד) (מג)"]),
 "vitamin_b5":  ("vitamin", "mg",  ["ויטמין B5 (חומצה פנטותנית) (מג)"]),
 "vitamin_b6":  ("vitamin", "mg",  ["Vitamin B6", "ויטמין B6 (מג)"]),
 "vitamin_b12": ("vitamin", "mcg", ["ויטמין B12 (מקג)"]),
 "folate":      ("vitamin", "mcg", ["חומצה פולית (מקג)"]),
 "biotin":      ("vitamin", "mcg", ["ביוטין (מקג)"]),
 "vitamin_c":   ("vitamin", "mg",  ["Vitamin C", "ויטמין C (מג)", "ויטמין C חומצה אסקורבית (מג)"]),
 "vitamin_d":   ("vitamin", "mcg", ["Vitamin D", "ויטמין D (מקג)", "ויטמין D קלציפרול (מקג)"]),
 "vitamin_e":   ("vitamin", "mg",  ["Vitamin E", "ויטמין E (מג)", "ויטמין E שווי אלפא טוקופרול (מג)"]),
 "vitamin_k":   ("vitamin", "mcg", ["ויטמין K (מקג)"]),
 # fatty acids
 "omega_3":         ("fatty_acid", "g",  ["חומצת שומן אומגה 3"]),
 "omega_6":         ("fatty_acid", "g",  ["חומצת שומן אומגה 6"]),
 "omega_9":         ("fatty_acid", "g",  ["חומצה אולאית (אומגה 9) (גרם)"]),
 "lauric":          ("fatty_acid", "g",  ["חומצה לאורית (גרם)"]),
 "dha":             ("fatty_acid", "mg", ["חומצת שומן DHA"]),
 "dha_epa":         ("fatty_acid", "mg", ["DHA + EPA"]),
 "ara":             ("fatty_acid", "mg", ["חומצת שומן ARA", "חומצת שומן AA (מג)"]),
 "alpha_linolenic": ("fatty_acid", "mg", ["חומצת שומן ALPHA לינולאית (מג)"]),
 "linoleic":        ("fatty_acid", "mg", ["חומצת שומן לינולאית (מג או גרם)"]),
 "linolenic":       ("fatty_acid", "mg", ["חומצת שומן לינולנית (מג או גרם)"]),
 # other
 "choline":      ("other", "mg",  ["כולין (מג)"]),
 "inositol":     ("other", "mg",  ["אינוסיטול (מג)"]),
 "taurine":      ("other", "mg",  ["טאורין (מג)"]),
 "carnitine":    ("other", "mg",  ["קרניטין"]),
 "nucleotides":  ("other", "mg",  ["נוקלאוטידים (מג)"]),
 "lutein":       ("other", "mcg", ["לוטאין (מקג)"]),
 "lycopene":     ("other", "mg",  ["ליקופן (מג)"]),
 "caffeine":     ("other", "mg",  ["קפאין (מג)"]),
 "galactooligosaccharides": ("other", "g", ["גלקטואוליגוסכרידים"]),
 "acesulfame_k": ("other", "mg",  ["אצסולפם k (מג)"]),
 "sucralose":    ("other", "mg",  ["סוכרלוז (מג)"]),
 "acetic_acid":  ("other", "g",   ["חומצת חומץ"]),
 "ash":          ("other", "g",   ["אפר"]),
 "moisture":     ("other", "%",   ["לחות", "רטיבות"]),
 # serving info (free-text units, never converted)
 "serving_size":           ("serving", None, ["Serving Size"]),
 "serving_size_text":      ("serving", None, ["ServingSizeFullTxt"]),
 "servings_per_container": ("serving", None, ["Servings Per Container"]),
}

def clean(s) -> str:
    """Make scraped text comparable: strip invisible bidi marks, unify quotes, collapse spaces."""
    s = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", s or "")
    s = s.replace("”", '"').replace("“", '"').replace("׳", "'").replace("’", "'")
    return re.sub(r"\s+", " ", s).strip()

LABELS = {clean(l): k for k, (_, _, ls) in SPEC.items() for l in ls}   # scraped label -> key
KIND   = {k: v[0] for k, v in SPEC.items()}                            # key -> energy/macro/...
CANON  = {k: v[1] for k, v in SPEC.items()}                            # key -> canonical unit

# ---------- 2. units ----------
# The unit field is unreliable (it contains things like "גרםn", "מל", "11", "390"),
# so every unit we accept must be a known alias. Anything else is treated as "no unit".
UNIT_ALIASES = {
    "g":    ["g", "gr", "gram", "gramo", "грамм", "ג'", "גרם", "גר`", "جرام"],
    "mg":   ["mg", "milligram", "мг.", 'מ"ג', "מג"],
    "mcg":  ["mcg", "µg", "מקג", 'מק"ג'],
    "kg":   ["kg", "קג", 'ק"ג'],
    "kcal": ["kcal", "קלוריות", 'קק"ל'],
    "ml":   ["ml", "מל", 'מ"ל', "mililitro", "миллилитр", "مل"],
    "%":    ["%"],
}
ALIAS  = {clean(a).lower(): u for u, al in UNIT_ALIASES.items() for a in al}
FACTOR = {"g": 1, "mg": 1e-3, "mcg": 1e-6, "kg": 1e3}   # to grams; only mass units are convertible

def parse_unit(raw):
    """Unit field -> (recognized unit | None, bound | None).
    Also pulls out "(מינ׳)" / "(מקס׳)" markers, which mean min / max."""
    s = "" if raw in (None, "-") else clean(str(raw))
    bound = "min" if "מינ" in s else "max" if "מקס" in s else None
    s = re.sub(r"\((?:מינ|מקס)'?\)", "", s)
    s = re.sub(r"(?<=[א-ת])n$", "", s).strip()      # stray "n" glued to Hebrew units: גרםn, מגn
    return ALIAS.get(s.lower()), bound

def label_unit(label):
    """Unit written inside the label -> (unit | None, variable?)
    "נתרן (מג)"                 -> (mg, False)  fixed unit
    "ויטמין B1 (... (מג או מקג)" -> (mg, True)   variable: the unit field decides"""
    groups = re.findall(r"\(([^()]*)\)", label)
    if not groups:
        return None, False
    toks = [ALIAS.get(t.strip().lower()) for t in re.split(r"\s+או\s+|,", groups[-1])]
    return (toks[0], " או " in groups[-1]) if toks[0] else (None, False)

# ---------- 3. basis ("size" field) ----------
# What the number is *per*. Kept in the basis so that e.g. "100g cooked" and "100g dry mix"
# are never compared as if they were the same thing.
BASIS_EXACT = {
    "למנה": "serving", "למנה מוכנה": "serving:prepared", "למנה 75 גרם": "serving:75g",
    "ליחידה": "unit", "לשקית": "bag", "לאריזה": "package", "לחטיף": "snack",
    "לכף": "tbsp", "לכפית": "tsp", "לכוס": "cup", "לכוס משקה": "drink_cup",
    "לפרוסה": "slice", "ל-2 פרוסות": "2_slices", "לקוביה": "cube", "לטבליה": "tablet",
    "לליטר": "liter", "אחוזים": "percent_dv", "כמות יומית": "daily_amount",
}
# Text after "ל-100 גרם" / "ל-100 מל": how the product was measured
QUAL = {
    "מוכן": "prepared", "תבשיל מוכן": "prepared", "מוכן בהכנה דליל": "prepared_diluted",
    "אחרי טיגון": "fried", "מוצר מבושל": "cooked", "מוצר לפני בישול": "raw",
    "מוצר לאחר סינון": "drained", "תערובת יבשה": "dry_mix",
}

def parse_basis(size):
    """Size text -> (basis, basis_raw).  "ל-100 גרם" -> "100g", "ל-100 גרם מוצר מבושל" -> "100g:cooked".
    Unrecognized qualifiers become ":other"; unrecognized sizes become "other". basis_raw keeps the original."""
    s = clean(size)
    if not s:
        return "unknown", ""
    if s in BASIS_EXACT:
        return BASIS_EXACT[s], s
    m = re.match(r'^ל[- ]?(\d+(?:\.\d+)?)\s*(גרם|מ"?ל)\s*(.*)$', s)
    if m:
        qty, u, rest = m.groups()
        base = f"{qty}{'g' if u == 'גרם' else 'ml'}"
        return (f"{base}:{QUAL.get(rest, 'other')}" if rest else base), s
    return "other", s

# ---------- 4. one row ----------
@dataclass
class NutritionRow:
    raw_label: str                 # label as scraped (cleaned), always kept
    nutrient: str | None           # canonical key, None = label not in SPEC yet
    amount: float                  # converted to `unit` when a conversion was possible
    unit: str | None
    bound: str | None              # "lt" (<), "min", "max", or None
    basis: str                     # what the amount is per: 100g, 100ml:cooked, serving, percent_dv...
    basis_raw: str                 # original size text
    flags: list = field(default_factory=list)   # unmapped | unit_missing | unit_mismatch
    is_canonical: bool = True      # False = duplicate of the same nutrient + basis in this product

def normalize_row(label, value, unit=None, size=None, less_than=False):
    """One scraped row -> NutritionRow (or None for non-numeric values)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None                # text values (e.g. ServingSizeFullTxt) stay in nutrition_raw only
    label = clean(label)
    nutrient = LABELS.get(label)
    basis, basis_raw = parse_basis(size)
    u, bound = parse_unit(unit)
    if less_than:
        bound = "lt"
    amount, out_unit, flags = float(value), u, set()

    if nutrient is None:
        flags.add("unmapped")                       # keep the row, fix SPEC later
    elif KIND[nutrient] == "serving":
        # serving info has free-text units ("cup", "teaspoon"): store as is, never convert
        out_unit = clean(str(unit)) if unit not in (None, "-", "") else None
    elif basis == "percent_dv":
        out_unit = "%"                              # the number is a % of daily value, not an amount
    else:
        canon = CANON[nutrient]
        lu, variable = label_unit(label)
        # Which unit is the number really in?
        #   fixed unit in the label  -> trust the label (the unit field is often garbage)
        #   variable ("מג או מקג") or no unit in the label -> use the unit field
        src = u if (variable or lu is None) else lu
        if src is None and canon not in FACTOR:     # kcal / tsp / %: nothing to convert, assume canonical
            src = canon
        if src is None:
            flags.add("unit_missing")               # can't tell the unit: keep the raw number, unit stays None
            out_unit = None
        else:
            if lu and not variable and u and u != lu:
                flags.add("unit_mismatch")          # field disagrees with the label, label wins
            if src in FACTOR and canon in FACTOR:
                amount *= FACTOR[src] / FACTOR[canon]   # e.g. mcg -> mg
                out_unit = canon
            else:
                out_unit = src
                if src != canon:
                    flags.add("unit_mismatch")      # e.g. a mass unit on a kcal nutrient
    return NutritionRow(label, nutrient, amount, out_unit, bound, basis, basis_raw, sorted(flags))

# ---------- 5. whole product ----------
def normalize_rows(rows):
    """All nutrition rows of one product. rows: iterable of dicts {label, value, unit, size, lt}.
    Skips exact repeats of (label, size). If two different labels map to the same nutrient and basis
    (e.g. plain and "מתוך סך השומנים" saturated fat), the first is canonical and the others are kept
    with is_canonical=False, so queries on is_canonical never double count."""
    out, seen_raw, seen_nut = [], set(), set()
    for r in rows:
        n = normalize_row(r["label"], r["value"], r.get("unit"), r.get("size"), r.get("lt", False))
        if n is None or (n.raw_label, n.basis_raw) in seen_raw:
            continue
        seen_raw.add((n.raw_label, n.basis_raw))
        if n.nutrient:
            if (n.nutrient, n.basis) in seen_nut:
                n.is_canonical = False
            seen_nut.add((n.nutrient, n.basis))
        out.append(n)
    validate(out)
    return out


# ---------- 6. validation ----------
VALIDATION_FLAGS = {"out_of_range", "macro_sum_high", "child_gt_parent", "energy_mismatch"}

def validate(rows):
    """Adds validation flags in place. Safe to call more than once: old validation flags are cleared first."""
    for r in rows:
        r.flags = [f for f in r.flags if f not in VALIDATION_FLAGS]

    by_basis = {}
    for r in rows:
        if r.nutrient and r.is_canonical:
            by_basis.setdefault(r.basis, {})[r.nutrient] = r

    for basis, n in by_basis.items():
        if not re.match(r"^\d+(\.\d+)?(g|ml)(:|$)", basis):
            continue                      # serving, percent_dv, unit...: can't compare to 100

        def get(k):
            return n[k].amount if k in n and n[k].unit == "g" else None

        def flag(keys, f):
            for k in keys:
                if k in n and f not in n[k].flags:
                    n[k].flags.append(f)

        for k in ("total_fat", "total_carbs", "protein", "sugars", "dietary_fiber", "saturated_fat"):
            if (v := get(k)) is not None and v > 100:
                flag([k], "out_of_range")

        p, f_, c = get("protein"), get("total_fat"), get("total_carbs")
        if None not in (p, f_, c) and p + f_ + c > 105:
            flag(["protein", "total_fat", "total_carbs"], "macro_sum_high")

        if (s := get("sugars")) is not None and c is not None and s > c + 0.5:
            flag(["sugars", "total_carbs"], "child_gt_parent")

        kcal = n["calories"].amount if "calories" in n else None
        if None not in (p, f_, c, kcal) and kcal > 0:
            if abs((4*p + 4*c + 9*f_) - kcal) / kcal > 0.25:
                flag(["calories"], "energy_mismatch")

    for r in rows:
        r.flags = sorted(r.flags)