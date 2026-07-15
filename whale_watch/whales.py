"""
Whale Watch — what the big 13F filers held last quarter, and what changed.

Standalone research/learning tool. Deliberately NOT wired into the trading
bot: 13F data is 45-135 days stale and reflects decade-horizon investors,
which is the wrong signal for a days-to-weeks swing bot (and the forward
test must not have its inputs changed mid-run).

Data source: SEC EDGAR (free, official). Institutional managers with >$100M
must file form 13F within 45 days of each quarter end. This shows their
long positions in US-listed stocks — not shorts, not bonds, not timing.

Usage:
    python whales.py              # summary of every tracked filer
    python whales.py buffett      # one filer, full detail
    python whales.py --list      # show tracked filers

Values are as-filed (whole USD since 2023). Ticker tags are best-effort
name matches against the bot's whitelist; everything else shows by name.
"""
import json
import sys
import time
import urllib.request
from xml.etree import ElementTree

# SEC asks automated clients to identify themselves.
HEADERS = {"User-Agent": "Greyson Rice greysonpuma@gmail.com"}

# name -> (CIK, who it is)
FILERS = {
    "buffett":       (1067983, "Berkshire Hathaway (Warren Buffett)"),
    "bridgewater":   (1350694, "Bridgewater Associates (Ray Dalio's firm)"),
    "renaissance":   (1037389, "Renaissance Technologies (quant legend RenTec)"),
    "ackman":        (1336528, "Pershing Square (Bill Ackman)"),
    "burry":         (1649339, "Scion Asset Management (Michael Burry)"),
    "druckenmiller": (1536411, "Duquesne Family Office (Stanley Druckenmiller)"),
}

# Distinctive 13F issuer-name fragments -> bot whitelist tickers.
WHITELIST_NAMES = {
    "APPLE INC": "AAPL", "MICROSOFT": "MSFT", "NVIDIA": "NVDA",
    "ALPHABET": "GOOGL", "AMAZON": "AMZN", "META PLATFORMS": "META",
    "TESLA": "TSLA", "ADVANCED MICRO": "AMD", "NETFLIX": "NFLX",
    "BROADCOM": "AVGO", "ORACLE": "ORCL", "SALESFORCE": "CRM",
    "ADOBE": "ADBE", "JPMORGAN": "JPM", "BANK OF AMER": "BAC",
    "BANK AMER": "BAC", "GOLDMAN SACHS": "GS", "MORGAN STANLEY": "MS",
    "VISA INC": "V", "MASTERCARD": "MA", "DISNEY": "DIS",
    "WALMART": "WMT", "WAL-MART": "WMT", "COSTCO": "COST",
    "HOME DEPOT": "HD", "CATERPILLAR": "CAT", "BOEING": "BA",
    "UNITEDHEALTH": "UNH", "JOHNSON & JOHNSON": "JNJ",
    "JOHNSON JOHNSON": "JNJ", "EXXON": "XOM", "CHEVRON": "CVX",
    "SPDR S&P 500": "SPY", "INVESCO QQQ": "QQQ",
}


def _get(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _get_json(url: str):
    return json.loads(_get(url))


def latest_13f_accessions(cik: int, n: int = 2):
    """Return the n most recent 13F-HR filings as (accession, report_date, filed)."""
    subs = _get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    recent = subs["filings"]["recent"]
    out, seen_periods = [], set()
    for form, acc, rdate, fdate in zip(recent["form"], recent["accessionNumber"],
                                       recent["reportDate"], recent["filingDate"]):
        # Prefer the first (newest) filing per period; amendments file later
        # but appear earlier in the list, so this naturally picks them up.
        if form in ("13F-HR", "13F-HR/A") and rdate not in seen_periods:
            seen_periods.add(rdate)
            out.append((acc, rdate, fdate))
        if len(out) == n:
            break
    return subs["name"], out


def fetch_holdings(cik: int, accession: str):
    """Parse a 13F information table into {cusip: {name, value, shares}}."""
    acc = accession.replace("-", "")
    index = _get_json(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json")
    xml_files = [f["name"] for f in index["directory"]["item"]
                 if f["name"].lower().endswith(".xml")
                 and "primary_doc" not in f["name"].lower()]
    holdings = {}
    for fname in xml_files:
        raw = _get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{fname}")
        if b"infoTable" not in raw:
            continue
        root = ElementTree.fromstring(raw)
        for elem in root.iter():
            if elem.tag.split("}")[-1] != "infoTable":
                continue
            row = {child.tag.split("}")[-1]: child for child in elem.iter()}
            cusip = row["cusip"].text.strip()
            value = float(row["value"].text)
            shares = float(row["sshPrnamt"].text) if "sshPrnamt" in row else 0.0
            h = holdings.setdefault(cusip, {"name": row["nameOfIssuer"].text.strip(),
                                            "value": 0.0, "shares": 0.0})
            h["value"] += value       # same cusip can appear in several rows
            h["shares"] += shares
        break
    # Unit guard: values must be whole dollars since 2023, but some filers
    # still file in thousands. A 13F filer manages >= $100M by definition,
    # so a total below that means the values are $000s.
    if holdings and sum(h["value"] for h in holdings.values()) < 100e6:
        for h in holdings.values():
            h["value"] *= 1000
    return holdings


def ticker_tag(name: str) -> str:
    upper = name.upper()
    for fragment, ticker in WHITELIST_NAMES.items():
        if fragment in upper:
            return f" [{ticker}*]"     # * = on the bot's whitelist
    return ""


def money(v: float) -> str:
    for cut, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= cut:
            return f"${v / cut:,.1f}{suffix}"
    return f"${v:,.0f}"


def report(key: str, detail: bool):
    cik, who = FILERS[key]
    entity, filings = latest_13f_accessions(cik)
    if not filings:
        print(f"\n{'=' * 72}\n{who}: no 13F filings found\n")
        return
    (acc_new, period_new, filed_new) = filings[0]
    latest = fetch_holdings(cik, acc_new)
    prior = fetch_holdings(cik, filings[1][0]) if len(filings) > 1 else {}

    total = sum(h["value"] for h in latest.values())
    print(f"\n{'=' * 72}")
    print(f"{who}")
    print(f"  filed as: {entity}")
    print(f"  holdings as of {period_new} (filed {filed_new} — this data is "
          f"already weeks/months old)")
    print(f"  reported long-stock portfolio: {money(total)} across {len(latest)} positions")

    top = sorted(latest.values(), key=lambda h: -h["value"])[:10 if detail else 5]
    print(f"\n  Top {len(top)} holdings:")
    for h in top:
        pct = h["value"] / total * 100 if total else 0
        print(f"    {pct:5.1f}%  {money(h['value']):>8}  {h['name']}{ticker_tag(h['name'])}")

    if prior:
        prior_total = sum(h["value"] for h in prior.values())
        new_pos = [latest[c] for c in latest.keys() - prior.keys()]
        gone = [prior[c] for c in prior.keys() - latest.keys()]
        if new_pos:
            print("\n  NEW positions this quarter:")
            for h in sorted(new_pos, key=lambda h: -h["value"])[:8 if detail else 4]:
                print(f"    + {money(h['value']):>8}  {h['name']}{ticker_tag(h['name'])}")
        if gone:
            print("\n  EXITED since prior quarter:")
            for h in sorted(gone, key=lambda h: -h["value"])[:8 if detail else 4]:
                print(f"    - was {money(h['value']):>8}  {h['name']}{ticker_tag(h['name'])}")
        if detail:
            changed = []
            for cusip in latest.keys() & prior.keys():
                old_sh, new_sh = prior[cusip]["shares"], latest[cusip]["shares"]
                if old_sh > 0 and abs(new_sh - old_sh) / old_sh >= 0.25:
                    changed.append((latest[cusip], (new_sh - old_sh) / old_sh))
            if changed:
                print("\n  Position size changes >= 25% (by share count):")
                for h, chg in sorted(changed, key=lambda x: -abs(x[0]["value"]))[:8]:
                    print(f"    {chg:+7.0%}  {h['name']}{ticker_tag(h['name'])}")
        print(f"\n  Portfolio value {money(prior_total)} -> {money(total)} "
              f"(includes price moves, not just trading)")

    overlap = sorted({ticker_tag(h["name"]).strip(" [*]")
                      for h in latest.values() if ticker_tag(h["name"])})
    if overlap:
        print(f"\n  Overlap with the bot's whitelist: {', '.join(overlap)}")


def main():
    args = [a.lower() for a in sys.argv[1:]]
    if "--list" in args:
        for k, (_, who) in FILERS.items():
            print(f"  {k:14} {who}")
        return
    picks = [a for a in args if a in FILERS]
    if args and not picks:
        print(f"unknown filer {args[0]!r} — options: {', '.join(FILERS)}")
        return
    targets = picks or list(FILERS)
    for i, key in enumerate(targets):
        if i:
            time.sleep(0.5)   # stay well under SEC's rate limit
        try:
            report(key, detail=bool(picks))
        except Exception as e:
            print(f"\n{'=' * 72}\n{FILERS[key][1]}: failed to fetch ({e})")
    print(f"\n{'=' * 72}")
    print("Remember what this is: quarterly snapshots filed up to 45 days late,")
    print("from investors with 5-30 year horizons. Useful for learning how the")
    print("greats position; useless as a swing-trade timing signal. [*] = stock")
    print("is on the bot's whitelist.")


if __name__ == "__main__":
    main()
