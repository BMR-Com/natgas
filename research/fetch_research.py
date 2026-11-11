"""Weekly natural-gas research data pull (runs on GitHub Actions; the page and the weekly note read the output).

Writes data/research/:
  hdd_hist.json      daily gas-weighted HDD/CDD (21 metros, ERA5 via Open-Meteo archive), 1995 to yesterday
  hdd_fcst.json      16-day daily gas-weighted HDD from GFS, ECMWF IFS and their ensembles (Open-Meteo)
  hdd_verify.json    forecast vs observed gas-weighted HDD at 1-7 day leads (Open-Meteo previous-runs archive, GFS and ECMWF)
  cpc.json           NOAA CPC 6-10/8-14 day and week 3-4 prognostic discussions (text)
"""
import json, os, time, datetime as dt
import requests

OUT = "data/research"; os.makedirs(OUT, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0 (BMR-Com energy desk research)"}
CITIES = [("Chicago",41.88,-87.63,.105),("New York",40.71,-74.01,.100),("Detroit",42.33,-83.05,.058),("Philadelphia",39.95,-75.17,.048),
 ("Boston",42.36,-71.06,.045),("Minneapolis",44.98,-93.27,.045),("Cleveland",41.50,-81.69,.038),("Pittsburgh",40.44,-79.996,.033),
 ("St. Louis",38.63,-90.20,.035),("Kansas City",39.10,-94.58,.032),("Indianapolis",39.77,-86.16,.030),("Cincinnati",39.10,-84.51,.030),
 ("Denver",39.74,-104.99,.038),("Salt Lake City",40.76,-111.89,.022),("Washington DC",38.91,-77.04,.038),("Atlanta",33.75,-84.39,.048),
 ("Charlotte",35.23,-80.84,.028),("Nashville",36.16,-86.78,.026),("Dallas",32.78,-96.80,.060),("Houston",29.76,-95.37,.053),("Seattle",47.61,-122.33,.028)]
W = sum(c[3] for c in CITIES)
LAT = ",".join(str(c[1]) for c in CITIES); LON = ",".join(str(c[2]) for c in CITIES)
log = {}


def get(url, params, tries=4):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=H, timeout=180)
            if r.status_code == 200:
                return r.json()
            log.setdefault("http", []).append([url, r.status_code, r.text[:200]])
        except Exception as e:
            log.setdefault("err", []).append([url, str(e)[:150]])
        time.sleep(10 * (i + 1))
    return None


def f_of(c):
    return c * 9 / 5 + 32


def weighted(daily_by_city, key="t"):
    """daily_by_city: list (per city) of {date: tempF}; returns {date: (hdd, cdd)} gas-weighted."""
    dates = sorted(set().union(*[set(d) for d in daily_by_city]))
    out = {}
    for d in dates:
        h = c = w = 0
        for (nm, la, lo, wt), m in zip(CITIES, daily_by_city):
            if d in m and m[d] is not None:
                t = m[d]; h += wt * max(0, 65 - t); c += wt * max(0, t - 65); w += wt
        if w > 0.8 * W:
            out[d] = (round(h / w, 2), round(c / w, 2))
    return out


def multi(js):
    return js if isinstance(js, list) else [js]


# 1) history (ERA5 daily mean temperature), in yearly chunks to stay within limits
hist = {}
start = 1995
today = dt.date.today()
for y0 in range(start, today.year + 1, 4):
    a = f"{y0}-01-01"; b = min(dt.date(y0 + 3, 12, 31), today - dt.timedelta(days=1)).isoformat()
    js = get("https://archive-api.open-meteo.com/v1/archive", {"latitude": LAT, "longitude": LON, "start_date": a, "end_date": b,
             "daily": "temperature_2m_mean", "temperature_unit": "fahrenheit", "timezone": "America/New_York"})
    if not js:
        continue
    per = [dict(zip(x["daily"]["time"], x["daily"]["temperature_2m_mean"])) for x in multi(js)]
    hist.update(weighted(per))
    time.sleep(5)
json.dump({"generated": dt.datetime.utcnow().isoformat(timespec="minutes"), "cities": [c[0] for c in CITIES], "base_f": 65,
           "daily": {d: v for d, v in sorted(hist.items())}}, open(f"{OUT}/hdd_hist.json", "w"), separators=(",", ":"))
print("hist days", len(hist))

# 2) forecasts: deterministic and ensemble means, 16 days
fc = {}
for model in ["gfs_seamless", "ecmwf_ifs025", "gem_seamless"]:
    js = get("https://api.open-meteo.com/v1/forecast", {"latitude": LAT, "longitude": LON, "daily": "temperature_2m_mean", "temperature_unit": "fahrenheit",
             "timezone": "America/New_York", "forecast_days": 16, "models": model})
    if js:
        per = [dict(zip(x["daily"]["time"], x["daily"]["temperature_2m_mean"])) for x in multi(js)]
        fc[model] = weighted(per)
for model in ["gfs025", "ecmwf_ifs025"]:
    js = get("https://ensemble-api.open-meteo.com/v1/ensemble", {"latitude": LAT, "longitude": LON, "hourly": "temperature_2m", "temperature_unit": "fahrenheit",
             "timezone": "America/New_York", "forecast_days": 16 if model == "gfs025" else 15, "models": model})
    if not js:
        continue
    per = []
    for x in multi(js):
        hr = x["hourly"]; t = hr["time"]; mem = [k for k in hr if k.startswith("temperature_2m")]
        days = {}
        for i, ts in enumerate(t):
            vals = [hr[k][i] for k in mem if hr[k][i] is not None]
            if vals:
                days.setdefault(ts[:10], []).append(sum(vals) / len(vals))
        per.append({d: sum(v) / len(v) for d, v in days.items() if len(v) >= 20})
    fc["ens_" + model] = weighted(per)
json.dump({"generated": dt.datetime.utcnow().isoformat(timespec="minutes"), "models": fc}, open(f"{OUT}/hdd_fcst.json", "w"), separators=(",", ":"))
print("fcst models", {k: len(v) for k, v in fc.items()})

# 3) verification: forecasts made N days earlier vs observed, winters Dec-Feb 2024-25 and 2025-26 plus Nov 2025 and Mar 2025/26
ver = {}
var = ",".join(["temperature_2m"] + [f"temperature_2m_previous_day{i}" for i in range(1, 8)])
periods = [("2024-11-01", "2025-03-31"), ("2025-11-01", "2026-03-31"), ("2026-10-01", (today - dt.timedelta(days=1)).isoformat())]
for model in ["gfs_seamless", "ecmwf_ifs025"]:
    allp = {}
    for a, b in periods:
        js = get("https://previous-runs-api.open-meteo.com/v1/forecast", {"latitude": LAT, "longitude": LON, "hourly": var, "temperature_unit": "fahrenheit",
                 "timezone": "America/New_York", "start_date": a, "end_date": b, "models": model})
        if not js:
            continue
        for lead in range(0, 8):
            k = "temperature_2m" if lead == 0 else f"temperature_2m_previous_day{lead}"
            per = []
            for x in multi(js):
                hr = x["hourly"]; days = {}
                for ts, v in zip(hr["time"], hr.get(k, [])):
                    if v is not None:
                        days.setdefault(ts[:10], []).append(v)
                per.append({d: sum(v) / len(v) for d, v in days.items() if len(v) >= 20})
            allp.setdefault(lead, {}).update(weighted(per))
        time.sleep(5)
    ver[model] = {str(k): v for k, v in allp.items()}
json.dump({"generated": dt.datetime.utcnow().isoformat(timespec="minutes"), "note": "lead 0 = analysis/observed-like first-day; lead N = forecast made N days earlier",
           "models": ver}, open(f"{OUT}/hdd_verify.json", "w"), separators=(",", ":"))
print("verify", {m: {k: len(v) for k, v in d.items()} for m, d in ver.items()})

# 4) NOAA CPC prognostic discussions
cpc = {}
for nm, u in [("6-10/8-14 day", "https://www.cpc.ncep.noaa.gov/products/predictions/610day/fxus06.html"),
              ("week 3-4", "https://www.cpc.ncep.noaa.gov/products/predictions/WK34/texts/week34fcst.txt"),  # was texts/sfmd.html (404)
              ("30-day (Dec)", "https://www.cpc.ncep.noaa.gov/products/predictions/30day/fxus07.html"),
              ("90-day", "https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus05.html")]:
    try:
        r = requests.get(u, headers=H, timeout=60)
        import re, html as h_
        txt = re.sub(r"<[^>]+>", " ", r.text); txt = h_.unescape(re.sub(r"\s+\n", "\n", txt))
        cpc[nm] = {"url": u, "status": r.status_code, "text": re.sub(r"[ \t]+", " ", txt)[:20000]}
    except Exception as e:
        cpc[nm] = {"url": u, "error": str(e)[:200]}
json.dump(cpc, open(f"{OUT}/cpc.json", "w"), indent=1)
json.dump(log, open(f"{OUT}/fetch_log.json", "w"), indent=1)
print("done", log.keys())
