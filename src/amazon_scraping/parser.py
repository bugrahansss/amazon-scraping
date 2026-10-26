"""Parse Amazon product pages, variation menus and seller offer panels.

The selectors follow the Scrape.do Amazon scraping guide (re-tested October 2026):

* Product page: ``#productTitle``, ``.a-price-whole`` + ``.a-price-fraction``,
  ``#outOfStockBuyBox_feature_div``, ``img#landingImage``, ``.AverageCustomerReviews``.
* Variations: every ``div#inline-twister-row-*`` is one dimension (color, size,
  style ...); each ``li[data-asin]`` inside it is an option with its own ASIN.
* Seller offers: the ``/gp/product/ajax/aodAjaxMain/?asin=`` panel, one
  ``div#aod-offer-soldBy`` per offer, with a sticky copy of the Buy Box offer
  inside ``#aod-sticky-pinned-offer`` that is skipped.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

ASIN_RE = re.compile(r"/(?:dp|gp/product|product-reviews)/([A-Z0-9]{10})(?:[/?]|$)")
TWISTER_RE = re.compile(r"inline-twister-row-.*")
SELECTED_RE = re.compile(r".*a-button-selected.*")

PRODUCT_FIELDS = ["asin", "name", "price", "currency", "in_stock", "rating", "image", "url"]
OFFER_FIELDS = ["asin", "price", "condition", "seller", "seller_rating", "rating_count", "positive", "ships_from"]

#: Preferred order of variation dimensions in the output.
DIMENSION_PRIORITY = ["color", "size", "style", "pattern", "material", "fit"]


def _soup(html_or_soup: Any) -> BeautifulSoup:
    return html_or_soup if isinstance(html_or_soup, BeautifulSoup) else BeautifulSoup(html_or_soup or "", "html.parser")


def _text(element, default: str = "") -> str:
    return " ".join(element.get_text().split()) if element is not None else default


def asin_from_url(url: str) -> Optional[str]:
    """``https://www.amazon.com/Some-Name/dp/B0BLRJ4R8F/`` -> ``B0BLRJ4R8F``."""
    if re.fullmatch(r"[A-Z0-9]{10}", (url or "").strip()):
        return url.strip()
    match = ASIN_RE.search(url or "")
    return match.group(1) if match else None


def parse_price(soup: BeautifulSoup) -> Optional[float]:
    """The buy box price, built from ``.a-price-whole`` and ``.a-price-fraction``."""
    whole = soup.find(class_="a-price-whole")
    if whole is None:
        return None
    fraction = soup.find(class_="a-price-fraction")
    digits = re.sub(r"[^\d]", "", whole.get_text())
    cents = re.sub(r"[^\d]", "", fraction.get_text()) if fraction is not None else "00"
    try:
        return float(f"{digits}.{cents or '00'}")
    except ValueError:
        return None


def is_out_of_stock(soup: BeautifulSoup) -> bool:
    return soup.find("div", id="outOfStockBuyBox_feature_div") is not None


def parse_product(html_or_soup: Any, url: str = "") -> Dict[str, Any]:
    """Name, price, stock, rating and main image of one product page.

    Raises ``ValueError`` when the page has no ``#productTitle``, which usually
    means a CAPTCHA page or a non-product page.
    """
    soup = _soup(html_or_soup)
    title = soup.find(id="productTitle")
    if title is None:
        raise ValueError("No product title found. Expected an Amazon product page (#productTitle).")
    out_of_stock = is_out_of_stock(soup)
    rating_el = soup.find(class_="AverageCustomerReviews")
    rating = None
    if rating_el is not None:
        match = re.search(r"(\d+(?:\.\d+)?) out of", rating_el.get_text())
        rating = float(match.group(1)) if match else None
    image = soup.find("img", id="landingImage")
    return {
        "asin": asin_from_url(url) or "",
        "name": _text(title),
        "price": None if out_of_stock else parse_price(soup),
        "currency": "USD",
        "in_stock": not out_of_stock,
        "rating": rating,
        "image": image.get("src", "") if image is not None else "",
        "url": url,
    }


def _option_name(option) -> str:
    swatch = option.find("span", class_="swatch-title-text-display")
    if swatch is not None:
        return _text(swatch)
    img = option.find("img")
    if img is not None and img.get("alt"):
        return img["alt"].strip()
    button = option.find("span", class_="a-button-text")
    if button is not None and _text(button) and _text(button) != "Select":
        return _text(button)
    return "Unknown"


def _dimension_name(row) -> str:
    return row.get("id", "").replace("inline-twister-row-", "").replace("_name", "")


def parse_variations(html_or_soup: Any) -> Dict[str, List[Dict[str, str]]]:
    """Every variation dimension on the page and its available options.

    ``{"color": [{"name": "Blue", "asin": "B0..."}], "size": [...]}``. Options
    marked ``data-initiallyUnavailable="true"`` are skipped.
    """
    soup = _soup(html_or_soup)
    dimensions: Dict[str, List[Dict[str, str]]] = {}
    for row in soup.find_all("div", id=TWISTER_RE):
        options = []
        for option in row.find_all("li", attrs={"data-asin": True}):
            asin = option.get("data-asin")
            if asin and option.get("data-initiallyunavailable", option.get("data-initiallyUnavailable")) != "true":
                options.append({"name": _option_name(option), "asin": asin})
        if options:
            dimensions[_dimension_name(row)] = options
    return dimensions


def order_dimensions(names) -> List[str]:
    """Sort dimensions so color comes before size, size before style, and so on."""
    return sorted(
        names,
        key=lambda n: DIMENSION_PRIORITY.index(n.lower()) if n.lower() in DIMENSION_PRIORITY else len(DIMENSION_PRIORITY),
    )


def selected_options(html_or_soup: Any, dim_names, asin: str = "") -> Dict[str, str]:
    """The option shown as selected for each dimension on a variation page."""
    soup = _soup(html_or_soup)
    selections: Dict[str, str] = {}
    for dim in dim_names:
        for row_id in (f"inline-twister-row-{dim}_name", f"inline-twister-row-{dim}"):
            row = soup.find("div", id=row_id)
            if row is None:
                continue
            selected = row.find("span", class_=SELECTED_RE)
            if selected is not None:
                name = _option_name(selected)
                selections[dim] = name if name != "Unknown" else "N/A"
            else:
                option = row.find("li", attrs={"data-asin": asin}) if asin else None
                selections[dim] = _option_name(option) if option is not None else "N/A"
            break
    return selections


def _find(pattern: str, text: str) -> str:
    match = re.search(pattern, text or "")
    return match.group(1) if match else ""


def parse_offers(html_or_soup: Any, asin: str = "") -> List[Dict[str, Any]]:
    """Every seller offer in an ``aodAjaxMain`` panel (Buy Box sticky copy skipped)."""
    soup = _soup(html_or_soup)
    offers = []
    for sold_by in soup.find_all("div", id="aod-offer-soldBy"):
        if sold_by.find_parent(id="aod-sticky-pinned-offer"):
            continue
        container = sold_by.parent
        while container is not None and container.find("span", class_="a-price-whole") is None:
            container = container.parent
        if container is None:
            continue
        seller_link = sold_by.find("a", href=lambda h: h and "/gp/aag/main" in h)
        rating_div = sold_by.find("div", id="aod-offer-seller-rating")
        rating_text = _text(rating_div.find("span", class_="a-icon-alt")) if rating_div is not None else ""
        count_el = rating_div.find("span", id=lambda i: i and "seller-rating-count" in i) if rating_div is not None else None
        count_text = _text(count_el)
        ships_div = container.find("div", id="aod-offer-shipsFrom")
        positive = _find(r"(\d+)%\s*positive", count_text)
        rating_count = _find(r"\((\d[\d,]*)\s*ratings\)", count_text)
        seller_rating = _find(r"(\d+\.?\d*) out of 5", rating_text)
        offers.append(
            {
                "asin": asin,
                "price": parse_price(container),
                "condition": _text(container.find("div", id="aod-offer-heading"), "New"),
                "seller": _text(seller_link) if seller_link is not None else "Amazon.com",
                "seller_rating": float(seller_rating) if seller_rating else None,
                "rating_count": int(rating_count.replace(",", "")) if rating_count else None,
                "positive": f"{positive}%" if positive else "",
                "ships_from": _text(ships_div.find("span", class_="a-color-base")) if ships_div is not None else "",
            }
        )
    return offers
