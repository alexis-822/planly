import http.server
import sys
import subprocess
import os
import socket
import urllib.request
import urllib.parse

PROXY_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SCRIPT_DIR, **kwargs)

    def do_GET(self):
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
        if args and isinstance(args[0], str) and "/proxy?" in args[0]:
            return
        super().log_message(format, *args)


class DualStackServer(http.server.HTTPServer):
    """Écoute IPv4 et IPv6 simultanément (dual-stack).
    Nécessaire sur Windows 11 où localhost résout vers ::1 (IPv6) en priorité.
    """
    address_family = socket.AF_INET6

    def server_bind(self):
        # IPV6_V6ONLY=0 → accepte aussi les connexions IPv4 via ::ffff:127.0.0.1
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


print(f"Server: http://localhost:8080  |  http://127.0.0.1:8080  |  http://192.168.1.15:8080")
print(f"Répertoire servi : {SCRIPT_DIR}")
DualStackServer(("::", 8080), NoCacheHandler).serve_forever()
