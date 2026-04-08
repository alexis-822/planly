import http.server
import sys

class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

print("Server: http://0.0.0.0:8080 (no-cache)")
http.server.HTTPServer(("0.0.0.0", 8080), NoCacheHandler).serve_forever()
