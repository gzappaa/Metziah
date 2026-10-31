from bs4 import BeautifulSoup
from scrapers.product_pages.type_1 import (
    MARKER,
    _parse_info,
    _parse_nutrients,
    parse,
)


def test_marker():
    assert MARKER == ".productContainer"


def test_parse_returns_none_without_product_container():
    assert parse("<html><body>No product</body></html>") is None


def test_parse_basic_product():
    html = """
    <html>
      <body>
        <img itemprop="image" src="/milk.jpg" alt="Fresh Milk">
        <ul class="productContainer">
          <li>
            <div class="productCode">
              <span class="text">7291234567890</span>
            </div>
            <div class="title"><span class="mainInfo">Brand</span></div>
            <div class="info"><div>Example Brand</div></div>
          </li>
        </ul>
      </body>
    </html>
    """

    result = parse(html)

    assert result["page_code"] == "7291234567890"
    assert result["name"] == "Fresh Milk"
    assert result["images"] == ["/milk.jpg"]
    assert result["sections"] == [
        {"title": "Brand", "content": "Example Brand"}
    ]


def test_parse_missing_optional_fields():
    html = """
    <ul class="productContainer">
      <li>
        <div class="title"><span class="mainInfo">Description</span></div>
        <div class="info">Simple product</div>
      </li>
    </ul>
    """

    result = parse(html)

    assert result["page_code"] is None
    assert result["name"] is None
    assert result["images"] == []
    assert result["sections"] == [
        {"title": "Description", "content": "Simple product"}
    ]
    assert "product_details" not in result


def test_parse_removes_duplicate_images():
    html = """
    <img itemprop="image" src="/milk.jpg" alt="Milk">
    <img itemprop="image" src="/milk.jpg" alt="Milk">
    <ul class="productContainer"></ul>
    """

    result = parse(html)

    assert result["images"] == ["/milk.jpg"]


def test_parse_data_list_fields():
    html = """
    <div class="info">
      <ul class="dataList">
        <li class="box">
          <span class="name">Brand:</span>
          <span class="text">Example</span>
        </li>
        <li class="box">
          <span class="name">Weight:</span>
          <span class="text">500 g</span>
        </li>
      </ul>
    </div>
    """

    assert _parse_info(BeautifulSoup(
        html, "html.parser"
    ).select_one(".info")) == {
        "Brand": ["Example"],
        "Weight": ["500 g"],
    }


def test_parse_data_list_preserves_repeated_labels():
    html = """
    <div class="info">
      <ul class="dataList">
        <li class="box">
          <span class="name">Kashrut:</span>
          <span class="text">Certification A</span>
        </li>
        <li class="box">
          <span class="name">Kashrut:</span>
          <span class="text">Certification B</span>
        </li>
      </ul>
    </div>
    """

    

    info = BeautifulSoup(html, "html.parser").select_one(".info")

    assert _parse_info(info) == {
        "Kashrut": ["Certification A", "Certification B"]
    }


def test_parse_markings_are_unique():
    

    html = """
    <div class="info">
      <div class="markingItem"><span class="text">Vegan</span></div>
      <div class="markingItem"><span class="text">Kosher</span></div>
      <div class="markingItem"><span class="text">Vegan</span></div>
    </div>
    """

    info = BeautifulSoup(html, "html.parser").select_one(".info")

    assert _parse_info(info) == ["Vegan", "Kosher"]


def test_parse_features_list_splits_items():
    

    html = """
    <div class="info">
      <div class="featuresList">Milk, Water<br>Salt</div>
    </div>
    """

    info = BeautifulSoup(html, "html.parser").select_one(".info")

    assert _parse_info(info) == ["Milk", "Water", "Salt"]




def test_parse_components_text_collapses_whitespace():
    

    html = """
    <div class="info">
      <div class="componentsText">Milk   and
      water</div>
    </div>
    """

    info = BeautifulSoup(html, "html.parser").select_one(".info")

    assert _parse_info(info) == "Milk and water"

def test_parse_nutrition_section():
    html = """
    <ul class="productContainer">
      <li>
        <div class="title">
          <span class="mainInfo">Nutrition</span>
          <span class="subInfo">Per 100g</span>
        </div>
        <div class="info">
          <div class="nutritionList">
            <div class="nutritionItem">
              <span class="number" title="12"></span>
              <span class="name">g</span>
              <span class="text">Protein</span>
            </div>
          </div>
        </div>
      </li>
    </ul>
    """

    result = parse(html)

    assert result["sections"] == [
        {
            "title": "Nutrition",
            "content": {
                "for": "Per 100g",
                "nutrients": {
                    "Protein": {"value": 12, "unit": "g"}
                },
            },
        }
    ]

def test_parse_nutrients_converts_numeric_values():
    

    html = """
    <div>
      <div class="nutritionItem">
        <span class="number" title="12"></span>
        <span class="name">g</span>
        <span class="text">Protein</span>
      </div>
      <div class="nutritionItem">
        <span class="number" title="2.5"></span>
        <span class="name">g</span>
        <span class="text">Fat</span>
      </div>
    </div>
    """

    info = BeautifulSoup(html, "html.parser")

    assert _parse_nutrients(info) == {
        "Protein": {"value": 12, "unit": "g"},
        "Fat": {"value": 2.5, "unit": "g"},
    }


def test_parse_nutrients_skips_incomplete_items():
    

    html = """
    <div>
      <div class="nutritionItem">
        <span class="number" title="12"></span>
        <span class="name">g</span>
      </div>
      <div class="nutritionItem">
        <span class="number" title="5"></span>
        <span class="name">g</span>
        <span class="text">Salt</span>
      </div>
    </div>
    """

    info = BeautifulSoup(html, "html.parser")

    assert _parse_nutrients(info) == {
        "Salt": {"value": 5, "unit": "g"}
    }


def test_parse_product_details():
    html = """
    <html>
      <body>
        <div class="productDetails">
          <ul class="productShip">
            <li>Home delivery</li>
            <li>Home delivery</li>
          </ul>
          <ul class="productVariants">
            <li>Small</li>
            <li>Large</li>
          </ul>
        </div>
        <ul class="productContainer"></ul>
      </body>
    </html>
    """

    result = parse(html)

    assert result["product_details"] == {
        "shipping": ["Home delivery"],
        "variants": ["Small", "Large"],
    }

def test_parse_categories():
    html = """
    <section class="breadcrumbSection">
      <ol itemtype="https://schema.org/BreadcrumbList">
        <li>
          <span itemprop="item">
            <span itemprop="name">Food</span>
          </span>
        </li>
        <li>
          <span itemprop="item">
            <span itemprop="name">Dairy</span>
          </span>
        </li>
      </ol>
    </section>
    <ul class="productContainer"></ul>
    """

    result = parse(html)

    assert result["categories"] == [
        {"1": "Food"},
        {"1": "Dairy"},
    ]