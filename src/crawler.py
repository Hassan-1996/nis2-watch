"""
crawler.py v3 — ACN NIS2 crawler.

Modifiche:
- SEED_URLS aggiornati con articoli reali 2025 trovati live
- Ordinamento per data articolo (non data di scraping)
- Cache discovery separata da cache articoli
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.acn.gov.it"

DISCOVERY_PAGES = [
    "https://www.acn.gov.it/portale/nis/notizie-ed-eventi",
    "https://www.acn.gov.it/portale/nis/la-normativa",
    "https://www.acn.gov.it/portale/nis/obblighi",
    "https://www.acn.gov.it/portale/nis",
]

# URL reali verificati live — aggiornati maggio 2026
SEED_URLS = [
    "https://www.acn.gov.it/portale/w/nis2-linee-guida-sul-processo-di-gestione-degli-incidenti-di-sicurezza-informatica",
    "https://www.acn.gov.it/portale/w/nis2-aggiornamenti-dal-tavolo-per-l-attuazione",
    "https://www.acn.gov.it/portale/w/nis-i-prossimi-passi-nell-attuazione-della-nuova-disciplina",
    "https://www.acn.gov.it/portale/w/nis-avviata-la-seconda-fase",
    "https://www.acn.gov.it/portale/w/nis-online-le-determine-sugli-adempimenti-per-i-nuovi-soggetti-e-sulle-modalita-di-accesso-alla-piattaforma-acn",
    "https://www.acn.gov.it/portale/w/nis-pubblicate-le-modalita-per-l-elencazione-e-la-categorizzazione-delle-attivita-e-dei-servizi",
    "https://www.acn.gov.it/portale/w/acn-convoca-il-tavolo-per-l-attuazione-della-disciplina-nis",
    "https://www.acn.gov.it/portale/w/registrazione-soggetti-nis-si-avvicina-la-scadenza-del-28-febbraio-2025",
    "https://www.acn.gov.it/portale/w/normativa-nis-date-e-informazioni-utili-per-un-implementazione-efficace",
    # Articolo citato dall'utente (UNI/PdR 174:2025)
    "https://www.acn.gov.it/portale/web/guest/-/uni/pdr-174-2025-pubblicata-la-nuova-prassi-di-riferimento-a-supporto-dei-soggetti-nis-certificati-iso-27001",
]

KEYWORDS = [
    "nis2", "nis 2", "direttiva", "aggiornamento", "decreto", "obbligo",
    "notifica", "incidente", "misura", "sicurezza", "scadenza", "registro",
    "acn", "normativa", "recepimento", "attuazione", "consultazione",
    "bando", "circolare", "comunicato", "sanzione", "categorizzazione",
    "elencazione", "soggetti", "adempimenti", "piattaforma", "linee guida",
    "determina", "tavolo", "uni", "pdr", "iso", "certificati",
]

BLACKLIST_LINES = [
    "menu", "cerca", "condividi", "stampa", "ascolta", "torna indietro",
    "privacy", "cookie", "seguici", "agenzia per la cybersicurezza nazionale",
    "notizie ed eventi", "registrazione", "faq",
    "consulta le domande frequenti", "apre un link esterno",
]

MONTHS_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

CACHE_DIR       = Path(__file__).parent.parent / "cache"
CACHE_TTL       = timedelta(minutes=60)
REQUEST_TIMEOUT = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.acn.gov.it/",
}

_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
    return _session


# ── Cache ──────────────────────────────────────────────────────────────────────

def _cache_key(url: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.md5(url.encode()).hexdigest()
    return CACHE_DIR / f"{h}.json"


def _cache_get(url: str) -> list[dict] | None:
    p = _cache_key(url)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if datetime.now() - datetime.fromisoformat(data["ts"]) < CACHE_TTL:
            return data["items"]
    except Exception:
        pass
    return None


def _cache_set(url: str, items: list[dict]) -> None:
    try:
        tmp = _cache_key(url).with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"ts": datetime.now().isoformat(), "items": items},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(_cache_key(url))
    except Exception:
        pass


def clear_cache() -> None:
    for f in CACHE_DIR.glob("*.json"):
        f.unlink(missing_ok=True)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _parse_date_it(text: str) -> tuple[str, datetime]:
    pattern = (
        r"(\d{1,2})\s+"
        r"(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto"
        r"|settembre|ottobre|novembre|dicembre)\s+(\d{4})"
    )
    m = re.search(pattern, text.lower())
    if not m:
        return "", datetime.min
    day   = int(m.group(1))
    month = MONTHS_IT[m.group(2)]
    year  = int(m.group(3))
    return f"{day} {m.group(2)} {year}", datetime(year, month, day)


def _kw_match(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in KEYWORDS)


# ── Discovery ──────────────────────────────────────────────────────────────────

def _discover_article_urls() -> list[str]:
    found: set[str] = set(SEED_URLS)
    sess = _get_session()

    for page_url in DISCOVERY_PAGES:
        try:
            resp = sess.get(page_url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            matches = re.findall(
                r"https://www\.acn\.gov\.it/portale/w/[a-zA-Z0-9\-_]+"
                r"|/portale/w/[a-zA-Z0-9\-_]+",
                resp.text,
            )
            for m in matches:
                if m.startswith("/"):
                    m = BASE_URL + m
                if "notizie-ed-eventi" not in m:
                    found.add(m)
        except requests.exceptions.RequestException:
            pass
        time.sleep(0.3)

    return list(found)


# ── Estrazione articolo ────────────────────────────────────────────────────────

def _extract_article(url: str) -> dict | None:
    cached = _cache_get(url)
    if cached is not None and cached:
        return cached[0]

    sess = _get_session()
    try:
        resp = sess.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.exceptions.RequestException:
        return None

    try:
        soup = BeautifulSoup(resp.text, "lxml")
    except Exception:
        soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(["script", "style", "nav", "footer",
                     "header", "aside", "form", "iframe"]):
        tag.decompose()

    title = ""
    h1 = soup.find("h1")
    if h1:
        title = _clean(h1.get_text(" ", strip=True))

    raw_text  = soup.get_text("\n", strip=True)
    date_label, date_obj = _parse_date_it(raw_text)

    lines      = raw_text.splitlines()
    paragraphs = []
    for line in lines:
        text = _clean(line)
        if len(text) < 40:
            continue
        low = text.lower()
        if title and text == title:
            continue
        if date_label and date_label.lower() in low:
            continue
        if any(x in low for x in BLACKLIST_LINES):
            continue
        if text not in paragraphs:
            paragraphs.append(text)

    content = "\n\n".join(paragraphs)

    if not date_label or len(content) < 100:
        return None
    if not _kw_match(title + " " + content[:500]):
        return None

    article = {
        "title":    title or url.split("/")[-1].replace("-", " ").title(),
        "url":      url,
        "date":     date_label,
        "date_obj": date_obj.isoformat(),
        "snippet":  content[:400],
        "source":   url,
    }
    _cache_set(url, [article])
    return article


# ── API pubblica ───────────────────────────────────────────────────────────────

def scrape_acn_nis(use_cache: bool = True) -> tuple[list[dict], list[str]]:
    """
    Scrape ACN NIS. Ordina sempre per data articolo decrescente.
    Returns (articles, errors).
    """
    errors: list[str] = []

    disc_cache_url = "discovery_urls"
    disc_cached    = _cache_get(disc_cache_url) if use_cache else None

    if disc_cached is not None:
        article_urls = [item["url"] for item in disc_cached]
    else:
        article_urls = _discover_article_urls()
        _cache_set(disc_cache_url, [{"url": u} for u in article_urls])

    articles:     list[dict] = []
    seen_titles:  set[str]   = set()

    for url in article_urls:
        if not use_cache:
            cp = _cache_key(url)
            cp.unlink(missing_ok=True)
        try:
            article = _extract_article(url)
        except Exception as e:
            errors.append(f"{url} ({e})")
            continue
        if article is None:
            continue
        if article["title"] in seen_titles:
            continue
        seen_titles.add(article["title"])
        articles.append(article)
        time.sleep(0.2)

    # ── Ordina per data articolo (più recente prima) ────────────────────────
    def _sort_key(a: dict) -> datetime:
        try:
            return datetime.fromisoformat(a.get("date_obj", ""))
        except Exception:
            return datetime.min

    articles.sort(key=_sort_key, reverse=True)
    return articles, errors
