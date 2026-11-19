#!/usr/bin/env python3
"""Minimal demo server: upload an image, run the lexicographic decode, return the trace.

Stdlib + Pillow only. Run with an interpreter that has a working Pillow:

    /usr/bin/python3 -I server.py 8765
"""
import base64, json, os, sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import decode_lib

STATIC = {"": "index.html", "/": "index.html",
          "/index.html": "index.html",
          "/lexicographic.html": "lexicographic.html"}

# Explicit download allow-list. Never derive these from the request path.
SAMPLES = {"/sample/unmasked.jpg": "samples/accredo-legacy-unmasked.jpg",
           "/sample/masked.png": "samples/accredo-legacy-masked.png"}
TOKEN = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _authed(self):
        if not TOKEN:
            return True
        h = self.headers.get("Authorization", "")
        if h.startswith("Bearer ") and h[7:].strip() == TOKEN:
            return True
        q = self.path.split("?", 1)[1] if "?" in self.path else ""
        return any(p == f"token={TOKEN}" for p in q.split("&"))

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._authed():
            return self._send(401, {"error": "unauthorized"})
        path = self.path.split("?")[0]
        if path == "/health":
            return self._send(200, {"ok": True})
        if path in SAMPLES:
            fn = SAMPLES[path]
            with open(os.path.join(HERE, fn), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type",
                             "image/png" if fn.endswith(".png") else "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition",
                             'attachment; filename="%s"' % os.path.basename(fn))
            self.end_headers()
            self.wfile.write(body)
            return
        name = STATIC.get(path)
        if not name:
            return self._send(404, {"error": "not found"})
        fp = os.path.join(HERE, name)
        with open(fp, "rb") as f:
            self._send(200, f.read(), "text/html; charset=utf-8")

    def do_POST(self):
        if not self._authed():
            return self._send(401, {"error": "unauthorized"})
        if self.path != "/api/decode":
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n) or b"{}")
            data = payload.get("image_b64", "")
            if "," in data:
                data = data.split(",", 1)[1]
            raw = base64.b64decode(data)
            box = payload.get("box")
            out = decode_lib.decode(raw, box=box,
                                    drug=payload.get("drug", "adalimumab"),
                                    sens=int(payload.get("sens", 28)),
                                    ocr=bool(payload.get("ocr", False)))
            return self._send(200, out)
        except Exception as e:
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    import argparse, socket
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1",
                    help="127.0.0.1 = this machine only; 0.0.0.0 = every interface")
    ap.add_argument("--token", default=None,
                    help="optional shared secret; accepted as ?token= or Authorization: Bearer")
    a = ap.parse_args()
    TOKEN = a.token

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        lan = s.getsockname()[0]
    except Exception:
        lan = "?"
    finally:
        s.close()

    print(f"serving on http://127.0.0.1:{a.port}")
    if a.host == "0.0.0.0":
        print(f"also reachable at http://{lan}:{a.port}")
    print(f"auth: {'token required' if TOKEN else 'NONE - open to anyone who can reach the port'}")
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()
