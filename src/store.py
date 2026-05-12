"""
store.py v3 — Archivio articoli persistente.

Novità:
- sent_to: dict {email: timestamp} su ogni articolo
  → traccia a chi è stato mandato e quando
- auto_send_eligible(article, recipients):
  → restituisce solo i destinatari AUTO a cui l'articolo NON è ancora stato inviato
- record_sent(article_id, emails): segna l'invio
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

DATA_DIR   = Path(__file__).parent.parent / "data"
STORE_PATH = DATA_DIR / "articles.json"
META_PATH  = DATA_DIR / "meta.json"


# ── I/O ────────────────────────────────────────────────────────────────────────

def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, obj: object) -> None:
    _ensure_dir()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_store() -> dict[str, dict]:
    return _load_json(STORE_PATH, {})


def _load_meta() -> dict:
    return _load_json(META_PATH, {"last_run_ids": [], "last_run_at": None})


def _make_id(item: dict) -> str:
    raw = (item.get("url", "") + "|" + item.get("title", "")).encode()
    return hashlib.md5(raw).hexdigest()[:12]


# ── Ingest ─────────────────────────────────────────────────────────────────────

def ingest_articles(analyzed_items: list[dict]) -> tuple[list[dict], list[dict]]:
    store    = _load_store()
    meta     = _load_meta()
    prev_ids: set[str] = set(meta.get("last_run_ids", []))
    now_iso  = datetime.now().isoformat()

    current_ids: set[str] = set()
    new_articles: list[dict] = []

    for item in analyzed_items:
        aid    = _make_id(item)
        current_ids.add(aid)
        is_new = aid not in prev_ids

        if aid not in store:
            record: dict = {
                **item,
                "id":         aid,
                "is_new":     is_new,
                "is_read":    False,
                "sent_to":    {},          # {email: iso_timestamp}
                "first_seen": now_iso,
                "last_seen":  now_iso,
            }
            store[aid] = record
        else:
            store[aid]["last_seen"] = now_iso
            store[aid]["is_new"]    = is_new
            # Backfill sent_to per record precedenti senza il campo
            if "sent_to" not in store[aid]:
                store[aid]["sent_to"] = {}

        if store[aid]["is_new"]:
            new_articles.append(store[aid])

    for pid in prev_ids:
        if pid not in current_ids and pid in store:
            store[pid]["is_new"] = False

    _atomic_write(STORE_PATH, store)
    _atomic_write(META_PATH, {"last_run_ids": list(current_ids), "last_run_at": now_iso})

    all_sorted = sorted(store.values(), key=lambda x: x.get("first_seen", ""), reverse=True)
    return new_articles, all_sorted


# ── Sent tracking ──────────────────────────────────────────────────────────────

def record_sent(article_id: str, emails: list[str]) -> None:
    """Registra che l'articolo è stato inviato a questi indirizzi email."""
    store = _load_store()
    if article_id not in store:
        return
    now = datetime.now().isoformat()
    if "sent_to" not in store[article_id]:
        store[article_id]["sent_to"] = {}
    for email in emails:
        store[article_id]["sent_to"][email.lower()] = now
    _atomic_write(STORE_PATH, store)


def already_sent_to(article_id: str, email: str) -> bool:
    """Controlla se l'articolo è già stato inviato automaticamente a questa email."""
    store = _load_store()
    if article_id not in store:
        return False
    return email.lower() in store[article_id].get("sent_to", {})


def auto_send_eligible(article: dict, auto_recipients: list[dict]) -> list[dict]:
    """
    Dato un articolo e la lista dei destinatari AUTO,
    restituisce solo quelli a cui l'articolo NON è ancora stato inviato.
    Questo previene l'invio duplicato automatico.
    """
    aid = article.get("id", "")
    return [
        r for r in auto_recipients
        if not already_sent_to(aid, r.get("email", ""))
    ]


# ── Read state ─────────────────────────────────────────────────────────────────

def mark_read(article_id: str) -> None:
    store = _load_store()
    if article_id in store:
        store[article_id]["is_read"] = True
        _atomic_write(STORE_PATH, store)


def mark_unread(article_id: str) -> None:
    store = _load_store()
    if article_id in store:
        store[article_id]["is_read"] = False
        _atomic_write(STORE_PATH, store)


def toggle_read(article_id: str) -> bool:
    store = _load_store()
    if article_id in store:
        new_state = not store[article_id].get("is_read", False)
        store[article_id]["is_read"] = new_state
        _atomic_write(STORE_PATH, store)
        return new_state
    return False


def mark_all_read() -> None:
    store = _load_store()
    changed = False
    for v in store.values():
        if not v.get("is_read"):
            v["is_read"] = True
            changed = True
    if changed:
        _atomic_write(STORE_PATH, store)


def mark_all_unread() -> None:
    store = _load_store()
    changed = False
    for v in store.values():
        if v.get("is_read"):
            v["is_read"] = False
            changed = True
    if changed:
        _atomic_write(STORE_PATH, store)


# ── Queries ────────────────────────────────────────────────────────────────────

def get_all_articles() -> list[dict]:
    store = _load_store()
    items = list(store.values())
    # Ordina per data articolo (date) se disponibile, altrimenti first_seen
    def _sort_key(a: dict) -> str:
        # date_obj è ISO datetime string dell'articolo reale
        return a.get("date_obj") or a.get("first_seen", "")
    return sorted(items, key=_sort_key, reverse=True)


def get_new_articles() -> list[dict]:
    return [a for a in get_all_articles() if a.get("is_new")]


def get_stats() -> dict:
    store = _load_store()
    items = list(store.values())
    return {
        "total":  len(items),
        "new":    sum(1 for a in items if a.get("is_new")),
        "unread": sum(1 for a in items if not a.get("is_read")),
        "alta":   sum(1 for a in items if "alt" in (a.get("priorita", "")).lower()),
        "media":  sum(1 for a in items if "med" in (a.get("priorita", "")).lower()),
        "bassa":  sum(1 for a in items if "bas" in (a.get("priorita", "")).lower()),
    }


def clear_store() -> None:
    for p in (STORE_PATH, META_PATH):
        if p.exists():
            p.unlink()
