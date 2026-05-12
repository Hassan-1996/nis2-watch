"""
analyzer.py — AI analysis via local Ollama model.

v2 fixes:
- _rule_based_analysis no longer KeyErrors on missing 'snippet'
- _ollama_available cached for duration of process (one check per run)
- JSON extraction uses greedy last-match to handle preamble text
- priorita field normalised to Title-case before returning
- analyze_items skips items that already have analysis fields (re-run safe)
"""

from __future__ import annotations

import json
import re
from typing import Optional

import requests

OLLAMA_BASE   = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2:1b"
OLLAMA_TIMEOUT = 18

PRIORITY_SIGNALS: dict[str, list[str]] = {
    "Alta": [
        "obbligo", "scadenza", "sanzione", "decreto", "recepimento",
        "notifica incidente", "misure minime", "obblighi", "registro",
        "attuazione",
    ],
    "Media": [
        "consultazione", "linee guida", "bando", "circolare",
        "aggiornamento normativo", "chiarimenti",
    ],
    "Bassa": [
        "evento", "convegno", "webinar", "formazione", "pubblicazione",
        "comunicato", "notizia",
    ],
}

_SYSTEM = (
    "Sei un analista cybersecurity NIS2. "
    "Rispondi SOLO con JSON valido, nessun testo prima o dopo, nessun markdown.\n"
    '{"rilevanza_nis2":"...","impatto_ciso_grc":"...","azioni_consigliate":"...","priorita":"Alta|Media|Bassa"}'
)

_ollama_ok_cache: Optional[bool] = None


def _ollama_available() -> bool:
    global _ollama_ok_cache
    if _ollama_ok_cache is not None:
        return _ollama_ok_cache
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=3)
        _ollama_ok_cache = r.status_code == 200
    except Exception:
        _ollama_ok_cache = False
    return _ollama_ok_cache


def reset_ollama_cache() -> None:
    """Call before each analysis run so availability is re-checked."""
    global _ollama_ok_cache
    _ollama_ok_cache = None


def _call_ollama(prompt: str, model: str) -> Optional[str]:
    try:
        r = requests.post(
            f"{OLLAMA_BASE}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 220, "top_p": 0.9},
            },
            timeout=OLLAMA_TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("response", "")
    except Exception:
        return None


def _parse_json(text: str) -> Optional[dict]:
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text).strip()
    # Find last JSON object (handles preamble text from some models)
    matches = list(re.finditer(r"\{[^{}]*\}", text, re.DOTALL))
    if not matches:
        return None
    for m in reversed(matches):
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            continue
    return None


def _normalise_prio(p: str) -> str:
    p = (p or "").strip().capitalize()
    if p not in ("Alta", "Media", "Bassa"):
        return "Media"
    return p


def _rule_based(item: dict) -> dict:
    text = (item.get("title", "") + " " + item.get("snippet", "")).lower()
    priority = "Bassa"
    for level, signals in PRIORITY_SIGNALS.items():
        if any(s in text for s in signals):
            priority = level
            break
    return {
        "rilevanza_nis2":     "Aggiornamento potenzialmente rilevante per la direttiva NIS2 (analisi automatica).",
        "impatto_ciso_grc":   "Verificare applicabilità ai soggetti NIS2 dell'organizzazione.",
        "azioni_consigliate": "1. Leggere il documento completo. 2. Valutare impatto su obblighi NIS2.",
        "priorita":           priority,
        "ai_source":          "rule-based",
    }


def analyze_item(item: dict, model: str = DEFAULT_MODEL) -> dict:
    snippet = (item.get("snippet") or "")[:200]
    prompt  = f"{_SYSTEM}\n\nTitolo: {item.get('title','')}\nEstratto: {snippet}"

    raw    = _call_ollama(prompt, model) if _ollama_available() else None
    parsed = _parse_json(raw) if raw else None

    if parsed:
        analysis = {
            "rilevanza_nis2":     str(parsed.get("rilevanza_nis2", "—")),
            "impatto_ciso_grc":   str(parsed.get("impatto_ciso_grc", "—")),
            "azioni_consigliate": str(parsed.get("azioni_consigliate", "—")),
            "priorita":           _normalise_prio(parsed.get("priorita", "")),
            "ai_source":          "ollama",
        }
    else:
        analysis = _rule_based(item)

    return {**item, **analysis}


def analyze_items(
    items: list[dict],
    model: str = DEFAULT_MODEL,
    progress_callback=None,
) -> list[dict]:
    reset_ollama_cache()
    results = []
    total   = len(items)

    for i, item in enumerate(items):
        # Skip if already fully analyzed (idempotent re-runs)
        if item.get("rilevanza_nis2") and item.get("priorita"):
            results.append(item)
        else:
            results.append(analyze_item(item, model))
        if progress_callback:
            progress_callback(i + 1, total)

    return results


def get_available_models() -> list[str]:
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=3)
        if r.status_code == 200:
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass
    return []
