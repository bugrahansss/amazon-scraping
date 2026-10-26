"""Fetch Amazon pages through the Scrape.do API.

Amazon sits behind AWS WAF, which checks the IP, headers and recent activity
of every request. Product pages are fetched through Scrape.do's Amazon plugin
(``/plugin/amazon/?url=...&output=html``) with a US ZIP code, which returns the
full page without render or super proxies. Seller offers come from Amazon's
``aodAjaxMain`` panel through the standard API. If you would rather skip HTML
parsing, :meth:`AmazonScraper.pdp` and :meth:`AmazonScraper.offer_listing`
call the structured JSON endpoints of the Amazon Scraper API.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, Optional

import requests

from .parser import asin_from_url, order_dimensions, parse_offers, parse_product, parse_variations, selected_options

API_URL = "https://api.scrape.do/"
PLUGIN_URL = "https://api.scrape.do/plugin/amazon/"
TOKEN_ENV = "SCRAPEDO_TOKEN"
AMAZON = "https://www.amazon.com"


class ScrapeError(RuntimeError):
    """Raised when a page cannot be fetched."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def product_url(asin_or_url: str) -> str:
    """Accept an ASIN or a product URL and return a clean ``/dp/<ASIN>/`` URL."""
    asin = asin_from_url(asin_or_url)
    if not asin:
        raise ValueError(f"No ASIN found in {asin_or_url!r}")
    return f"{AMAZON}/dp/{asin}/"


class AmazonScraper:
    """Scrape Amazon product pages, all variations of a product, and seller offers.

    >>> scraper = AmazonScraper(token="YOUR_SCRAPEDO_TOKEN")
    >>> scraper.get_product("B0BLRJ4R8F")["price"]
    >>> scraper.get_offers("B0BN969PGL")
    """

    def __init__(
        self,
        token: Optional[str] = None,
        geocode: str = "us",
        zipcode: Optional[str] = "10001",
        timeout: float = 90.0,
        retries: int = 2,
        session: Optional[requests.Session] = None,
    ):
        self.token = token or os.environ.get(TOKEN_ENV, "")
        if not self.token:
            raise ValueError(f"A Scrape.do API token is required. Pass token=... or set {TOKEN_ENV}.")
        self.geocode = geocode
        self.zipcode = zipcode
        self.timeout = timeout
        self.retries = max(0, retries)
        self.session = session or requests.Session()

    # ------------------------------------------------------------------ transport

    def _get(self, url: str, params: Dict[str, Any]) -> requests.Response:
        params = {"token": self.token, **{k: v for k, v in params.items() if v not in (None, "")}}
        last_error: Optional[ScrapeError] = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = ScrapeError(f"Request failed: {exc}")
            else:
                if response.status_code == 200:
                    return response
                last_error = ScrapeError(f"Request failed with status {response.status_code}", response.status_code)
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    break
            if attempt < self.retries:
                time.sleep(2 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def fetch_product_html(self, asin_or_url: str) -> str:
        """Raw HTML of a product page via the Amazon plugin (no render, no super proxy)."""
        url = asin_or_url if asin_or_url.startswith("http") else product_url(asin_or_url)
        return self._get(PLUGIN_URL, {"url": url, "geocode": self.geocode, "zipcode": self.zipcode, "output": "html"}).text

    # ------------------------------------------------------------------ HTML scrapers

    def get_product(self, asin_or_url: str) -> Dict[str, Any]:
        """Name, price, stock, rating and image of one product."""
        url = asin_or_url if asin_or_url.startswith("http") else product_url(asin_or_url)
        return parse_product(self.fetch_product_html(url), url=url)

    def get_variations(
        self,
        asin_or_url: str,
        max_pages: Optional[int] = None,
        on_row: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> List[Dict[str, Any]]:
        """Every color/size/style combination of a product, one row per variation ASIN.

        Walks the option tree depth first: for each option of the current
        dimension it loads that option's own page (available options can change
        with the selection) and records the selected options and the price shown
        there. Costs one request per variation page; ``max_pages`` caps it.
        """
        base = asin_or_url if asin_or_url.startswith("http") else product_url(asin_or_url)
        root = asin_from_url(base)
        first = self.fetch_product_html(base)
        dim_names = order_dimensions(parse_variations(first).keys())
        pages = {root: first}
        requests_made = [1]
        rows: List[Dict[str, Any]] = []
        done = set()

        def page_for(asin: str) -> Optional[str]:
            if asin not in pages:
                if max_pages and requests_made[0] >= max_pages:
                    return None
                pages[asin] = self.fetch_product_html(f"{AMAZON}/dp/{asin}/?th=1&psc=1")
                requests_made[0] += 1
            return pages[asin]

        def walk(asin: str, dim_index: int) -> None:
            if asin in done:
                return
            html = page_for(asin)
            if html is None:
                return
            dims = parse_variations(html)
            if dim_index >= len(dim_names) or not dims:
                done.add(asin)
                try:
                    product = parse_product(html, url=f"{AMAZON}/dp/{asin}/")
                except ValueError:
                    return
                row = {"asin": asin, "name": product["name"]}
                row.update(selected_options(html, dim_names, asin))
                row["price"] = product["price"]
                row["in_stock"] = product["in_stock"]
                rows.append(row)
                if on_row:
                    on_row(row)
                return
            current = dim_names[dim_index]
            if current in dims:
                for option in dims[current]:
                    walk(option["asin"], dim_index + 1)
            else:
                walk(asin, dim_index + 1)

        walk(root, 0)
        return rows

    def get_offers(self, asin_or_url: str) -> List[Dict[str, Any]]:
        """All seller offers from the ``aodAjaxMain`` panel (price, condition, seller, rating, ships from).

        The count varies by ASIN and delivery location; one offer or none is a valid result.
        """
        asin = asin_from_url(asin_or_url)
        if not asin:
            raise ValueError(f"No ASIN found in {asin_or_url!r}")
        target = f"{AMAZON}/gp/product/ajax/aodAjaxMain/?asin={asin}"
        html = self._get(API_URL, {"url": target, "geoCode": self.geocode}).text
        return parse_offers(html, asin)

    # ------------------------------------------------------------------ structured JSON endpoints

    def pdp(self, asin_or_url: str) -> Dict[str, Any]:
        """Product details as JSON from the Amazon Scraper API (1 credit per successful request)."""
        asin = asin_from_url(asin_or_url)
        return self._get(PLUGIN_URL + "pdp", {"asin": asin, "geocode": self.geocode, "zipcode": self.zipcode}).json()

    def offer_listing(self, asin_or_url: str) -> Dict[str, Any]:
        """All seller offers as JSON from the Amazon Scraper API."""
        asin = asin_from_url(asin_or_url)
        return self._get(PLUGIN_URL + "offer-listing", {"asin": asin, "geocode": self.geocode, "zipcode": self.zipcode}).json()
