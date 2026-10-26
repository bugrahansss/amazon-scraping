"""Scrape Amazon product data, all variations and seller offers with Python."""

from .client import AmazonScraper, ScrapeError, product_url
from .parser import (
    OFFER_FIELDS,
    PRODUCT_FIELDS,
    asin_from_url,
    parse_offers,
    parse_product,
    parse_variations,
    selected_options,
)

__all__ = [
    "AmazonScraper",
    "OFFER_FIELDS",
    "PRODUCT_FIELDS",
    "ScrapeError",
    "asin_from_url",
    "parse_offers",
    "parse_product",
    "parse_variations",
    "product_url",
    "selected_options",
]

__version__ = "0.1.0"
