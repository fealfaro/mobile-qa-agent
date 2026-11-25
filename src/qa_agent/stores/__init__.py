"""Búsqueda de apps en tiendas públicas para crear perfiles.

- App Store: iTunes Search API (oficial y pública).
- Google Play: no tiene API oficial de búsqueda. Se usa `google-play-scraper` (no oficial; puede
  romperse si Google cambia su web). Si falla, se devuelve un error explicativo, nunca datos inventados.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"}


@dataclass
class StoreApp:
    store: str                 # google_play | app_store
    id: str                    # applicationId / bundleId
    title: str
    developer: str
    icon: str | None
    url: str
    rating: float | None
    genre: str = ""
    track_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class StoreError(RuntimeError):
    pass


def search_app_store(term: str, country: str = "cl", limit: int = 15) -> list[StoreApp]:
    q = urllib.parse.urlencode({"term": term, "country": country, "entity": "software", "limit": limit})
    try:
        with urllib.request.urlopen(f"https://itunes.apple.com/search?{q}", timeout=15) as r:
            data = json.load(r)
    except Exception as e:
        raise StoreError(f"App Store no respondió: {e}") from e
    out = []
    for x in data.get("results", []):
        out.append(StoreApp("app_store", x["bundleId"], x.get("trackName", ""), x.get("sellerName", ""),
                            x.get("artworkUrl512") or x.get("artworkUrl100"), x.get("trackViewUrl", ""),
                            round(x["averageUserRating"], 1) if x.get("averageUserRating") else None,
                            x.get("primaryGenreName", ""), str(x.get("trackId", "")) or None))
    return out


def _play_ids_from_html(term: str, lang: str, country: str) -> list[str]:
    u = "https://play.google.com/store/search?" + urllib.parse.urlencode({"q": term, "c": "apps", "hl": lang, "gl": country})
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=15) as r:
        html = r.read().decode("utf-8", "ignore")
    ids: list[str] = []
    for i in re.findall(r"/store/apps/details\?id=([\w.]+)", html):
        if i not in ids:
            ids.append(i)
    return ids


def search_google_play(term: str, country: str = "cl", lang: str = "es", limit: int = 15) -> list[StoreApp]:
    try:
        from google_play_scraper import search
    except ImportError as e:
        raise StoreError("Falta la dependencia google-play-scraper") from e
    try:
        res = search(term, lang=lang, country=country, n_hits=limit)
    except Exception as e:
        raise StoreError(f"Google Play no respondió: {e}") from e
    # La librería a veces devuelve el primer resultado (destacado) sin appId: se recupera por posición
    # desde la página de búsqueda, que lista los mismos resultados en el mismo orden.
    if any(not x.get("appId") for x in res):
        try:
            html_ids = _play_ids_from_html(term, lang, country)
        except Exception:
            html_ids = []
        known = {x["appId"] for x in res if x.get("appId")}
        for i, x in enumerate(res):
            if not x.get("appId") and i < len(html_ids) and html_ids[i] not in known:
                x["appId"] = html_ids[i]
                known.add(html_ids[i])
    out = []
    for x in res:
        if not x.get("appId"):
            continue  # sin id confiable no se ofrece (no se inventa)
        out.append(StoreApp("google_play", x["appId"], x.get("title", ""), x.get("developer", ""), x.get("icon"),
                            f"https://play.google.com/store/apps/details?id={x['appId']}",
                            round(x["score"], 1) if x.get("score") else None, x.get("genre", "")))
    return out


def search(store: str, term: str, country: str = "cl") -> list[StoreApp]:
    term = term.strip()
    if not 2 <= len(term) <= 80:
        raise StoreError("Escribe entre 2 y 80 caracteres")
    if store == "google_play":
        return search_google_play(term, country)
    if store == "app_store":
        return search_app_store(term, country)
    raise StoreError(f"Tienda desconocida: {store}")
