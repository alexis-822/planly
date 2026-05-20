"""
fetch_tides.py — Scrape maree.info et génère tides.js (7 jours)
Usage : python fetch_tides.py
Relancer une fois par semaine pour avoir 7 jours de données.
"""
import urllib.request, re, json, io, sys, datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"

PORTS = [
    {"id": 124, "nom": "Saint-Gilles-Croix-de-Vie"},
    {"id": 125, "nom": "Les Sables-d'Olonne"},
]

def parse_day(row_html, base_date, day_index):
    def split_br(cell_html):
        parts = re.split(r"<br\s*/?>", cell_html, flags=re.IGNORECASE)
        return [re.sub(r"<[^>]+>", "", p).replace("&nbsp;", "").strip() for p in parts]

    m = re.search(r'<td>(.*?)</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>', row_html, re.DOTALL)
    if not m:
        return []

    time_texts   = [t for t in split_br(m.group(1)) if t][:4]
    height_texts = [t for t in split_br(m.group(2)) if t][:4]
    coeff_texts  = split_br(m.group(3))[:4]

    types = ["BM", "PM", "BM", "PM"]
    tides = []
    for i, t in enumerate(time_texts):
        h_raw = height_texts[i] if i < len(height_texts) else None
        h_val = round(float(h_raw.replace("m", "").replace(",", ".")), 2) if h_raw else None
        coeff_raw = coeff_texts[i] if i < len(coeff_texts) else ""
        coeff_val = int(coeff_raw) if coeff_raw and coeff_raw.isdigit() else None
        tides.append({"type": types[i], "time": t, "height": h_val, "coeff": coeff_val})
    return tides

def fetch_all_days(port_id):
    url = f"https://maree.info/{port_id}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=10) as r:
        html = r.read().decode("utf-8", errors="replace")

    today = datetime.date.today()
    days = {}

    for i in range(7):
        row_match = re.search(
            r'id="MareeJours_' + str(i) + r'"[^>]*>(.*?)</tr>',
            html, re.DOTALL
        )
        if not row_match:
            continue
        date_str = (today + datetime.timedelta(days=i)).isoformat()
        tides = parse_day(row_match.group(1), today, i)
        if tides:
            days[date_str] = tides
            print(f"     J+{i} ({date_str}): {len(tides)} marées")

    return days

results = {}
today = datetime.date.today().isoformat()
print(f"Fetching marées 7 jours à partir du {today}...")

for port in PORTS:
    try:
        days = fetch_all_days(port["id"])
        results[port["id"]] = {"nom": port["nom"], "generated": today, "days": days}
        print(f"  ✅ Port {port['id']} ({port['nom']}): {len(days)} jours")
    except Exception as e:
        print(f"  ❌ Port {port['id']}: {e}")
        results[port["id"]] = {"nom": port["nom"], "generated": today, "days": {}}

out = f"// Generated {today} by fetch_tides.py\nvar TIDES_DATA = {json.dumps(results, ensure_ascii=True, indent=2)};\n"
with open("tides.js", "w", encoding="utf-8") as f:
    f.write(out)

print(f"\n✅ tides.js généré ({len(results)} ports, 7 jours)")
