# Energy Desk

Single-file terminal for natural gas, crude and refined products. Storage and
inventory fundamentals, gas-weighted degree days, a weather-driven storage
model, inventory-implied fair value, CFTC positioning, technicals, and a signal
scorecard across NG, CL, HO and RB.

Everything runs in the browser. `index.html` has no build step and no
dependencies.

## Data sources

| Source | What it provides | Access |
|---|---|---|
| EIA Open Data v2 | gas storage, S&D, petroleum stocks, refining, spot and futures, STEO | free key, sends CORS headers |
| CFTC public reporting | disaggregated Commitments of Traders | no key, sends CORS headers |
| Open-Meteo | 16-day forecast and ERA5 archive for degree days | no key, sends CORS headers |
| yfinance (`fetch_data.py`) | ETF and futures OHLCV, ETF option chains | Python, writes local JSON |

The first three are called directly from the page. Yahoo is not, because it
sends no `Access-Control-Allow-Origin` header — a browser cannot read its
response at all. yfinance works because it is Python, where CORS does not
apply. So the script fetches, writes JSON, and the page reads that file
same-origin.

## Running it

```bash
pip install -r requirements.txt
python3 fetch_data.py          # writes data/prices.json and data/options.json
python3 -m http.server 8000
```

Open <http://localhost:8000>. On Windows use `python` instead of `python3`.

Get a free EIA key at <https://www.eia.gov/opendata/register.php>, paste it in
the header, press **Refresh all**. It is stored in your browser only.

Re-run `fetch_data.py` whenever you want fresh prices and option chains.

Opening `index.html` as a file will not work — a `file://` page has a null
origin and every API rejects it. It has to be served over http.

## Hosting on GitHub Pages

Settings → Pages → deploy from `main`, root folder.

The EIA, CFTC and weather panels work on Pages as they are. The price and
options panels need `data/*.json` present, and `.gitignore` excludes those by
default. Two choices:

- **Commit the data.** Remove the two `data/*.json` lines from `.gitignore`,
  run the script, commit the output. Refreshes when you re-run and push.
- **Keep prices local.** Leave it as is and use Pages for the fundamentals,
  running locally when you want the charts and chains.

A scheduled Action could run the script for you, but it is deliberately not
included — add one only if you want that.

## Layout

```
index.html        the terminal, one file
fetch_data.py     yfinance fetcher
data/             JSON output, created by the script
```

## Notes

- Series IDs are not hard-coded. The page reads EIA's facet catalogue on each
  refresh and resolves every panel to a live series, so a renamed series heals
  itself. The Data tab shows what resolved to what and lets you pin overrides.
- The signal scorecard is a rules engine over your own data, not advice. Every
  component shows its raw input so you can see what drives the score.
- ETFs roll front-month futures monthly, so they decay against the contract in
  contango. Where an ETF stands in for a contract, the page measures the
  correlation and cumulative drift against the EIA front contract and says so.
- Yahoo carries option chains for the ETFs, not for the futures contracts.
