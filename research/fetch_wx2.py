"""Extra weather inputs for the natgas desk (runs on GitHub Actions after fetch_research.py).

Writes data/research/:
  hdd_members.json  per-member 15-16 day gas-weighted HDD for the GFS (GEFS), ECMWF ENS and ECMWF AIFS ensembles,
                    with the 10-yr normal and the share of members colder/warmer than normal by more than 30 HDD
  vortex.json       stratospheric polar vortex: GFS forecast zonal-mean 10 hPa wind at 60N (from 36 points around the circle),
                    plus NOAA CPC daily AO / NAO / PNA observed values and ensemble forecasts where the files are reachable
  snow.json         NOAA NOHRSC national snow analysis: % of the Lower 48 covered by snow and mean depth, today and
                    the same date in earlier years
  cpc_dd.json       NOAA CPC weekly population-weighted heating degree days (US total line)
  wx2_log.json      what worked and what did not
"""
import json, os, re, time, math, datetime as dt
import requests

OUT = "data/research"; os.makedirs(OUT, exist_ok=True)
H = {"User-Agent": "BMR-Com energy desk research (github.com/BMR-Com/natgas)"}
CITIES = [("Chicago",41.88,-87.63,.105),("New York",40.71,-74.01,.100),("Detroit",42.33,-83.05,.058),("Philadelphia",39.95,-75.17,.048),
 ("Boston",42.36,-71.06,.045),("Minneapolis",44.98,-93.27,.045),("Cleveland",41.50,-81.69,.038),("Pittsburgh",40.44,-79.996,.033),
 ("St. Louis",38.63,-90.20,.035),("Kansas City",39.10,-94.58,.032),("Indianapolis",39.77,-86.16,.030),("Cincinnati",39.10,-84.51,.030),
 ("Denver",39.74,-104.99,.038),("Salt Lake City",40.76,-111.89,.022),("Washington DC",38.91,-77.04,.038),("Atlanta",33.75,-84.39,.048),
 ("Charlotte",35.23,-80.84,.028),("Nashville",36.16,-86.78,.026),("Dallas",32.78,-96.80,.060),("Houston",29.76,-95.37,.053),("Seattle",47.61,-122.33,.028)]
LAT = ",".join(str(c[1]) for c in CITIES); LON = ",".join(str(c[2]) for c in CITIES)
log = {"ok": [], "fail": []}
today = dt.date.today()


def get(url, params=None, tries=3, as_json=True, timeout=180):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=H, timeout=timeout)
            if r.status_code == 200:
                return r.json() if as_json else r.text
            log["fail"].append([url, r.status_code, r.text[:160]])
            if r.status_code in (400, 404):
                return None
        except Exception as e:
            log["fail"].append([url, str(e)[:160]])
        time.sleep(20 * (i + 1))
    return None


def multi(js):
    return js if isinstance(js, list) else [js]


# 10-yr daily normal from the history file written by fetch_research.py
normal = {}
try:
    hist = json.load(open(f"{OUT}/hdd_hist.json"))["daily"]
    by = {}
    for d, (h, c) in hist.items():
        if "2016-01-01" <= d < "2026-01-01":
            by.setdefault(d[5:], []).append(h)
    keys = sorted(by)
    raw = {k: sum(v) / len(v) for k, v in by.items()}
    for i, k in enumerate(keys):  # 7-day centred smoothing
        w = [raw[keys[(i + j) % len(keys)]] for j in range(-3, 4)]
        normal[k] = sum(w) / len(w)
except Exception as e:
    log["fail"].append(["normal", str(e)])


# 1) ensemble members -> gas-weighted HDD per member
def members(model, days):
    js = get("https://ensemble-api.open-meteo.com/v1/ensemble", {"latitude": LAT, "longitude": LON, "hourly": "temperature_2m",
             "temperature_unit": "fahrenheit", "timezone": "America/New_York", "forecast_days": days, "models": model})
    if not js:
        return None
    js = multi(js)
    keys = sorted({k for k in js[0]["hourly"] if k.startswith("temperature_2m")})
    times = js[0]["hourly"]["time"]
    dates = sorted({t[:10] for t in times})
    out = {}
    for k in keys:
        daily = {}
        for d in dates:
            h = w = 0
            for (nm, la, lo, wt), x in zip(CITIES, js):
                vals = [v for t, v in zip(x["hourly"]["time"], x["hourly"].get(k, [])) if t[:10] == d and v is not None]
                if len(vals) >= 20:
                    h += wt * max(0, 65 - sum(vals) / len(vals)); w += wt
            if w > 0.8 * sum(c[3] for c in CITIES):
                daily[d] = round(h / w, 2)
        out[k] = daily
    return out


ens = {}
for name, model, days in [("GEFS (GFS ensemble)", "gfs025", 16), ("ECMWF ENS", "ecmwf_ifs025", 15),
                          ("ECMWF AIFS ENS", "ecmwf_aifs025", 15), ("ECMWF AIFS ENS", "ecmwf_aifs025_ensemble", 15)]:
    if name in ens:
        continue
    m = members(model, days)
    if not m:
        continue
    log["ok"].append(["members", model, len(m)])
    full = [v for v in m.values() if v]
    common = sorted(d for d in set.intersection(*[set(v) for v in full]) if d >= today.isoformat() and d[5:] in normal) if full else []
    if not common:
        continue
    nrm = sum(normal[d[5:]] for d in common)
    tots = sorted(round(sum(v[d] for d in common) - nrm, 1) for v in m.values() if all(d in v for d in common))
    n = len(tots)
    if not n:
        continue
    q = lambda p: tots[min(n - 1, max(0, int(round(p * (n - 1)))))]
    ens[name] = {"model": model, "members": n, "days": len(common), "from": common[0], "to": common[-1], "normal_hdd": round(nrm, 1),
                 "anom_by_member": tots, "p10": q(.1), "p50": q(.5), "p90": q(.9), "mean": round(sum(tots) / n, 1),
                 "share_cold30": round(sum(t > 30 for t in tots) / n, 3), "share_warm30": round(sum(t < -30 for t in tots) / n, 3),
                 "daily_mean": {d: round(sum(v[d] for v in m.values() if d in v) / n, 2) for d in common},
                 "daily_normal": {d: round(normal[d[5:]], 2) for d in common}}
    time.sleep(15)
json.dump({"generated": dt.datetime.utcnow().isoformat(timespec="minutes"), "base_f": 65, "normal": "2016-2025 daily mean, 7-day smoothed",
           "ensembles": ens}, open(f"{OUT}/hdd_members.json", "w"), separators=(",", ":"))

# 2) polar vortex: zonal-mean u at 10 hPa, 60N, from GFS (36 longitudes)
vort = {}
lons = list(range(-180, 180, 10))
for model in ["gfs_seamless", "ecmwf_ifs025"]:
    js = get("https://api.open-meteo.com/v1/forecast", {"latitude": ",".join(["60"] * len(lons)), "longitude": ",".join(map(str, lons)),
             "hourly": "wind_speed_10hPa,wind_direction_10hPa", "wind_speed_unit": "ms", "forecast_days": 16, "past_days": 10,
             "timezone": "UTC", "models": model})
    if not js:
        continue
    js = multi(js)
    t = js[0]["hourly"]["time"]; ser = {}
    for i, ts in enumerate(t):
        if not ts.endswith("12:00"):
            continue
        us = []
        for x in js:
            s = x["hourly"].get("wind_speed_10hPa", [None] * len(t))[i]; d = x["hourly"].get("wind_direction_10hPa", [None] * len(t))[i]
            if s is not None and d is not None:
                us.append(-s * math.sin(math.radians(d)))
        if len(us) >= 30:
            ser[ts[:10]] = round(sum(us) / len(us), 1)
    if ser:
        vort[model] = ser; log["ok"].append(["vortex", model, len(ser)])
    time.sleep(10)

# CPC teleconnection indices: daily observed + GEFS forecasts (try the published text/csv files)
tele = {}
CPC = "https://www.cpc.ncep.noaa.gov/products/precip/CWlink"
for idx, page in [("ao", f"{CPC}/daily_ao_index/ao.shtml"), ("nao", f"{CPC}/pna/nao.shtml"), ("pna", f"{CPC}/pna/pna.shtml")]:
    rec = {}
    html = get(page, as_json=False, tries=2)
    if html:
        links = sorted(set(re.findall(r'href="([^"]+\.(?:txt|csv|ascii))"', html, re.I)))
        rec["links"] = links[:40]
    cands = {"obs": [f"https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.{idx}.cdas.z{'1000' if idx == 'ao' else '500'}.19500101_current.csv"],
             "gefs": [f"https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.{idx}.gefs.z{'1000' if idx == 'ao' else '500'}.120days.csv",
                      f"{CPC}/daily_ao_index/{idx}.gefs.z1000.120days.csv"]}
    for lk in rec.get("links", []):
        u = lk if lk.startswith("http") else (page.rsplit("/", 1)[0] + "/" + lk)
        if "fcst" in lk.lower() or "gefs" in lk.lower() or "ens" in lk.lower():
            cands["gefs"].insert(0, u)
    for kind, urls in cands.items():
        for u in urls:
            txt = get(u, as_json=False, tries=1, timeout=60)
            if txt and len(txt) > 200:
                lines = [l for l in txt.strip().splitlines() if l.strip()]
                rec[kind] = {"url": u, "tail": lines[-140:] if kind == "obs" else lines[:400]}
                log["ok"].append(["tele", idx, kind, u]); break
    tele[idx] = rec
json.dump({"generated": dt.datetime.utcnow().isoformat(timespec="minutes"), "u10_60N_ms": vort,
           "note": "zonal-mean zonal wind at 10 hPa, 60N, 12z; climatology in Nov-Jan is roughly +20 to +40 m/s; below 0 = major sudden stratospheric warming",
           "teleconnections": tele}, open(f"{OUT}/vortex.json", "w"), indent=0)

# 3) NOHRSC national snow analysis
snow = {}
for back in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]:
    d = today.replace(year=today.year - back) if back else today
    if back == 0:
        d = today
    html = get("https://www.nohrsc.noaa.gov/nsa/index.html", {"year": d.year, "month": d.month, "day": d.day, "units": "e", "region": "National"},
               as_json=False, tries=2, timeout=60)
    if not html:
        continue
    txt = re.sub(r"<[^>]+>", " ", html); txt = re.sub(r"\s+", " ", txt)
    a = re.search(r"Area Covered By Snow:\s*([\d.]+)\s*%", txt, re.I)
    dep = re.search(r"Snow Depth:\s*Average:\s*([\d.]+)\s*in", txt, re.I)
    if a:
        snow[d.isoformat()] = {"cover_pct": float(a.group(1)), "avg_depth_in": float(dep.group(1)) if dep else None}
    elif back == 0:
        log["fail"].append(["nohrsc parse", txt[:300]])
    time.sleep(3)
if snow:
    log["ok"].append(["snow", len(snow)])
json.dump({"generated": dt.datetime.utcnow().isoformat(timespec="minutes"), "source": "NOAA NOHRSC National Snow Analysis, Lower 48",
           "by_date": snow}, open(f"{OUT}/snow.json", "w"), indent=0)

# 4) CPC weekly population-weighted degree days
dd = {}
for k, u in [("heating_weekly", "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/cdus/degree_days/hfstwpws.txt")]:
    txt = get(u, as_json=False, tries=2, timeout=60)
    if txt:
        lines = txt.splitlines()
        dd[k] = {"url": u, "head": lines[:14], "us": [l for l in lines if re.match(r"\s*(UNITED STATES|CONUS|U\.?S\.?)\b", l, re.I)]}
        log["ok"].append(["cpc dd", k])
json.dump(dd, open(f"{OUT}/cpc_dd.json", "w"), indent=0)
json.dump(log, open(f"{OUT}/wx2_log.json", "w"), indent=1)
print(json.dumps(log["ok"]))
print("fails", len(log["fail"]))
