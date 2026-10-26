# amazon-scraping

[![PyPI](https://img.shields.io/pypi/v/amazon-scraping)](https://pypi.org/project/amazon-scraping/)
[![Python](https://img.shields.io/pypi/pyversions/amazon-scraping)](https://pypi.org/project/amazon-scraping/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A Python scraper for [Amazon](https://www.amazon.com) product data: name, price, stock, rating and image from product pages, **every color/size/model variation** of a product with its own price, and **all seller offers** with condition, seller rating and fulfillment. Output as Python dicts, JSON or CSV.

```bash
pip install amazon-scraping
```

## Why a plain request fails

Amazon sits behind AWS WAF. Every request is scored on its IP, headers and recent activity, and `requests` or a headless browser on a datacenter IP gets a CAPTCHA page or a block within a few calls. Building around it means maintaining a pool of residential proxies, browser-like headers and fingerprints.

This package fetches pages through the [Scrape.do](https://scrape.do/?utm_source=github&utm_medium=readme&utm_campaign=amazon-scraping) API instead:

- **Product pages** go through the Amazon plugin (`/plugin/amazon/?url=...&geocode=us&zipcode=10001&output=html`), which returns the full page with US pricing for the ZIP code you set. No `render=true`, no `super=true`: the plain call came back 200 in under 4 seconds in October 2026, and it is cheaper.
- **Seller offers** come from Amazon's own `aodAjaxMain` panel through the standard API.
- **Structured JSON**, if you'd rather skip HTML: `pdp()` and `offer_listing()` call the Amazon Scraper API endpoints.

You need a Scrape.do API token; the free plan includes 1,000 credits a month.

## Quick start

```python
from amazon_scraping import AmazonScraper

scraper = AmazonScraper(token="YOUR_SCRAPEDO_TOKEN")  # or set SCRAPEDO_TOKEN; zipcode="10001" by default

product = scraper.get_product("B0BLRJ4R8F")          # an ASIN or a product URL
print(product["name"], product["price"], product["rating"], product["in_stock"])

variations = scraper.get_variations("https://www.amazon.com/Apple-iPhone-Plus-128GB-Blue/dp/B0CG84XR6N/")
for v in variations:
    print(v["asin"], v.get("color"), v.get("size"), v["price"])

offers = scraper.get_offers("B0BN969PGL")
for o in offers:
    print(o["seller"], o["price"], o["condition"], o["seller_rating"], o["ships_from"])
```

### Command line

```bash
export SCRAPEDO_TOKEN=your_token

# products, one ASIN or URL per line, CSV
amazon-scraping product --input asins.txt --format csv --output products.csv

# every variation of one product
amazon-scraping variations "https://www.amazon.com/dp/B0CG84XR6N/" -f csv -o amazon_variations.csv

# all seller offers
amazon-scraping offers B0BN969PGL -f csv -o amazon_seller_offers.csv

# structured JSON from the Amazon Scraper API
amazon-scraping pdp B0BLRJ4R8F
```

### Output

Product (from the fictional test page in [`tests/fixtures`](tests/fixtures/product_in_stock.html)):

```json
{
  "asin": "B0BLRJ4R8F",
  "name": "Example Basics Portable Laptop Stand, Height Adjustable, Silver",
  "price": 1029.87,
  "currency": "USD",
  "in_stock": true,
  "rating": 4.6,
  "image": "https://m.media-amazon.com/images/I/example-stand.jpg",
  "url": "https://www.amazon.com/Some-Stand/dp/B0BLRJ4R8F/"
}
```

Variation rows carry one column per dimension the product has (`color`, `size`, `style`, `service_provider`, ...), so the CSV always matches the product's own variation model.

## How it works

**Product page.** Title from `#productTitle`, price from `.a-price-whole` + `.a-price-fraction` (turned into a float, so `1,029.` + `87` becomes `1029.87`), rating from `.AverageCustomerReviews`, image from `img#landingImage`. If `#outOfStockBuyBox_feature_div` is on the page the product is out of stock and the price is `None` instead of a stale or missing value.

**Variations.** Amazon puts each variation dimension in a `div#inline-twister-row-<dimension>`; every option is an `li` with its own `data-asin`. The scraper reads the dimensions on the base page, sorts them (color, size, style, ...), and walks the option tree depth first, loading each option's own page, because the available options change with the selection (some sizes only exist in some colors). It reads the selected options and the price from each final page and never visits an ASIN twice. Budget one request per variation page; `max_pages` caps it. Note that `html.parser` lowercases attribute names, so options marked `data-initiallyUnavailable="true"` are matched in lowercase and skipped.

**Seller offers.** The "Other sellers" panel loads from `/gp/product/ajax/aodAjaxMain/?asin=<ASIN>`. Each offer has a `div#aod-offer-soldBy`; the scraper climbs to the container holding the price, reads the seller link (no link means Amazon sells it), seller rating, rating count, positive feedback percentage, ships-from and condition, and skips the sticky copy of the Buy Box offer inside `#aod-sticky-pinned-offer` so it isn't counted twice. One offer, or none, is a valid result: the count depends on the ASIN and the delivery location.

## Limits

- **Reviews are not scraped.** Since May 2026 the public `/product-reviews/` pages return Page Not Found to logged-out clients and review text was removed from the product page HTML. Login-protected content is off-limits; use the Amazon Scraper API PDP endpoint for featured reviews.
- **Markup changes.** Amazon changes its HTML. Parsers raise `ValueError` on pages without a product title (usually a CAPTCHA page) and return `None`/empty values for missing fields rather than guessing.
- **Errors.** Non-200 responses raise `ScrapeError` with the status code. Server errors and 429s are retried twice; client errors are not.

## Responsible use

Stick to public pages (products, prices, offers), keep request rates reasonable, and stay away from anything behind a login. Amazon's Conditions of Use restrict automated access; you are responsible for how you use the data and for the laws that apply to you. This is not legal advice.

## Development

```bash
git clone https://github.com/bugrahansss/amazon-scraping
cd amazon-scraping
pip install -e .
python -m unittest discover -s tests -v
```

The tests run offline against fictional fixture pages.

## License

MIT

---

Source: [Complete 2026 Amazon Scraping Guide: Product Data, Prices, Sellers, and More](https://scrape.do/blog/amazon-scraping/)
