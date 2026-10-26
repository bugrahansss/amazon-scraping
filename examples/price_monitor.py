"""Check prices and seller offers for a list of ASINs and save them to CSV.

Usage:
    export SCRAPEDO_TOKEN=your_token
    python price_monitor.py asins.txt prices.csv
"""

import csv
import sys
from datetime import datetime, timezone

from amazon_scraping import AmazonScraper, ScrapeError


def main(asin_file: str, out_file: str) -> None:
    with open(asin_file, encoding="utf-8") as handle:
        asins = [line.strip() for line in handle if line.strip()]

    scraper = AmazonScraper()  # reads SCRAPEDO_TOKEN
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(out_file, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["checked_at", "asin", "name", "buy_box_price", "in_stock", "offers", "lowest_offer"])
        for asin in asins:
            try:
                product = scraper.get_product(asin)
                offers = scraper.get_offers(asin)
            except (ScrapeError, ValueError) as exc:
                print(f"skipped {asin}: {exc}")
                continue
            prices = [o["price"] for o in offers if o["price"] is not None]
            writer.writerow([checked_at, asin, product["name"], product["price"], product["in_stock"], len(offers), min(prices) if prices else ""])
            print(f"{asin}: {product['price']} ({len(offers)} offers)")


if __name__ == "__main__":
    main(*sys.argv[1:3])
