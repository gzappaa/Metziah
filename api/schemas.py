"""Pydantic schemas for the shopper-facing API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Product(BaseModel):
    item_code: str
    name: str | None = None
    manufacturer: str | None = None
    manufacturer_country: str | None = None
    item_type: int | None = None
    name_he: str | None = None
    name_en: str | None = None
    brand_he: str | None = None
    brand_en: str | None = None
    family_he: str | None = None
    family_en: str | None = None
    department_he: str | None = None
    category_he: str | None = None
    subcategory_he: str | None = None
    description_he: str | None = None
    description_en: str | None = None
    ingredients_he: str | None = None
    ingredients_en: str | None = None


class Price(BaseModel):
    item_code: str
    chain_id: str
    store_id: str
    chain_name_he: str
    chain_name_en: str
    brands: list[str] = Field(default_factory=list)
    shopper_brand: str | None = None
    store_name: str | None = None
    address: str | None = None
    city: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    price: Decimal | None = None
    unit_price: Decimal | None = None
    quantity: Decimal | None = None
    unit_qty: str | None = None
    unit_measure: str | None = None
    weighted: bool | None = None
    package_quantity: int | None = None
    allow_discount: bool | None = None
    status: str | None = None
    price_update_time: datetime | None = None
    last_sale_datetime: datetime | None = None
    updated_at: datetime | None = None


class Promotion(BaseModel):
    item_code: str
    chain_id: str
    promotion_id: str
    store_id: str
    chain_name_he: str
    chain_name_en: str
    brands: list[str] = Field(default_factory=list)
    shopper_brand: str | None = None
    store_name: str | None = None
    address: str | None = None
    city: str | None = None
    description: str | None = None
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None
    club_id: str | None = None
    additional_is_coupon: bool | None = None
    allow_multiple_discounts: bool | None = None
    additional_restrictions: str | None = None
    remarks: str | None = None
    group_id: str
    min_purchase_amount: Decimal | None = None
    discount_type: str | None = None
    min_qty: Decimal | None = None
    max_qty: Decimal | None = None
    discount_rate: Decimal | None = None
    discounted_price: Decimal | None = None
    discounted_price_per_mida: Decimal | None = None
    is_weighted: bool | None = None


class Nutrition(BaseModel):
    source: str
    raw_label: str
    nutrient: str | None = None
    amount: Decimal | None = None
    unit: str | None = None
    bound: str | None = None
    basis: str
    basis_raw: str
    flags: list[str] = Field(default_factory=list)
    is_canonical: bool


class ProductEnrichment(Product):
    local_name: str | None = None
    source: str
    source_file: str | None = None
    category_path_he: list[str] | None = None
    category_path_en: list[str] | None = None
    nutrition_raw: Any = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    nutrition: list[Nutrition] = Field(default_factory=list)


class ProductDetail(BaseModel):
    product: Product
    prices: list[Price] = Field(default_factory=list)
    promotions: list[Promotion] = Field(default_factory=list)
    enrichment: ProductEnrichment | None = None


class SearchResult(BaseModel):
    items: list[Product]
    total: int
    limit: int
    offset: int

class StoreProductCategory(BaseModel):
    id: int
    name: str
    sort_order: int


class StoreProductSubcategory(BaseModel):
    id: int
    category_id: int
    category: str
    name: str
    sort_order: int


class StoreProduct(BaseModel):
    chain_id: str
    store_id: str
    item_code: str
    product_name: str
    chain_name_he: str
    chain_name_en: str
    brands: list[str] = Field(default_factory=list)
    shopper_brand: str | None = None
    store_name: str | None = None
    address: str | None = None
    city: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    category_id: int | None = None
    category: str | None = None
    subcategory_id: int | None = None
    subcategory: str | None = None


class StoreProductSearchResult(BaseModel):
    items: list[StoreProduct]
    total: int
    limit: int
    offset: int






class CatalogStats(BaseModel):
    total_stores: int
    total_brands: int
    total_fresh_products: int


class PackagedCategory(BaseModel):
    name: str
    count: int
    subcategories: list[str] = Field(default_factory=list)

    @field_validator("subcategories", mode="before")
    @classmethod
    def _none_to_empty(cls, value):
        return value or []


class ProductSearchHit(BaseModel):
    identifier: str
    name: str
    brand: str | None = None
    category: str = ""
    min_price: Decimal | None = None
    store_count: int = 0


class ProductSearchPage(BaseModel):
    items: list[ProductSearchHit]
    total: int
    limit: int
    offset: int


class FreshCategory(StoreProductCategory):
    count: int = 0


class FreshSubcategory(StoreProductSubcategory):
    count: int = 0


class FreshProductSummary(BaseModel):
    product_name: str
    store_count: int
    lowest_price: Decimal | None = None
    cheapest_promotion: Decimal | None = None


class FreshProductPage(BaseModel):
    items: list[FreshProductSummary]
    total: int
    limit: int
    offset: int


class FreshPromotion(BaseModel):
    promotion_id: str
    description: str | None = None
    discounted_price: Decimal | None = None
    discount_rate: Decimal | None = None
    min_qty: Decimal | None = None
    max_qty: Decimal | None = None
    group_id: str | None = None
    club_id: str | None = None
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None


class FreshStorePromotion(FreshPromotion):
    store_name: str | None = None
    chain_name_he: str | None = None


class FreshStorePrice(BaseModel):
    chain_id: str
    store_id: str
    item_code: str
    chain_name_he: str
    chain_name_en: str
    brands: list[str] = Field(default_factory=list)
    shopper_brand: str | None = None
    store_name: str | None = None
    address: str | None = None
    city: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    price: Decimal | None = None
    unit_price: Decimal | None = None
    promotions: list[FreshPromotion] = Field(default_factory=list)


class FreshProductDetail(BaseModel):
    product_name: str
    category_id: int | None = None
    category: str | None = None
    subcategory_id: int | None = None
    subcategory: str | None = None
    lowest_price: Decimal | None = None
    lowest_promotion: FreshStorePromotion | None = None
    stores: list[FreshStorePrice]
    promotions: list[FreshStorePromotion] = Field(default_factory=list)