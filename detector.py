#!/usr/bin/env python3
"""TCG Watch : repère les nouvelles pages produits TCG dans les sitemaps publics.

Principe : pour chaque enseigne, on lit robots.txt pour trouver les sitemaps,
on parcourt les sitemaps (index inclus), on garde les URLs qui parlent d'un jeu
suivi (Pokémon, One Piece, Cyberpunk...) ET d'un produit carte (booster, display,
coffret...), puis on compare avec ce qu'on avait déjà vu.

Aucune dépendance externe : uniquement la bibliothèque standard Python.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (compatible; TCGWatch/1.0; veille personnelle de sitemaps publics)"
MAX_ITEMS = 3000
MAX_STATE_URLS = 20000

SKIP_HINT = re.compile(r"blog|cms|image|video|magasin|store|brand|marque|faq", re.I)
PRIO_HINT = re.compile(r"product|produit|article|item|catalog|categor|jeu|toy|jouet|carte|tcg", re.I)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# Réseau
# --------------------------------------------------------------------------
def http_get(url: str, timeout: int = 30, retries: int = 1) -> bytes:
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "gzip"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            if data[:2] == b"\x1f\x8b":
                data = gzip.decompress(data)
            return data
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5)
    assert last is not None
    raise last


def post_json(url: str, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json", "User-Agent": UA}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()


# --------------------------------------------------------------------------
# Sitemaps
# --------------------------------------------------------------------------
def parse_sitemap(data: bytes):
    root = ET.fromstring(data)
    kind = "index" if root.tag.lower().endswith("sitemapindex") else "urlset"
    out = []
    for el in root:
        loc = lastmod = None
        for c in el:
            tag = c.tag.split("}")[-1]
            if tag == "loc":
                loc = (c.text or "").strip()
            elif tag == "lastmod":
                lastmod = (c.text or "").strip()
        if loc:
            out.append((loc, lastmod))
    return kind, out


def norm(text: str) -> str:
    text = urllib.parse.unquote(text).lower()
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def exclude_for(site: dict, rules: dict) -> str:
    extra = site.get("exclude")
    return rules["exclude"] + ("|" + extra if extra else "")


def classify(url: str, rules: dict, exclude: str | None = None):
    p = urllib.parse.urlsplit(url)
    text = norm(p.path + " " + p.query)
    if re.search(exclude or rules["exclude"], text):
        return None
    for g in rules["games"]:
        if re.search(g["pattern"], text) and re.search(g.get("context", rules["context"]), text):
            return g["id"]
    return None


def title_from_url(url: str) -> str:
    """Titre lisible : on prend le segment d'adresse qui contient le plus de vrais mots
    (les identifiants du type pr-37fa6180-... ou 88013-... sont ignorés)."""
    path = urllib.parse.urlsplit(url).path.rstrip("/")
    best, best_score = "", 0
    for seg in path.split("/"):
        seg = urllib.parse.unquote(seg)
        seg = re.sub(r"\.(html?|php|aspx?)$", "", seg, flags=re.I)
        tokens = [t for t in re.split(r"[-_+\s]+", seg) if t]
        words = [t for t in tokens if re.fullmatch(r"[A-Za-zÀ-ÿ']{3,}", t)]
        if len(words) < 2 or len(words) < best_score:
            continue
        keep = [t for t in tokens if not re.fullmatch(r"[0-9a-f]{8,}|\d{6,}", t, re.I)]
        if keep and keep[0].isdigit():
            keep = keep[1:]
        best, best_score = " ".join(keep), len(words)
    if not best:
        return url
    return best[:1].upper() + best[1:]


def crawl_site(site: dict, defaults: dict, rules: dict, max_sitemaps: int | None = None):
    """Retourne (matches, nb_urls_vues, erreurs, nb_sitemaps_lus)."""
    base = site["base"].rstrip("/")
    budget = site.get("time_budget", defaults.get("time_budget", 300))
    cap = max_sitemaps or site.get("max_sitemaps", defaults.get("max_sitemaps", 80))
    delay = site.get("delay", defaults.get("delay", 0.6))
    deadline = time.time() + budget
    errors: list[str] = []
    exclude = exclude_for(site, rules)

    roots = list(site.get("sitemaps", []))
    if not roots:
        try:
            txt = http_get(base + "/robots.txt").decode("utf-8", "replace")
            roots = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", txt)
        except Exception as e:  # noqa: BLE001
            errors.append(f"robots.txt: {e}")
        if not roots:
            roots = [base + "/sitemap.xml", base + "/sitemap_index.xml"]

    queue = [(u, 0) for u in roots]
    seen_maps: set[str] = set()
    matches: dict[str, dict] = {}
    total = 0
    fetched = 0
    while queue and fetched < cap and time.time() < deadline:
        u, depth = queue.pop(0)
        if u in seen_maps:
            continue
        seen_maps.add(u)
        try:
            data = http_get(u)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{u}: {e}")
            continue
        fetched += 1
        try:
            kind, entries = parse_sitemap(data)
        except ET.ParseError as e:
            errors.append(f"{u}: XML invalide ({e})")
            continue
        if kind == "index":
            if depth < 3:
                children = [loc for loc, _ in entries if not SKIP_HINT.search(urllib.parse.urlsplit(loc).path)]
                children.sort(key=lambda s: 0 if PRIO_HINT.search(s) else 1)
                queue.extend((c, depth + 1) for c in children)
                queue.sort(key=lambda t: t[1])
        else:
            for loc, lastmod in entries:
                total += 1
                game = classify(loc, rules, exclude)
                if game:
                    matches[loc] = {"game": game, "lastmod": lastmod}
        time.sleep(delay)
    return matches, total, errors, fetched


# --------------------------------------------------------------------------
# Traitement d'une enseigne
# --------------------------------------------------------------------------
def process_site(site: dict, cfg: dict, state_dir: Path):
    matches, total, errors, fetched = crawl_site(site, cfg["defaults"], cfg["rules"])
    status = {
        "name": site["name"],
        "ok": fetched > 0 and total > 0,
        "sitemaps_read": fetched,
        "urls_seen": total,
        "matches": len(matches),
        "last_run": now_iso(),
        "error": errors[0] if errors and fetched == 0 else None,
    }
    state_file = state_dir / f"{site['id']}.json"
    state = {"baselined": False, "urls": []}
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text("utf-8"))
        except json.JSONDecodeError:
            pass

    if not status["ok"]:
        # Pas de données fiables : on ne touche pas à l'état, on signale juste l'échec.
        return site, status, [], state

    known = set(state.get("urls", []))
    baseline = not state.get("baselined", False)
    new_items = []
    for url, meta in matches.items():
        if url in known:
            continue
        new_items.append(
            {
                "url": url,
                "title": title_from_url(url),
                "site": site["id"],
                "site_name": site["name"],
                "game": meta["game"],
                "lastmod": meta["lastmod"],
                "first_seen": now_iso(),
                "baseline": baseline,
            }
        )
    merged = sorted(known | set(matches))[-MAX_STATE_URLS:]
    state = {"baselined": True, "urls": merged, "updated": now_iso()}
    return site, status, new_items, state


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------
def build_message(items: list[dict], games: dict[str, str]):
    lines = []
    for it in items[:12]:
        lines.append(f"• [{games.get(it['game'], it['game'])}] {it['site_name']} : {it['title']}\n{it['url']}")
    if len(items) > 12:
        lines.append(f"... et {len(items) - 12} autre(s)")
    title = f"TCG Watch : {len(items)} nouvelle(s) page(s)"
    return title, "\n\n".join(lines)


def notify(items: list[dict], games: dict[str, str]) -> list[str]:
    if not items:
        return []
    title, text = build_message(items, games)
    sent = []
    pwa_url = os.environ.get("PWA_URL") or items[0]["url"]
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
        try:
            post_json(server, {"topic": topic, "title": title, "message": text[:3500], "click": pwa_url, "priority": 4})
            sent.append("ntfy")
        except Exception as e:  # noqa: BLE001
            print(f"[notif] ntfy a échoué : {e}", file=sys.stderr)
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token:
        # Un canal général (TELEGRAM_CHAT_ID, reçoit tout) et/ou un canal par jeu
        # (TELEGRAM_CHAT_ID_POKEMON, TELEGRAM_CHAT_ID_ONEPIECE, TELEGRAM_CHAT_ID_CYBERPUNK...).
        targets: dict[str, dict[str, dict]] = {}
        general = os.environ.get("TELEGRAM_CHAT_ID")
        if general:
            targets.setdefault(general, {}).update({it["url"]: it for it in items})
        for gid in games:
            chat = os.environ.get(f"TELEGRAM_CHAT_ID_{gid.upper()}")
            if chat:
                targets.setdefault(chat, {}).update({it["url"]: it for it in items if it["game"] == gid})
        api = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
        for chat, bucket in targets.items():
            if not bucket:
                continue
            t, body = build_message(list(bucket.values()), games)
            try:
                post_json(
                    f"{api}/bot{token}/sendMessage",
                    {"chat_id": chat, "text": f"{t}\n\n{body}"[:4000], "disable_web_page_preview": True},
                )
                sent.append(f"telegram {chat}")
            except Exception as e:  # noqa: BLE001
                print(f"[notif] Telegram {chat} a échoué : {e}", file=sys.stderr)
    hook = os.environ.get("DISCORD_WEBHOOK")
    if hook:
        try:
            post_json(hook, {"content": f"**{title}**\n\n{text}"[:1900]})
            sent.append("discord")
        except Exception as e:  # noqa: BLE001
            print(f"[notif] Discord a échoué : {e}", file=sys.stderr)
    return sent


# --------------------------------------------------------------------------
# Suivi de pages précises (disponibilité + prix)
# --------------------------------------------------------------------------
# Sur Philibert, le formulaire « Prévenez-moi lorsque le produit est disponible »
# n'existe que tant que le produit est en rupture.
WATCH_OUT_HTML = re.compile(
    r"ajax/product/\d+/\d+/mail_alert|Prévenez-moi lorsque le produit est disponible", re.I
)
WATCH_OUT_SCHEMA = re.compile(r"OutOfStock|SoldOut|Discontinued", re.I)
LD_RE = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)


def _iter_ld(node):
    if isinstance(node, list):
        for n in node:
            yield from _iter_ld(n)
    elif isinstance(node, dict):
        yield node
        graph = node.get("@graph")
        if isinstance(graph, list):
            yield from _iter_ld(graph)


def read_product(html: str):
    """Lit les données Product (schema.org) de la page : prix et disponibilité déclarée."""
    for m in LD_RE.finditer(html):
        try:
            data = json.loads(m.group(1), strict=False)
        except ValueError:
            continue
        for node in _iter_ld(data):
            t = node.get("@type")
            if t == "Product" or (isinstance(t, list) and "Product" in t):
                offers = node.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                price = None
                try:
                    price = float(str(offers.get("price", "")).replace(",", "."))
                except ValueError:
                    pass
                if price is not None and price <= 0:  # prix « à venir » déclaré à 0
                    price = None
                return {"price": price, "availability": str(offers.get("availability", ""))}
    return None


def check_watch(w: dict, fetch=None):
    """Retourne {'status': 'in'|'out', 'price': float|None} ou None si la page est illisible
    (erreur réseau, page de protection...) : dans ce cas on ne change rien."""
    fetch = fetch or http_get
    try:
        html = fetch(w["url"], timeout=30).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        print(f"[suivi] {w['site']} : page illisible ({e})", file=sys.stderr)
        return None
    prod = read_product(html)
    if not prod:  # pas de fiche produit reconnue : probablement une page de protection ou un changement du site
        return None
    extra = w.get("out_regex")
    proof = w.get("in_regex")
    if (
        WATCH_OUT_HTML.search(html)
        or (extra and re.search(extra, html, re.I | re.S))
        or WATCH_OUT_SCHEMA.search(prod["availability"])
        # Certains sites ajoutent le message « rupture » en JavaScript : on exige alors une
        # preuve positive (le bouton d'achat dans la page) avant de conclure « en stock ».
        or (proof and not re.search(proof, html, re.I | re.S))
    ):
        return {"status": "out", "price": prod["price"]}
    return {"status": "in", "price": prod["price"]}


def fmt_price(p) -> str:
    return "" if p is None else f"{p:.2f}".replace(".", ",") + " €"


def run_watch(cfg: dict, state_dir: Path, fetch=None) -> list[dict]:
    """Vérifie les pages suivies et retourne les événements à signaler."""
    watches = cfg.get("watch", [])
    if not watches:
        return []
    path = state_dir / "watch.json"
    try:
        state = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        state = {}
    events: list[dict] = []
    for w in watches:
        res = check_watch(w, fetch)
        if res is None:
            print(f"?   {w['site']:<12} {w['name'][:36]:<36} illisible, état conservé")
            continue
        prev = state.get(w["id"])
        label = "EN STOCK ?" if res["status"] == "in" else "rupture"
        print(f"OK  {w['site']:<12} {w['name'][:36]:<36} {label} {fmt_price(res['price'])}")
        if res["status"] == "in" and (prev is None or prev["status"] != "in"):
            events.append({**w, "kind": "stock", "price": res["price"]})
        elif prev and prev.get("price") is not None and res["price"] is not None and abs(prev["price"] - res["price"]) > 0.001:
            events.append({**w, "kind": "price", "price": res["price"], "old_price": prev["price"]})
        new = {"status": res["status"], "price": res["price"]}
        if prev != new:  # on n'écrit que si quelque chose change (évite un commit à chaque passage)
            state[w["id"]] = {**new, "changed": now_iso()}
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
    return events


def build_watch_message(ev: dict):
    price = fmt_price(ev["price"])
    if ev["kind"] == "stock":
        title = f"DISPONIBLE ? {ev['site']}"
        head = "Le produit semble de nouveau en stock : vérifie vite la page."
    else:
        title = f"Prix modifié : {ev['site']}"
        head = f"Ancien prix {fmt_price(ev['old_price'])}, nouveau prix {price}."
    text = f"{head}\n\n{ev['name']}\n{price}\n{ev['url']}".replace("\n\n\n", "\n\n")
    return title, text


def notify_watch(events: list[dict], games: dict[str, str]) -> list[str]:
    sent: list[str] = []
    for ev in events:
        title, text = build_watch_message(ev)
        topic = os.environ.get("NTFY_TOPIC")
        if topic:
            server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
            try:
                post_json(server, {"topic": topic, "title": title, "message": text[:3500], "click": ev["url"], "priority": 5})
                sent.append("ntfy")
            except Exception as e:  # noqa: BLE001
                print(f"[notif] ntfy a échoué : {e}", file=sys.stderr)
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if token:
            chats = {c for c in (os.environ.get("TELEGRAM_CHAT_ID"), os.environ.get(f"TELEGRAM_CHAT_ID_{ev.get('game', '').upper()}")) if c}
            api = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
            for chat in sorted(chats):
                try:
                    post_json(f"{api}/bot{token}/sendMessage", {"chat_id": chat, "text": f"{title}\n\n{text}"[:4000]})
                    sent.append(f"telegram {chat}")
                except Exception as e:  # noqa: BLE001
                    print(f"[notif] Telegram {chat} a échoué : {e}", file=sys.stderr)
        hook = os.environ.get("DISCORD_WEBHOOK")
        if hook:
            try:
                post_json(hook, {"content": f"**{title}**\n\n{text}"[:1900]})
                sent.append("discord")
            except Exception as e:  # noqa: BLE001
                print(f"[notif] Discord a échoué : {e}", file=sys.stderr)
    return sent


# --------------------------------------------------------------------------
# Programme principal
# --------------------------------------------------------------------------
def run_check(cfg: dict) -> int:
    print("Vérification des enseignes (10 sitemaps max par site, rien n'est enregistré)\n")
    bad = 0
    for site in cfg["sites"]:
        m, total, errs, fetched = crawl_site(site, cfg["defaults"], cfg["rules"], max_sitemaps=10)
        ok = fetched > 0 and total > 0
        bad += 0 if ok else 1
        flag = "OK " if ok else "KO "
        extra = f" | {errs[0][:90]}" if errs else ""
        print(f"{flag} {site['name']:<14} sitemaps lus: {fetched:<3} URLs: {total:<8} correspondances: {len(m)}{extra}")
    print(f"\n{len(cfg['sites']) - bad}/{len(cfg['sites'])} enseignes lisibles")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=str(HERE / "config.json"))
    ap.add_argument("--state-dir", default=str(HERE / "state"))
    ap.add_argument("--out", default=str(HERE / "docs" / "data.json"))
    ap.add_argument("--check", action="store_true", help="teste l'accès aux sitemaps sans rien enregistrer")
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--watch-only", action="store_true", help="ne vérifie que les pages suivies (rapide, pour un passage toutes les 5 min)")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text("utf-8"))
    if args.check:
        return run_check(cfg)

    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    if args.watch_only:
        wev = run_watch(cfg, state_dir)
        if wev and not args.no_notify:
            sent = notify_watch(wev, {g["id"]: g["name"] for g in cfg["rules"]["games"]})
            print(f"{len(wev)} changement(s) sur les pages suivies, alerte via : {', '.join(sent) or 'aucun canal configuré'}")
        return 0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    games = {g["id"]: g["name"] for g in cfg["rules"]["games"]}

    data = {"items": [], "sites": {}, "games": games}
    if out.exists():
        try:
            data = json.loads(out.read_text("utf-8"))
        except json.JSONDecodeError:
            pass
    data["games"] = games
    items = {it["url"]: it for it in data.get("items", [])}
    # Re-filtrage de l'existant : si les règles ont changé, les anciennes pages
    # qui ne correspondent plus disparaissent de la liste (et les titres sont refaits).
    site_ex = {s["id"]: exclude_for(s, cfg["rules"]) for s in cfg["sites"]}
    kept = {}
    for u, it in items.items():
        if it.get("site") not in site_ex:
            continue
        g = classify(u, cfg["rules"], site_ex[it["site"]])
        if g:
            it["game"], it["title"] = g, title_from_url(u)
            kept[u] = it
    items = kept

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda s: process_site(s, cfg, state_dir), cfg["sites"]))

    fresh: list[dict] = []
    for site, status, new_items, state in results:
        data.setdefault("sites", {})[site["id"]] = status
        if status["ok"]:
            (state_dir / f"{site['id']}.json").write_text(json.dumps(state, ensure_ascii=False), "utf-8")
        for it in new_items:
            items[it["url"]] = it
            if not it["baseline"]:
                fresh.append(it)
        tag = "OK " if status["ok"] else "KO "
        print(
            f"{tag} {site['name']:<14} URLs: {status['urls_seen']:<8} correspondances: {status['matches']:<4} "
            f"nouvelles: {len(new_items)}" + (f" | {status['error']}" if status["error"] else "")
        )

    ordered = sorted(
        items.values(), key=lambda i: (i["first_seen"], not i.get("baseline", False)), reverse=True
    )[:MAX_ITEMS]
    data["items"] = ordered
    data["updated"] = now_iso()
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), "utf-8")

    if fresh and not args.no_notify:
        sent = notify(fresh, games)
        print(f"{len(fresh)} nouvelle(s) page(s), alerte envoyée via : {', '.join(sent) or 'aucun canal configuré'}")
    else:
        print(f"{len(fresh)} nouvelle(s) page(s) détectée(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
