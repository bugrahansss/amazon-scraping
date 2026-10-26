"""Command line entry point: ``amazon-scraping product|variations|offers|pdp ...``."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import Any, Dict, List, Optional

from . import __version__
from .client import TOKEN_ENV, AmazonScraper, ScrapeError
from .parser import OFFER_FIELDS, PRODUCT_FIELDS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="amazon-scraping",
        description="Scrape Amazon products, all variations and seller offers into JSON or CSV.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-t", "--token", help=f"Scrape.do API token (default: ${TOKEN_ENV})")
    common.add_argument("-f", "--format", choices=("json", "csv"), default="json", help="Output format (default: json)")
    common.add_argument("-o", "--output", help="Write to this file instead of stdout")
    common.add_argument("--zipcode", default="10001", help="US ZIP code for local prices (default: 10001)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("product", parents=[common], help="Name, price, stock, rating and image")
    p.add_argument("items", nargs="*", help="ASINs or product URLs")
    p.add_argument("-i", "--input", help="Text file with one ASIN or URL per line")

    v = sub.add_parser("variations", parents=[common], help="Every color/size/style variation of one product")
    v.add_argument("item", help="ASIN or product URL")
    v.add_argument("--max-pages", type=int, help="Stop after this many page requests")

    o = sub.add_parser("offers", parents=[common], help="All seller offers for one ASIN")
    o.add_argument("item", help="ASIN or product URL")

    j = sub.add_parser("pdp", parents=[common], help="Structured JSON from the Amazon Scraper API")
    j.add_argument("item", help="ASIN or product URL")
    return parser


def _write(rows: List[Dict[str, Any]], fmt: str, stream, fields: Optional[List[str]] = None) -> None:
    if fmt == "csv":
        keys = fields or (list(rows[0]) if rows else [])
        for row in rows:
            keys += [k for k in row if k not in keys]
        writer = csv.DictWriter(stream, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    else:
        json.dump(rows, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        scraper = AmazonScraper(token=args.token, zipcode=args.zipcode)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    fields = None
    failures = 0
    try:
        if args.command == "product":
            items = list(args.items)
            if args.input:
                with open(args.input, encoding="utf-8") as handle:
                    items += [line.strip() for line in handle if line.strip() and not line.startswith("#")]
            if not items:
                print("No ASINs given. Pass ASINs/URLs or --input FILE.", file=sys.stderr)
                return 2
            rows, fields = [], list(PRODUCT_FIELDS)
            for item in items:
                try:
                    rows.append(scraper.get_product(item))
                    print(f"ok    {item}", file=sys.stderr)
                except (ScrapeError, ValueError) as exc:
                    failures += 1
                    print(f"fail  {item}: {exc}", file=sys.stderr)
        elif args.command == "variations":
            rows = scraper.get_variations(
                args.item, max_pages=args.max_pages,
                on_row=lambda r: print(f"✓ {r['asin']}: {r['price']}", file=sys.stderr),
            )
        elif args.command == "offers":
            rows, fields = scraper.get_offers(args.item), list(OFFER_FIELDS)
        else:
            rows = [scraper.pdp(args.item)]
    except (ScrapeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="" if args.format == "csv" else None) as handle:
            _write(rows, args.format, handle, fields)
        print(f"Saved {len(rows)} row(s) to {args.output}", file=sys.stderr)
    else:
        _write(rows, args.format, sys.stdout, fields)
    return 1 if failures and not rows else 0


if __name__ == "__main__":
    raise SystemExit(main())
