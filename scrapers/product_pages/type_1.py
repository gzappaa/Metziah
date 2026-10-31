"""
Type 1: server-rendered product page.

Product content is a <ul class="productContainer"> whose <li> children
are sections, each with a .title and an .info block.
"""

from bs4 import BeautifulSoup

from scrapers.product_pages.common import add_field, clean, split_list, unique


MARKER = ".productContainer"



def _parse_nutrients(info):
    nutrients = {}

    for item in info.select(".nutritionItem"):
        number = item.select_one(".number")
        unit = item.select_one(".name")
        name = item.select_one(".text")
        if not number or not unit or not name:
            continue

        value = number.get("title")
        nutrient_name = clean(name.get_text(" "))
        if not value or not nutrient_name:
            continue

        try:
            numeric = float(value)
            value = int(numeric) if numeric.is_integer() else numeric
        except ValueError:
            pass

        nutrients[nutrient_name] = {
            "value": value,
            "unit": clean(unit.get_text(" ")),
        }

    return nutrients


def _parse_info(info):
    """Parse one section's .info block by what it contains."""
    if info.select_one("ul.dataList"):
        fields = {}
        for box in info.select("ul.dataList .box"):
            name = box.select_one(".name")
            text = box.select_one(".text")
            if name and text:
                add_field(
                    fields,
                    clean(name.get_text(" ")).rstrip(":").strip(),
                    clean(text.get_text(" ")),
                )
        return fields

    if info.select_one(".markingItem"):
        return unique(
            clean(el.get_text(" ")) for el in info.select(".markingItem .text")
        )

    el = info.select_one(".featuresList, .alergiesProperties")
    if el:
        return split_list(el.get_text("\n"))

    el = info.select_one(".componentsText")
    if el:
        return clean(el.get_text(" "))

    return clean(info.get_text(" "))


def _parse_categories(soup):
    """Parse the product breadcrumb into an ordered list of category names."""
    breadcrumb = soup.select_one(
        'section.breadcrumbSection ol[itemtype="https://schema.org/BreadcrumbList"]'
    )
    if not breadcrumb:
        return []

    categories = []

    for li in breadcrumb.find_all("li", recursive=False):
        name_el = li.select_one(
            ':scope > [itemprop="item"] > [itemprop="name"]'
        )
        if not name_el:
            continue

        name = clean(name_el.get_text(" "))
        if name:
            categories.append({"1": name})

    return categories


def parse(html):
    """Return a dict with page_code, name, images, categories + type-specific fields."""
    soup = BeautifulSoup(html, "html.parser")

    container = soup.select_one(MARKER)
    if not container:
        return None

    code_el = container.select_one(".productCode .text")
    page_code = clean(code_el.get_text()) if code_el else None

    image_els = soup.select('img[itemprop="image"]')
    images = unique(img.get("src") for img in image_els)
    name = next((img.get("alt") for img in image_els if img.get("alt")), None)

    categories = _parse_categories(soup)

    sections = []
    for li in container.find_all("li", recursive=False):
        title_el = li.select_one(".title .mainInfo")
        info = li.select_one(".info")
        if not title_el or not info:
            continue

        if info.select_one(".nutritionList"):
            sub = li.select_one(".title .subInfo")
            content = {
                "for": clean(sub.get_text(" ")) if sub else None,
                "nutrients": _parse_nutrients(info),
            }
            if not content["nutrients"]:
                continue
        else:
            content = _parse_info(info)

        if content:
            sections.append(
                {
                    "title": clean(title_el.get_text(" ")),
                    "content": content,
                }
            )

    product_details = {}
    details_el = soup.select_one("div.productDetails")
    if details_el:
        shipping = unique(
            clean(li.get_text(" ")) for li in details_el.select("ul.productShip li")
        )
        variants = unique(
            clean(li.get_text(" ")) for li in details_el.select("ul.productVariants li")
        )
        if shipping:
            product_details["shipping"] = shipping
        if variants:
            product_details["variants"] = variants

    result = {
        "page_code": page_code,
        "name": name,
        "images": images,
        "categories": categories,
        "sections": sections,
    }

    if product_details:
        result["product_details"] = product_details

    return result