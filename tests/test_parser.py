import csv
import io
import json
import unittest
from pathlib import Path
from unittest import mock

from amazon_scraping import (
    AmazonScraper,
    ScrapeError,
    asin_from_url,
    parse_offers,
    parse_product,
    parse_variations,
    product_url,
    selected_options,
)
from amazon_scraping import cli

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def _response(status, text="", data=None):
    r = mock.Mock()
    r.status_code, r.text = status, text
    r.json.return_value = data
    return r


class ProductTest(unittest.TestCase):
    def test_in_stock(self):
        p = parse_product(fixture("product_in_stock.html"), url="https://www.amazon.com/Some-Stand/dp/B0BLRJ4R8F/")
        self.assertEqual(p["asin"], "B0BLRJ4R8F")
        self.assertEqual(p["name"], "Example Basics Portable Laptop Stand, Height Adjustable, Silver")
        self.assertEqual(p["price"], 1029.87)  # "1,029." + "87"
        self.assertTrue(p["in_stock"])
        self.assertEqual(p["rating"], 4.6)
        self.assertTrue(p["image"].startswith("https://m.media-amazon.com/"))

    def test_out_of_stock(self):
        p = parse_product(fixture("product_out_of_stock.html"))
        self.assertIsNone(p["price"])
        self.assertFalse(p["in_stock"])
        self.assertEqual(p["name"], 'Example Ergonomic Stand 10-15.6", Silver')

    def test_captcha_page(self):
        with self.assertRaises(ValueError):
            parse_product(fixture("captcha.html"))

    def test_asin_helpers(self):
        self.assertEqual(asin_from_url("https://www.amazon.com/Apple-iPhone/dp/B0CG84XR6N/?th=1"), "B0CG84XR6N")
        self.assertEqual(asin_from_url("B0BLRJ4R8F"), "B0BLRJ4R8F")
        self.assertIsNone(asin_from_url("https://www.amazon.com/s?k=laptop"))
        self.assertEqual(product_url("B0BLRJ4R8F"), "https://www.amazon.com/dp/B0BLRJ4R8F/")


class VariationsTest(unittest.TestCase):
    def test_dimensions_skip_unavailable(self):
        dims = parse_variations(fixture("variation_B0EXAMPLE1.html"))
        self.assertEqual(set(dims), {"color", "size"})
        self.assertEqual([o["name"] for o in dims["color"]], ["Blue", "Black"])  # Red is initially unavailable
        self.assertEqual([o["name"] for o in dims["size"]], ["128GB", "256GB"])

    def test_selected_options(self):
        sel = selected_options(fixture("variation_B0EXAMPLE4.html"), ["color", "size"], "B0EXAMPLE4")
        self.assertEqual(sel, {"color": "Black", "size": "256GB"})

    def test_walks_every_combination(self):
        pages = {f"B0EXAMPLE{i}": fixture(f"variation_B0EXAMPLE{i}.html") for i in range(1, 5)}

        def fake_fetch(url):
            return pages[asin_from_url(url)]

        scraper = AmazonScraper(token="T")
        with mock.patch.object(scraper, "fetch_product_html", side_effect=fake_fetch) as fetch:
            rows = scraper.get_variations("https://www.amazon.com/Example-Phone/dp/B0EXAMPLE1/")
        self.assertEqual(len(rows), 4)
        self.assertEqual(fetch.call_count, 4)  # each ASIN fetched once
        by_asin = {r["asin"]: r for r in rows}
        self.assertEqual((by_asin["B0EXAMPLE2"]["color"], by_asin["B0EXAMPLE2"]["size"], by_asin["B0EXAMPLE2"]["price"]), ("Blue", "256GB", 599.0))
        self.assertEqual((by_asin["B0EXAMPLE4"]["price"], by_asin["B0EXAMPLE4"]["in_stock"]), (None, False))
        self.assertEqual(list(rows[0])[:4], ["asin", "name", "color", "size"])  # color sorted before size

    def test_max_pages(self):
        scraper = AmazonScraper(token="T")
        with mock.patch.object(scraper, "fetch_product_html", side_effect=lambda u: fixture(f"variation_{asin_from_url(u)}.html")):
            rows = scraper.get_variations("B0EXAMPLE1", max_pages=2)
        self.assertLessEqual(len(rows), 2)


class OffersTest(unittest.TestCase):
    def test_offers(self):
        offers = parse_offers(fixture("offers_panel.html"), "B0BN969PGL")
        self.assertEqual(len(offers), 3)  # sticky Buy Box copy skipped
        first = offers[0]
        self.assertEqual((first["price"], first["seller"], first["condition"]), (325.0, "ExampleMobile", "Refurbished - Excellent"))
        self.assertEqual((first["seller_rating"], first["rating_count"], first["positive"]), (4.0, 10174, "71%"))
        self.assertEqual(offers[2]["seller"], "Amazon.com")
        self.assertEqual(parse_offers("<html></html>"), [])


class ClientTest(unittest.TestCase):
    def test_requires_token(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                AmazonScraper()

    def test_product_request_uses_plugin(self):
        session = mock.Mock()
        session.get.return_value = _response(200, fixture("product_in_stock.html"))
        AmazonScraper(token="T", session=session).get_product("B0BLRJ4R8F")
        url, = session.get.call_args[0]
        params = session.get.call_args[1]["params"]
        self.assertEqual(url, "https://api.scrape.do/plugin/amazon/")
        self.assertEqual(params, {"token": "T", "url": "https://www.amazon.com/dp/B0BLRJ4R8F/", "geocode": "us", "zipcode": "10001", "output": "html"})

    def test_offers_request(self):
        session = mock.Mock()
        session.get.return_value = _response(200, fixture("offers_panel.html"))
        offers = AmazonScraper(token="T", session=session).get_offers("https://www.amazon.com/x/dp/B0BN969PGL/")
        params = session.get.call_args[1]["params"]
        self.assertEqual(params["url"], "https://www.amazon.com/gp/product/ajax/aodAjaxMain/?asin=B0BN969PGL")
        self.assertEqual(params["geoCode"], "us")
        self.assertEqual(len(offers), 3)

    def test_pdp_json(self):
        session = mock.Mock()
        session.get.return_value = _response(200, data={"asin": "B0BLRJ4R8F", "price": 29.87, "status": "success"})
        data = AmazonScraper(token="T", session=session).pdp("B0BLRJ4R8F")
        self.assertEqual(session.get.call_args[0][0], "https://api.scrape.do/plugin/amazon/pdp")
        self.assertEqual(session.get.call_args[1]["params"]["asin"], "B0BLRJ4R8F")
        self.assertEqual(data["price"], 29.87)

    def test_client_error_not_retried(self):
        session = mock.Mock()
        session.get.return_value = _response(401)
        with self.assertRaises(ScrapeError) as ctx:
            AmazonScraper(token="T", session=session, retries=3).fetch_product_html("B0BLRJ4R8F")
        self.assertEqual((ctx.exception.status_code, session.get.call_count), (401, 1))

    @mock.patch("amazon_scraping.client.time.sleep")
    def test_server_error_retried(self, _sleep):
        session = mock.Mock()
        session.get.side_effect = [_response(502), _response(200, "ok")]
        self.assertEqual(AmazonScraper(token="T", session=session).fetch_product_html("B0BLRJ4R8F"), "ok")


class CliTest(unittest.TestCase):
    def _run(self, argv, html):
        out = io.StringIO()
        with mock.patch("amazon_scraping.client.AmazonScraper.fetch_product_html", return_value=html), \
                mock.patch("sys.stdout", out), mock.patch("sys.stderr", io.StringIO()):
            code = cli.main(argv)
        return code, out.getvalue()

    def test_product_json_and_csv(self):
        code, out = self._run(["product", "B0BLRJ4R8F", "--token", "T"], fixture("product_in_stock.html"))
        self.assertEqual((code, json.loads(out)[0]["price"]), (0, 1029.87))
        code, out = self._run(["product", "B0BLRJ4R8F", "--token", "T", "-f", "csv"], fixture("product_out_of_stock.html"))
        row = next(csv.DictReader(io.StringIO(out)))
        self.assertEqual((row["in_stock"], row["price"]), ("False", ""))


if __name__ == "__main__":
    unittest.main()
