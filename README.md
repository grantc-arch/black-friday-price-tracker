# Was that Black Friday deal real?

Daily price logger for a study of South African Black Friday discounts. It
tracks 40 Takealot products across 8 categories, records the selling price,
the advertised "was" price, stock status and seller, and builds a price
history to test how many Black Friday "discounts" are genuine.

## How it works
1. `products.csv` lists the tracked products.
2. A GitHub Actions workflow (`.github/workflows/log-prices.yml`) runs
   `log_prices.py` every day at 07:00 SAST, plus extra snapshots on 27-30 November.
3. `log_prices.py` calls Takealot's product JSON endpoint for each product and
   appends one row per product to `data/prices.csv`, which the workflow commits
   back to the repo.
4. After the sale, the price history is analysed (baseline vs sale period).

## Setup
1. Create a GitHub repo and push these files.
2. Edit `USER_AGENT` in `log_prices.py` with your real contact email.
3. Fill `products.csv` (30-50 products, several categories). Use full product
   page URLs; for Takealot the URL must contain the `PLID` number.
4. Test locally: `pip install -r requirements.txt && python log_prices.py --debug --limit 3`
   Check that prices are captured. If they show `parse_error`, adjust
   `parse_takealot()` using the fields printed by `--debug`.
   Other options: `--find <text>` runs only products whose name contains the text.
5. Push, then run the workflow manually from the Actions tab to confirm it
   commits `data/prices.csv`. After that it runs on its schedule.

## Rate limiting and retries
Takealot rate-limited the logger once (30 October 2026: 31 of 40 requests
returned HTTP 429). The logger now:
- waits 8 seconds between products (it was 4);
- retries a request that gets HTTP 429, a 5xx error or a network timeout, up to
  3 times, waiting about 30s, 60s and 120s (or the server's `Retry-After` value);
- stops the run if 3 products in a row are still rate limited after all
  retries, and logs the remaining products as `skipped_rate_limited` instead of
  hammering the site.
Failed or skipped products always appear as rows with a non-`ok` status, so
gaps are visible in the data. The workflow run turns red if more than about
10% of products failed in a run.

## Product selection rules
Products were chosen from Takealot's published best-seller data (BusinessTech's
coverage of the 2024 and 2025 sales) and from a candidate list, with the
remaining slots filled by rule. For rule-based slots, in that category on
Takealot, take the top product that passes all four checks:
1. High review count (proxy for sales; use a popularity or most-reviewed sort if available).
2. Sold by Takealot, or a stable seller.
3. Listed for at least 6 months (check the earliest reviews).
4. In stock.
Record the review count and date you checked in your notes, so the method can be reported.

## Seller field
`seller` in the log is either a marketplace seller's slug (e.g. `alcell`) or
`takealot`, when Takealot sells the item directly. This is inferred from a
blank seller field in the API response, confirmed by checking 40 real
products: every blank matched a branded/generic product and every filled
value was a distinctive third-party slug. Worth reporting: how many of your
tracked products are Takealot's own stock vs marketplace sellers, since
third-party prices are less predictable and may be worth analysing
separately. Sellers can rotate, so a price change may really be a seller
change; check the `seller` column before calling something a discount.

## Study phases and definitions (fixed before seeing sale results)
- Baseline: 27 September 2026 - 25 October 2026 (the day before Takealot's
  Black Friday-priced deals began).
- Countdown sale: 26 October - 23 November 2026 (new deals every week).
- Main event: 27 - 30 November 2026 (Black Friday to Cyber Monday).
- Aftermath: 1 December 2026 onward, logged until about 7 December, to see
  whether prices revert after the sale.
- Genuine deal: a sale-phase price below the lowest in-stock price recorded in
  the baseline.
- Inflated "was" price: the advertised was-price never appeared as an actual
  selling price during the baseline.
- Rows with `in_stock = False` are excluded from verdicts.
- Only rows with `status = ok` are used.

## Timing note
Takealot announced on 23 October 2026 that its Black Friday-priced deals would
run from 26 October to 23 November, with 27 November as the main event. That
is earlier and more spread out than the 2025 structure (a countdown from 3
November, then the main sale from 25 November), so a secondary question is
whether prices drifted down gradually or jumped on specific dates.

## Known data limitations
- 30 October 2026: 31 of 40 products were rate limited (HTTP 429), so that
  day has gaps for most products. This is a missing day, not a missing product.
- Sony WH-CH520 headphones: shown as out of stock on every logged day so far,
  so no reliable verdict is possible unless it restocks.
- Defy 157L fridge: out of stock 15-26 October, back in stock since 27 October.
- Defy MAC6030W is a portable air cooler, not an air conditioner.
- Some tracked listings are sold by marketplace sellers whose own was-prices
  are unreliable; lean on the baseline-minimum test for those.
- Basket of 40 products: findings describe this basket, not all of Takealot.

## Ethics
Check each retailer's terms, one pass per scheduled run, honest User-Agent,
back off when rate limited, stop if blocked. Describe findings as being about
your tracked basket, not the whole retailer.
