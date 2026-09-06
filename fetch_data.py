#!/usr/bin/env python3
"""
Fetch prices and ETF option chains with yfinance, write JSON next to the terminal.

    pip install yfinance
    python3 fetch_data.py

Writes data/prices.json and data/options.json. Serve the folder and the page
reads them same-origin, so no CORS is involved at any point:

    python3 -m http.server 8000

Re-run it whenever you want fresh data. Options are only available for the
ETFs -- listed futures options are not in Yahoo's chain endpoint.
"""

import json
import pathlib
import sys
from datetime import datetime, timezone

try:
    import yfinance as yf
except ImportError:
    sys.exit("pip install yfinance")

try:
    import urllib.request
except ImportError:  # pragma: no cover
    urllib = None

FUTURES = ["NG=F", "CL=F", "HO=F", "RB=F", "BZ=F"]
ETFS = ["UNG", "BOIL", "KOLD", "USO", "USL", "BNO", "UGA", "XLE", "XOP", "OIH"]

# how the terminal keys them
KEY = {"NG=F": "NG", "CL=F": "CL", "HO=F": "HO", "RB=F": "RB", "BZ=F": "BZ"}

OUT = pathlib.Path("data")
OUT.mkdir(exist_ok=True)


STOOQ = {"NG=F": "ng.f", "CL=F": "cl.f", "HO=F": "ho.f", "RB=F": "rb.f", "BZ=F": "cb.f"}


def stooq_bars(sym):
    """Fallback source. Yahoo occasionally throttles cloud IPs; Stooq does not."""
    s = STOOQ.get(sym) or (sym.lower() + ".us")
    url = f"https://stooq.com/q/d/l/?s={s}&i=d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    txt = urllib.request.urlopen(req, timeout=30).read().decode()
    lines = txt.strip().split("\n")
    if len(lines) < 30 or not lines[0].lower().startswith("date"):
        raise RuntimeError("stooq returned no usable rows")
    out = []
    for ln in lines[1:]:
        p = ln.split(",")
        if len(p) < 5:
            continue
        try:
            o, h, l, c = float(p[1]), float(p[2]), float(p[3]), float(p[4])
        except ValueError:
            continue
        if c <= 0:
            continue
        v = None
        if len(p) > 5:
            try:
                v = int(float(p[5]))
            except ValueError:
                v = None
        out.append({"d": p[0], "o": o, "h": h, "l": l, "c": c, "v": v})
    if not out:
        raise RuntimeError("stooq parsed 0 rows")
    return out[-1300:]


def bars(sym, period="5y"):
    df = yf.Ticker(sym).history(period=period, interval="1d", auto_adjust=True)
    if df is None or df.empty:
        raise RuntimeError("no rows")
    df = df.dropna(subset=["Close"])
    return [
        {
            "d": idx.strftime("%Y-%m-%d"),
            "o": round(float(r.Open), 6),
            "h": round(float(r.High), 6),
            "l": round(float(r.Low), 6),
            "c": round(float(r.Close), 6),
            "v": int(r.Volume) if r.Volume == r.Volume else None,
        }
        for idx, r in df.iterrows()
    ]


def chain(sym, max_expiries=8):
    tk = yf.Ticker(sym)
    exps = list(tk.options or [])[:max_expiries]
    rows = []
    for e in exps:
        try:
            oc = tk.option_chain(e)
        except Exception as err:
            print(f"    {e}: {err}")
            continue
        for side, df in (("C", oc.calls), ("P", oc.puts)):
            for _, r in df.iterrows():
                oi = r.get("openInterest")
                vol = r.get("volume")
                rows.append(
                    {
                        "exp": e,
                        "type": side,
                        "strike": float(r["strike"]),
                        "oi": int(oi) if oi == oi and oi is not None else 0,
                        "vol": int(vol) if vol == vol and vol is not None else 0,
                        "iv": round(float(r.get("impliedVolatility") or 0), 6),
                        "last": float(r.get("lastPrice") or 0),
                    }
                )
    spot = None
    try:
        h = tk.history(period="5d")
        if not h.empty:
            spot = round(float(h["Close"].iloc[-1]), 4)
    except Exception:
        pass
    return {"spot": spot, "expiries": exps, "rows": rows}


def main():
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    prices, failed = {}, []
    for sym in FUTURES + ETFS:
        k = KEY.get(sym, sym)
        try:
            prices[k] = bars(sym)
            print(f"  {k:5s} {len(prices[k]):5d} bars  yfinance")
        except Exception as e:
            try:
                prices[k] = stooq_bars(sym)
                print(f"  {k:5s} {len(prices[k]):5d} bars  stooq (yfinance: {e})")
            except Exception as e2:
                failed.append(f"{k}: yfinance {e}; stooq {e2}")
                print(f"  {k:5s} FAILED — yfinance {e} · stooq {e2}")

    (OUT / "prices.json").write_text(
        json.dumps({"generated": stamp, "failed": failed, "prices": prices},
                   separators=(",", ":"))
    )
    print(f"\ndata/prices.json — {len(prices)} symbols\n")

    chains = {}
    for sym in ETFS:
        try:
            c = chain(sym)
            if c["rows"]:
                chains[sym] = c
                print(f"  {sym:5s} {len(c['rows']):5d} contracts across {len(c['expiries'])} expiries")
            else:
                print(f"  {sym:5s} no contracts returned")
        except Exception as e:
            print(f"  {sym:5s} FAILED — {e}")

    (OUT / "options.json").write_text(
        json.dumps({"generated": stamp, "chains": chains}, separators=(",", ":"))
    )
    print(f"\ndata/options.json — {len(chains)} chains")
    if not prices:
        sys.exit("No price data at all — failing so the Action reports red")
    print("\nRun locally: python3 -m http.server 8000")
    print("On GitHub Actions this output is committed to data/ and served by Pages.")


if __name__ == "__main__":
    main()
