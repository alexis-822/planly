"""
fetch_tides.py — Scrape maree.info et génère tides.js
Usage : python fetch_tides.py
Relancer chaque matin (ou via scheduler) pour avoir les données du jour.
"""
import urllib.request, re, json, io, sys, datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"

PORTS = [
    {"id": 124, "nom": "Saint-Gilles-Croix-de-Vie"},
    {"id": 125, "nom": "Les Sables-d'Olonne"},
]

def fetch_and_parse(port_id):
    url = f"https://maree.info/{port_id}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=10) as r:
        html = r.read().decode("utf-8", errors="replace")

    # Parse la structure HTML : <tr id="MareeJours_0"><td>HHhMM<br>...<td>H,HHm<br>...<td>&nbsp;<br><b>coeff</b>
    row_match = re.search(r'id="MareeJours_0"[^>]*>.*?<td>(.*?)</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>', html, re.DOTALL)
    if not row_match:
        print(f"  ⚠️  Port {port_id}: structure HTML non trouvée, fallback regex")
        times = re.findall(r"(\d{1,2}h\d{2})", html)[:4]
        heights = [float(h.replace(",", ".")) for h in re.findall(r"(\d[,\.]\d{2})\s*m", html)[:4]]
        types = ["BM","PM","BM","PM"]
        return [{"type": types[i], "time": times[i], "height": round(heights[i], 2) if i < len(heights) else None, "coeff": None} for i in range(len(times))]

    def split_br(cell_html):
        parts = re.split(r"<br\s*/?>", cell_html, flags=re.IGNORECASE)
        return [re.sub(r"<[^>]+>", "", p).replace("&nbsp;", "").strip() for p in parts]

    time_texts   = [t for t in split_br(row_match.group(1)) if t][:4]
    height_texts = [t for t in split_br(row_match.group(2)) if t][:4]
    coeff_texts  = split_br(row_match.group(3))[:4]

    types = ["BM","PM","BM","PM"]
    tides = []
    for i, t in enumerate(time_texts):
        h_raw = height_texts[i] if i < len(height_texts) else None
        h_val = round(float(h_raw.replace("m","").replace(",",".")), 2) if h_raw else None
        coeff_raw = coeff_texts[i] if i < len(coeff_texts) else ""
        coeff_val = int(coeff_raw) if coeff_raw and coeff_raw.isdigit() else None
        tides.append({"type": types[i], "time": t, "height": h_val, "coeff": coeff_val})
    return tides

results = {}
today = datetime.date.today().isoformat()
print(f"Fetching marées pour le {today}...")

for port in PORTS:
    try:
        tides = fetch_and_parse(port["id"])
        results[port["id"]] = {"nom": port["nom"], "date": today, "tides": tides}
        print(f"  ✅ Port {port['id']} ({port['nom']}): {len(tides)} marées")
        for t in tides:
            coeff = f" coeff {t['coeff']}" if t['coeff'] else ""
            print(f"     {t['type']} {t['time']} — {t['height']}m{coeff}")
    except Exception as e:
        print(f"  ❌ Port {port['id']}: {e}")
        results[port["id"]] = {"nom": port["nom"], "date": today, "tides": []}

# Génère tides.js
out = f"// Generated {today} by fetch_tides.py\nvar TIDES_DATA = {json.dumps(results, ensure_ascii=True, indent=2)};\n"
with open("tides.js", "w", encoding="utf-8") as f:
    f.write(out)

print(f"\n✅ tides.js généré ({len(results)} ports)")
