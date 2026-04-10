import http.server
import sys
import subprocess
import os
import urllib.request
import urllib.parse

PROXY_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"

def refresh_tides():
    script = os.path.join(os.path.dirname(__file__), "fetch_tides.py")
    try:
        result = subprocess.run([sys.executable, script], capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            print("Marées mises à jour (tides.js)")
        else:
            print("Erreur fetch_tides.py:", result.stderr[:200])
    except Exception as e:
        print("fetch_tides.py non lancé:", e)

refresh_tides()

class NoCacheHandler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):
        # Endpoint proxy : /proxy?url=https://...
        if self.path.startswith("/proxy?"):
            qs = urllib.parse.parse_qs(self.path[7:])
            target = qs.get("url", [None])[0]
            if not target:
                self.send_error(400, "Missing url param")
                return
            try:
                req = urllib.request.Request(target, headers={"User-Agent": PROXY_UA, "Accept": "text/html"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    body = resp.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_error(502, str(e))
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, format, *args):
        # Silence proxy logs, keep others
        if "/proxy?" not in args[0]:
            super().log_message(format, *args)

print("Server: http://0.0.0.0:8080 (no-cache + /proxy endpoint)")
http.server.HTTPServer(("0.0.0.0", 8080), NoCacheHandler).serve_forever()
