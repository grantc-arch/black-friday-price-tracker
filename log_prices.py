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
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# ---- Settings -------------------------------------------------------------
PRODUCTS_FILE = Path("products.csv")
OUTPUT_FILE = Path("data/prices.csv")
DELAY_SECONDS = 4  # pause between requests, keep it polite

# CHANGE THIS: put your own contact so the site owner can reach you.
USER_AGENT = "BlackFridayPriceStudy/1.0 (student research project; contact: your-email@example.com)"

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


def fetch_takealot(url, debug=False):
    match = re.search(r"PLID\d+", url, re.IGNORECASE)
    if not match:
        return {"status": "bad_url"}
    plid = match.group(0).upper()  # API wants the full "PLID103346940" form
    resp = requests.get(TAKEALOT_API.format(plid=plid),
                        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                        timeout=30)
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
                   "in_stock": "", "seller": "", "status": "no_fetcher"}
            if fetch:
                try:
                    result = fetch(p["url"], debug=(debug and i == 0))
                    for k, v in result.items():
                        if v is not None and (k != "name" or not row["name"]):
                            row[k] = v
                except Exception as e:  # network errors, bad JSON, etc.
                    row["status"] = f"error_{type(e).__name__}"
            if row["status"] == "ok":
                ok += 1
            writer.writerow(row)
            print(f"{row['status']:<14} {row['name'][:45]:<45} price={row['price']} was={row['was_price']} seller={row['seller']}")
            if i < len(products) - 1:
                time.sleep(DELAY_SECONDS)

    print(f"\n{ok}/{len(products)} products logged successfully.")
    if products and ok == 0:
        sys.exit(1)  # makes the GitHub Actions run show as failed


if __name__ == "__main__":
    main()
