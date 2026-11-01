#!/usr/bin/env python3
"""Test de bout en bout, sans internet : faux site, faux sitemaps, faux webhook.

Vérifie : découverte via robots.txt, sitemap index + gz, filtrage des jeux,
exclusion des accessoires/jeux vidéo, première exécution silencieuse (référence),
détection d'une nouvelle page, alerte envoyée une seule fois.
"""
import gzip
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PAGES = {"urls": []}
WEBHOOKS = []


def urlset(urls):
    body = "".join(f"<url><loc>{u}</loc><lastmod>2026-10-31</lastmod></url>" for u in urls)
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/xml"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        base = f"http://127.0.0.1:{self.server.server_port}"
        if self.path == "/robots.txt":
            self._send(f"User-agent: *\nSitemap: {base}/index.xml\n", "text/plain")
        elif self.path == "/index.xml":
            self._send(
                '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<sitemap><loc>{base}/produits.xml.gz</loc></sitemap>"
                f"<sitemap><loc>{base}/blog.xml</loc></sitemap></sitemapindex>"
            )
        elif self.path == "/produits.xml.gz":
            self._send(gzip.compress(urlset(PAGES["urls"]).encode()), "application/gzip")
        elif self.path == "/blog.xml":
            self._send(urlset([f"{base}/blog/pokemon-booster-test"]))
        else:
            self.send_error(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        WEBHOOKS.append(json.loads(self.rfile.read(n)))
        self._send("ok", "text/plain")


def run(cfg, state, out):
    env = dict(os.environ, NO_PROXY="127.0.0.1", no_proxy="127.0.0.1")
    env["DISCORD_WEBHOOK"] = f"http://127.0.0.1:{PORT}/hook"
    r = subprocess.run(
        [sys.executable, "-I", str(HERE / "detector.py"), "--config", cfg, "--state-dir", state, "--out", out],
        env=env, capture_output=True, text=True,
    )
    print(r.stdout.strip())
    if r.returncode != 0:
        print(r.stderr)
        sys.exit(1)


srv = HTTPServer(("127.0.0.1", 0), H)
PORT = srv.server_port
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = f"http://127.0.0.1:{PORT}"

tmp = Path(tempfile.mkdtemp())
cfg = json.loads((HERE / "config.json").read_text())
cfg["sites"] = [{"id": "faux", "name": "Faux Magasin", "base": B}]
cfg["defaults"]["delay"] = 0
(tmp / "cfg.json").write_text(json.dumps(cfg))
args = (str(tmp / "cfg.json"), str(tmp / "state"), str(tmp / "data.json"))

# --- Passage 1 : référence -------------------------------------------------
PAGES["urls"] = [
    f"{B}/p/pokemon-display-24-boosters-ecarlate-et-violet-12345.html",   # oui
    f"{B}/p/pokemon-peluche-pikachu-30cm-555.html",                       # non (peluche)
    f"{B}/p/one-piece-card-game-booster-op09.html",                       # oui
    f"{B}/p/cyberpunk-2077-ps5-jeu-video.html",                           # non (jeu vidéo)
    f"{B}/p/cyberpunk-tcg-welcome-to-night-city-display.html",            # oui
    f"{B}/p/classeur-pokemon-ultra-pro.html",                             # non (classeur)
    f"{B}/p/lego-technic-voiture.html",                                   # non
]
print("--- passage 1 (référence, aucune alerte attendue)")
run(*args)
assert not WEBHOOKS, "aucune alerte attendue au premier passage"
d = json.loads((tmp / "data.json").read_text())
got = sorted(i["game"] for i in d["items"])
assert got == ["cyberpunk", "onepiece", "pokemon"], got
assert all(i["baseline"] for i in d["items"])
assert not any("blog" in i["url"] for i in d["items"]), "le sitemap blog doit être ignoré"

# --- Passage 2 : une nouvelle page apparaît ----------------------------------
PAGES["urls"].append(f"{B}/p/pokemon-etb-coffret-dresseur-elite-evolutions-prismatiques.html")
print("--- passage 2 (1 nouvelle page, 1 alerte attendue)")
run(*args)
assert len(WEBHOOKS) == 1, WEBHOOKS
assert "evolutions prismatiques" in WEBHOOKS[0]["content"], WEBHOOKS[0]["content"]
d = json.loads((tmp / "data.json").read_text())
assert d["items"][0]["baseline"] is False and d["items"][0]["game"] == "pokemon"

# --- Passage 3 : rien de nouveau, pas de doublon ------------------------------
print("--- passage 3 (rien de nouveau, pas de nouvelle alerte)")
run(*args)
assert len(WEBHOOKS) == 1, "pas de doublon d'alerte"

print("\nTOUS LES TESTS PASSENT")
