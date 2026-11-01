"""
Daily price logger for the "Was that Black Friday deal real?" project.

Reads products.csv, fetches the current price for each product, and appends
one row per product to data/prices.csv. Run once a day (GitHub Actions does
this for you). One pass a day, a few seconds between requests, honest
User-Agent. If a site blocks you, drop it rather than working around it.

Usage:
    python log_prices.py            # normal run
    python log_prices.py --debug --limit 3
                                    # test on the first 3 products
    python log_prices.py --debug --find hisense
                                    # test only products whose name contains "hisense"
                                    # --debug saves the LAST matching response to
                                    # debug_response.json and prints its price/stock fields
"""
import csv
import json
import random
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# ---- Settings -------------------------------------------------------------
PRODUCTS_FILE = Path("products.csv")
OUTPUT_FILE = Path("data/prices.csv")
DELAY_SECONDS = 8  # pause between products, keep it polite (was 4; Takealot rate-limited us on 30 Oct)

# Retry settings for rate limits (HTTP 429) and temporary server errors.
# Waits are 30s, 60s, 120s (plus a little random jitter) unless the site sends
# a Retry-After header, which is respected (capped at MAX_WAIT_SECONDS).
MAX_RETRIES = 3
BASE_WAIT_SECONDS = 30
MAX_WAIT_SECONDS = 300
RETRY_STATUSES = {429, 500, 502, 503, 504}
# If this many products in a row still hit the rate limit after all retries,
# stop the run instead of hammering the site. The rest are logged as skipped.
MAX_CONSECUTIVE_RATE_LIMITED = 3

# Identifies this tool to the site. A contact URL or email can be added in the
# brackets if you want the site owner to be able to reach you.
USER_AGENT = "BlackFridayPriceStudy/1.0 (student research project)"

# Takealot's website loads product data from this JSON endpoint. It is not a
# documented public API, so the version number may change over time.
TAKEALOT_API = "https://api.takealot.com/rest/v-1-14-0/product-details/{plid}?platform=desktop"

SAST = timezone(timedelta(hours=2))
FIELDS = ["date", "timestamp", "retailer", "product_id", "name",
          "category", "price", "was_price", "in_stock", "seller", "status"]


# ---- Takealot -------------------------------------------------------------
def get_path(data, *path):
    """Safely walk nested dicts/lists; returns None if any step is missing."""
    for key in path:
        try:
            data = data[key]
        except (KeyError, IndexError, TypeError):
            return None
    return data


def to_number(value):
    if value is None:
        return None
    try:
        return float(str(value).replace("R", "").replace(",", "").replace(" ", ""))
    except ValueError:
        return None


def find_price_fields(data, path=""):
    """Debug helper: list every field whose name looks price/stock/seller related."""
    hits = []
    if isinstance(data, dict):
        for k, v in data.items():
            p = f"{path}.{k}" if path else k
            is_scalar_list = isinstance(v, list) and all(not isinstance(x, (dict, list)) for x in v)
            if any(w in k.lower() for w in ("price", "stock", "availab", "seller")) and (
                    not isinstance(v, (dict, list)) or is_scalar_list):
                hits.append((p, v))
            elif isinstance(v, (dict, list)):
                hits += find_price_fields(v, p)
    elif isinstance(data, list):
        for i, v in enumerate(data[:10]):
            hits += find_price_fields(v, f"{path}[{i}]")
    return hits


def parse_takealot(data):
    """Return (name, price, was_price, in_stock, seller_slug) from the API JSON.

    Confirmed against a real response on 2026-09:
    buybox.items[0].price          = current selling price
    buybox.items[0].listing_price  = the crossed-out "was" price (higher, or
                                      equal to price if there's no discount)
    buybox.items[0].is_add_to_cart_available = whether it can actually be bought
    seller_detail.link_data.fields.seller_slug = who's selling it (helps flag
                                      when a price change is really a seller change)
    """
    name = (get_path(data, "title")
            or get_path(data, "core", "title")
            or get_path(data, "event_data", "documents", "product", "title"))

    price = to_number(get_path(data, "buybox", "items", 0, "price"))
    was = to_number(get_path(data, "buybox", "items", 0, "listing_price"))
    if was is not None and price is not None and was <= price:
        was = None  # no real "was" price when it isn't actually higher

    if price is None:  # fallback if buybox.items is ever missing
        price = to_number(get_path(data, "event_data", "documents", "product", "purchase_price"))
        was = was or to_number(get_path(data, "event_data", "documents", "product", "original_price"))

    stock = get_path(data, "buybox", "items", 0, "is_add_to_cart_available")
    # ASSUMPTION, confirmed by pattern across 40 real products on 2026-09-27:
    # a blank seller_slug means the item is sold by Takealot itself, not a
    # third party. Every branded, generic-name product came back blank, while
    # every distinctive/unusual slug (e.g. "ndlihcoinvestments") was a clear
    # marketplace seller. Recorded explicitly rather than left blank so it's
    # not mistaken for missing data.
    seller = get_path(data, "seller_detail", "link_data", "fields", "seller_slug") or "takealot"
    return name, price, was, stock, seller


def get_with_backoff(url):
    """GET with retries on rate limits / temporary errors. Returns the final response.

    Raises only if every attempt failed with a network error (timeout, DNS, ...).
    """
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(url,
                                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                                timeout=30)
            last_error = None
        except (requests.ConnectionError, requests.Timeout) as e:
            resp, last_error = None, e

        if resp is not None and resp.status_code not in RETRY_STATUSES:
            return resp
        if attempt == MAX_RETRIES:
            break

        wait = BASE_WAIT_SECONDS * (2 ** attempt)
        if resp is not None:
            retry_after = resp.headers.get("Retry-After", "")
            if retry_after.isdigit():
                wait = int(retry_after)
        wait = min(wait, MAX_WAIT_SECONDS) + random.uniform(0, 5)
        reason = f"http_{resp.status_code}" if resp is not None else type(last_error).__name__
        print(f"    {reason}, retry {attempt + 1}/{MAX_RETRIES} in {wait:.0f}s")
        time.sleep(wait)

    if resp is None:
        raise last_error
    return resp


def fetch_takealot(url, debug=False):
    match = re.search(r"PLID\d+", url, re.IGNORECASE)
    if not match:
        return {"status": "bad_url"}
    plid = match.group(0).upper()  # API wants the full "PLID103346940" form
    resp = get_with_backoff(TAKEALOT_API.format(plid=plid))
    if resp.status_code != 200:
        detail = ""
        try:
            detail = resp.json().get("message", "")
        except Exception:
            pass
        return {"product_id": plid, "status": f"http_{resp.status_code}" + (f" ({detail})" if detail else "")}
    data = resp.json()
    if debug:
        Path("debug_response.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        print("Saved full response to debug_response.json (don't commit it)")
        print("Top-level keys:", list(data.keys()))
        print("Fields that look price/stock related:")
        for path, value in find_price_fields(data)[:60]:
            print(f"  {path} = {value}")
    name, price, was, stock, seller = parse_takealot(data)
    return {"product_id": plid, "name": name, "price": price, "was_price": was,
            "in_stock": stock, "seller": seller, "status": "ok" if price is not None else "parse_error"}


FETCHERS = {"takealot": fetch_takealot}


# ---- Main -----------------------------------------------------------------
def main():
    debug = "--debug" in sys.argv
    with PRODUCTS_FILE.open(newline="", encoding="utf-8") as f:
        products = [r for r in csv.DictReader(f) if r.get("url", "").strip()]
    if "--limit" in sys.argv:  # e.g. --limit 3 to test on the first three products
        products = products[:int(sys.argv[sys.argv.index("--limit") + 1])]
    if "--find" in sys.argv:  # e.g. --find hisense to test only products whose name contains "hisense"
        term = sys.argv[sys.argv.index("--find") + 1].lower()
        products = [p for p in products if term in p.get("name", "").lower()]

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    new_file = not OUTPUT_FILE.exists()
    now = datetime.now(SAST)
    ok = 0
    rate_limited_in_a_row = 0
    stopped_early = False

    with OUTPUT_FILE.open("a", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        for i, p in enumerate(products):
            retailer = p["retailer"].strip().lower()
            fetch = FETCHERS.get(retailer)
            row = {"date": now.date().isoformat(), "timestamp": now.isoformat(timespec="seconds"),
                   "retailer": retailer, "product_id": "", "name": p.get("name", ""),
                   "category": p.get("category", ""), "price": "", "was_price": "",
