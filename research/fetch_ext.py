"""Extended-range weather for the natgas desk: weeks 1-5 gas-weighted HDD beyond the 15-day ensembles.

Why: the 15-day ensembles (fetch_wx2.py) stop around day 14-15. Cold-risk calls (SSW / negative AO / -EPO) usually sit
in days 15-35, and the market trades that horizon well before the 15-day models show it. This file adds:

  GEFS 35-day ensemble (Open-Meteo model gfs05, 31 members)            -> per-member weekly HDD anomalies, weeks 1-5
  ECMWF extended-range ensemble (EC46), if Open-Meteo serves it          -> same, up to 46 days
  CFSv2 (Open-Meteo seasonal API), if reachable                          -> weekly anomalies, weeks 1-6

Writes data/research/hdd_ext.json and data/research/hdd_ext_log.json. Runs after fetch_wx2.py on GitHub Actions;
a failure here never touches the other weather files. Same 21 metros, weights and 10-yr normal as fetch_wx2.py.
"""
import json, os, time, datetime as dt
import requests

OUT = "data/research"; os.makedirs(OUT, exist_ok=True)
H = {"User-Agent": "BMR-Com energy desk research (github.com/BMR-Com/natgas)"}
# same 21 metros and weights as fetch_wx2.py (keep in sync)
CITIES = [("Chicago",41.88,-87.63,.105),("New York",40.71,-74.01,.100),("Detroit",42.33,-83.05,.058),("Philadelphia",39.95,-75.17,.048),
 ("Boston",42.36,-71.06,.045),("Minneapolis",44.98,-93.27,.045),("Cleveland",41.50,-81.69,.038),("Pittsburgh",40.44,-79.996,.033),
 ("St. Louis",38.63,-90.20,.035),("Kansas City",39.10,-94.58,.032),("Indianapolis",39.77,-86.16,.030),("Cincinnati",39.10,-84.51,.030),
 ("Denver",39.74,-104.99,.038),("Salt Lake City",40.76,-111.89,.022),("Washington DC",38.91,-77.04,.038),("Atlanta",33.75,-84.39,.048),
 ("Charlotte",35.23,-80.84,.028),("Nashville",36.16,-86.78,.026),("Dallas",32.78,-96.80,.060),("Houston",29.76,-95.37,.053),("Seattle",47.61,-122.33,.028)]
LAT = ",".join(str(c[1]) for c in CITIES); LON = ",".join(str(c[2]) for c in CITIES)
WSUM = sum(c[3] for c in CITIES)
today = dt.date.today()
log = {"ok": [], "fail": []}


def get(url, params, tries=2, timeout=240):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=H, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            log["fail"].append([url, params.get("models"), r.status_code, r.text[:200]])
            if r.status_code in (400, 404):
                return None
        except Exception as e:
            log["fail"].append([url, params.get("models"), str(e)[:200]])
        time.sleep(20 * (i + 1))
    return None


# 10-yr daily normal (2016-2025), 7-day smoothed, from hdd_hist.json
hist = json.load(open(f"{OUT}/hdd_hist.json"))["daily"]
by = {}
for d, (h, c) in hist.items():
    if "2016-01-01" <= d < "2026-01-01":
        by.setdefault(d[5:], []).append(h)
keys = sorted(by); raw = {k: sum(v) / len(v) for k, v in by.items()}
normal = {k: sum(raw[keys[(i + j) % len(keys)]] for j in range(-3, 4)) / 7 for i, k in enumerate(keys)}


def member_daily(js, prefer=("temperature_2m_mean",), minmax=("temperature_2m_max", "temperature_2m_min")):
    """Open-Meteo multi-location daily response -> {member_key: {date: gas-weighted HDD}}."""
    js = js if isinstance(js, list) else [js]
    dly0 = js[0].get("daily", {})
    dates = dly0.get("time", [])
    mean_keys = sorted(k for k in dly0 if any(k.startswith(p) for p in prefer))
    use_minmax = not mean_keys
    if use_minmax:
        mx = sorted(k for k in dly0 if k.startswith(minmax[0]))
        pairs = [(k, k.replace(minmax[0], minmax[1])) for k in mx]
    else:
        pairs = [(k, None) for k in mean_keys]
    out = {}
    for a, b in pairs:
        mk = a.split("_member")[-1] if "_member" in a else "ctl"
        daily = {}
        for i, d in enumerate(dates):
            h = w = 0.0
            for (nm, la, lo, wt), x in zip(CITIES, js):
                dl = x.get("daily", {})
                va = (dl.get(a) or [None] * len(dates))[i]
                vb = (dl.get(b) or [None] * len(dates))[i] if b else None
                if va is None or (b and vb is None):
                    continue
                t = (va + vb) / 2 if b else va
                h += wt * max(0.0, 65 - t); w += wt
            if w > 0.8 * WSUM:
                daily[d] = round(h / w, 2)
        if daily:
            out[mk] = daily
    return out


def weekly(members):
    """per-member daily HDD -> weekly anomaly buckets vs 10-yr normal; week 1 starts today."""
    weeks = []
    for k in range(7):
        a = today + dt.timedelta(days=7 * k); b = a + dt.timedelta(days=6)
        days = [(a + dt.timedelta(days=i)).isoformat() for i in range(7)]
        an = []
        for m in members.values():
            if all(d in m for d in days):
                an.append(round(sum(m[d] - normal[d[5:]] for d in days), 1))
        if len(an) < 3:
            break
        an.sort(); n = len(an)
        q = lambda p: an[min(n - 1, max(0, int(round(p * (n - 1)))))]
        weeks.append({"week": k + 1, "from": days[0], "to": days[-1], "members": n,
                      "normal_hdd": round(sum(normal[d[5:]] for d in days), 1),
                      "mean": round(sum(an) / n, 1), "p10": q(.1), "p50": q(.5), "p90": q(.9),
                      "share_cold": round(sum(x > 0 for x in an) / n, 3), "share_cold20": round(sum(x > 20 for x in an) / n, 3)})
    return weeks


ext = {}
# 1) GEFS 35-day and ECMWF extended via the ensemble API (daily mean temperature per member)
for name, model, days in [("GEFS 35-day", "gfs05", 35), ("ECMWF extended (EC46)", "ecmwf_ifs_ec46", 46),
                          ("ECMWF extended (EC46)", "ecmwf_ec46", 46), ("ECMWF extended (EC46)", "ecmwf_ifs025_ensemble_extended", 46)]:
    if name in ext:
        continue
    js = get("https://ensemble-api.open-meteo.com/v1/ensemble", {"latitude": LAT, "longitude": LON, "daily": "temperature_2m_mean",
             "temperature_unit": "fahrenheit", "timezone": "America/New_York", "forecast_days": days, "models": model})
    if not js:
        continue
    m = member_daily(js)
    wk = weekly(m)
    if wk:
        ext[name] = {"model": model, "members": len(m), "weeks": wk,
                     "daily_mean": {d: round(sum(v[d] for v in m.values() if d in v) / len(m), 2) for d in sorted(set().union(*m.values()))}}
        log["ok"].append([name, model, len(m), len(wk)])
    time.sleep(15)

# 2) CFSv2 through the seasonal API (members, min/max -> mean)
for model in ["cfsv2", None]:
    p = {"latitude": LAT, "longitude": LON, "daily": "temperature_2m_max,temperature_2m_min", "temperature_unit": "fahrenheit",
         "timezone": "America/New_York", "forecast_days": 45}
    if model:
        p["models"] = model
    js = get("https://seasonal-api.open-meteo.com/v1/seasonal", p)
    if not js:
        continue
    m = member_daily(js, prefer=("temperature_2m_mean",))
    wk = weekly(m)
    if wk:
        ext["CFSv2"] = {"model": model or "default", "members": len(m), "weeks": wk}
        log["ok"].append(["CFSv2", model, len(m), len(wk)]); break

json.dump({"generated": dt.datetime.utcnow().isoformat(timespec="minutes"), "base_f": 65,
           "normal": "2016-2025 daily mean, 7-day smoothed; anomalies are weekly totals (HDD), + = colder than normal",
           "models": ext}, open(f"{OUT}/hdd_ext.json", "w"), separators=(",", ":"))
json.dump(log, open(f"{OUT}/hdd_ext_log.json", "w"), indent=1)
print("ok", log["ok"]); print("fails", len(log["fail"]))
