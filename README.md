# Was that Black Friday deal real?

Daily price logger for a study of South African Black Friday discounts.

## Setup
1. Create a GitHub repo and push these files.
2. Edit `USER_AGENT` in `log_prices.py` with your real contact email.
3. Fill `products.csv` (30-50 products, several categories). Use full product
   page URLs; for Takealot the URL must contain the `PLID` number.
4. Run locally once: `pip install -r requirements.txt && python log_prices.py --debug`
   Check that prices are captured. If they show `parse_error`, adjust
   `parse_takealot()` using the JSON printed by `--debug`.
5. Push, then run the workflow manually from the Actions tab to confirm it
   commits `data/prices.csv`. After that it runs daily.

## Product selection rules
Rows marked "TBC" are slots filled by rule, not by hand. In that category on
Takealot, take the top product that passes all four checks, then replace the
TBC name with the real product name:
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
separately.

## Definitions (fix these before you see results)
- Genuine deal: Black Friday price is below the lowest price in the prior 30 days.
- Inflated "was" price: the advertised was-price never appeared as the selling price.
- Baseline period: 28 September 2026 through 25 October 2026 (the day before Takealot's Black November sale began).
- Sale period: 26 October 2026 onward.
- Genuine deal: sale price is below the lowest price recorded during the baseline period.
- Inflated "was" price: the advertised was-price never appeared as the actual selling price during the baseline period.

- ## Timing note
Takealot announced the 2026 Black November sale would start 26 October — earlier and more abrupt than the gradual "countdown" sale structure used in 2025 (per BusinessTech's coverage), which ramped up through November. Worth checking in the analysis whether prices shifted gradually or jumped all at once on the 26th.

## Ethics
Check each retailer's terms, one pass a day, honest User-Agent, stop if blocked.
Describe findings as being about your tracked basket, not the whole retailer.
