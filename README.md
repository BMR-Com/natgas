# Energy Desk

Terminal for natural gas, crude and refined products. Storage and inventory
fundamentals, gas-weighted degree days, a weather-driven storage model,
inventory-implied fair value, CFTC positioning, technicals, and a signal
scorecard across NG, CL, HO and RB.

Runs entirely on GitHub. Nothing to install and nothing to run locally.

## How the data gets here

| Source | What it provides | How it is reached |
|---|---|---|
| EIA Open Data v2 | gas storage, S&D, petroleum stocks, refining, spot and futures, STEO | called from the browser, free key |
| CFTC public reporting | disaggregated Commitments of Traders | called from the browser |
| Open-Meteo | 16-day forecast and ERA5 archive for degree days | called from the browser |
| Yahoo, via yfinance | ETF and futures OHLCV, ETF option chains | fetched by GitHub Actions, committed as JSON |

The first three send CORS headers, so the page calls them directly. Yahoo does
not — a browser cannot read its response at all. That is why yfinance works in
Python and cannot work in a page. The workflow runs it on a GitHub runner,
which is a server, and commits the output to `data/`. Pages serves those files
next to `index.html`, so the page reads them same-origin and CORS never applies.

## Setup, once

1. **Actions permissions.** Settings → Actions → General → Workflow
   permissions → **Read and write permissions** → Save. The workflow commits
   to the repo, so it needs this.
2. **Pages.** Settings → Pages → Source *Deploy from a branch* → `main` /
   `/ (root)` → Save.
3. **Run it.** Actions tab → **Refresh market data** → **Run workflow**. Takes
   about a minute.
4. **EIA key.** Free at <https://www.eia.gov/opendata/register.php>. Paste it
   into the header on the page and press **Refresh all**. Stored in your
   browser only, never in the repo.

After that the workflow runs itself on weekdays at 22:40 UTC, after the US
settle. Run it by hand any time from the Actions tab.

## Files

```
index.html                       the terminal
fetch_data.py                    yfinance fetcher, run by the workflow
.github/workflows/data.yml       schedule and commit step
data/prices.json                 written by the workflow
data/options.json                written by the workflow
```

## If something is empty

- **Everything blank, tabs dead** — a script error. The page paints a red bar
  at the bottom with the message and line number.
- **Price or options panels empty** — the workflow has not run yet, or it
  failed. Check the Actions tab; a failed run shows which symbols did not come
  back.
- **A fundamentals panel empty** — the Data tab lists every EIA series, the
  route it resolved to and the row count, and lets you pin a corrected ID.
- **Yahoo throttles the runner** — it sometimes does with cloud IPs. The script
  falls back to Stooq for prices automatically. Option chains have no fallback,
  so they may be missing from a run where that happens.

## Notes

- Series IDs are not hard-coded. The page reads EIA's facet catalogue on every
  refresh and resolves each panel to a live series, so a renamed series heals
  itself.
- The signal scorecard is a rules engine over your own data, not advice. Every
  component shows its raw input.
- ETFs roll front-month futures monthly and decay against the contract in
  contango. Where one stands in for a contract, the page measures correlation
  and cumulative drift against the EIA front contract and says so.
- Yahoo carries option chains for the ETFs, not for the futures contracts.
