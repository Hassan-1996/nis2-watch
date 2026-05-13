"""
analyzer.py — AI analysis via local Ollama model.

v3 changes:
- Aggiunto campo `email_narrativa`: testo lungo in stile consulenziale,
  pensato per essere il corpo principale della mail (non più solo tabella).
- Prompt Ollama esteso per produrre il testo narrativo oltre ai tre campi
  sintetici già esistenti.
- Fallback rule-based con template umano (introduzione contestuale,
  analisi, azioni, chiusura "parliamone").
- Estrazione data di pubblicazione e tipo di documento per popolare
  meglio il template di fallback.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Optional

import requests

OLLAMA_BASE   = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2:1b"
OLLAMA_TIMEOUT = 30   # alzato: la generazione narrativa richiede più token

PRIORITY_SIGNALS: dict[str, list[str]] = {
    "Alta": [
        "obbligo", "scadenza", "sanzione", "decreto", "recepimento",
        "notifica incidente", "misure minime", "obblighi", "registro",
        "attuazione", "determina", "determinazione", "adempimento",
        "adempimenti", "piattaforma nis", "termine", "entro il",
    ],
    "Media": [
        "consultazione", "linee guida", "bando", "circolare",
        "aggiornamento normativo", "chiarimenti", "faq", "avviso",
    ],
    "Bassa": [
        "evento", "convegno", "webinar", "formazione", "pubblicazione",
        "comunicato", "notizia",
    ],
}

# Mese italiano → numero (e viceversa) per l'estrazione/formattazione data
_MESI_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5,
    "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
    "novembre": 11, "dicembre": 12,
}
_MESI_IT_INV = {v: k for k, v in _MESI_IT.items()}


_SYSTEM = (
    "Sei un consulente senior in cybersecurity e compliance NIS2 che scrive "
    "comunicazioni professionali a clienti italiani (CISO, Compliance Officer, "
    "Risk Manager). Tono: professionale, neutro, consulenziale, mai promozionale. "
    "Rispondi SOLO con JSON valido, nessun testo prima o dopo, nessun markdown.\n"
    "Schema richiesto (tutti i campi sono obbligatori, in italiano):\n"
    "{\n"
    '  "rilevanza_nis2": "1-2 frasi sintetiche sulla rilevanza ai fini NIS2",\n'
    '  "impatto_ciso_grc": "1-2 frasi sintetiche sull\'impatto per CISO/GRC",\n'
    '  "azioni_consigliate": "elenco numerato breve di 2-4 azioni operative",\n'
    '  "priorita": "Alta|Media|Bassa",\n'
    '  "email_narrativa": "testo lungo 200-350 parole in italiano, in stile email '
    'consulenziale, articolato in paragrafi separati da \\n\\n. Struttura attesa: '
    '(1) segnalazione contestuale con data e oggetto pubblicato da ACN; '
    '(2) analisi degli adempimenti, scadenze e soggetti coinvolti; '
    '(3) azioni che l\'azienda dovrebbe intraprendere (referenti interni, '
    'documentazione, processi); '
    '(4) chiusura con disponibilità a supportare e invito a confrontarsi se '
    'qualche aspetto non è chiaro. NON usare bullet con il carattere •, usa '
    'trattini - oppure liste numerate 1. 2. 3."\n'
    "}"
)

# ── Rilevamento record "legacy" ────────────────────────────────────────────────
# Stringhe-firma del vecchio fallback rule-based v1/v2. Servono a riconoscere
# articoli salvati in archivio con la versione precedente del codice e a
# rigenerarne l'analisi al primo caricamento dopo l'upgrade.
LEGACY_RILEVANZA = (
    "Aggiornamento potenzialmente rilevante per la direttiva NIS2 "
    "(analisi automatica)."
)
LEGACY_IMPATTO = "Verificare applicabilità ai soggetti NIS2 dell'organizzazione."
LEGACY_AZIONI  = (
    "1. Leggere il documento completo. 2. Valutare impatto su obblighi NIS2."
)


def is_legacy_analysis(item: dict) -> bool:
    """
    Restituisce True se l'articolo è stato analizzato con la vecchia versione
    del codice (testi generici) o se manca del campo `email_narrativa`.
    """
    rel    = (item.get("rilevanza_nis2")     or "").strip()
    imp    = (item.get("impatto_ciso_grc")   or "").strip()
    azioni = (item.get("azioni_consigliate") or "").strip()

    if rel == LEGACY_RILEVANZA:
        return True
    if imp == LEGACY_IMPATTO:
        return True
    if azioni == LEGACY_AZIONI:
        return True
    if not item.get("email_narrativa"):
        return True
    return False


def refresh_legacy_record(item: dict) -> dict:
    """
    Ri-applica il fallback rule-based v3 a un record che proviene dalla
    vecchia versione del codice, preservando tutti i metadati di storage
    (id, is_read, sent_to, first_seen, ecc.).
    """
    fresh = _rule_based(item)
    return {**item, **fresh}


_ollama_ok_cache: Optional[bool] = None


# ── Ollama lifecycle ───────────────────────────────────────────────────────────

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
                # num_predict alzato per ospitare la narrativa
                "options": {"temperature": 0.2, "num_predict": 900, "top_p": 0.9},
            },
            timeout=OLLAMA_TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("response", "")
    except Exception:
        return None


def _parse_json(text: str) -> Optional[dict]:
    """
    Estrae l'ultimo oggetto JSON valido dal testo. Versione robusta che
    supporta JSON multilinea con stringhe lunghe (email_narrativa).
    """
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text).strip()

    # Tentativo: parse diretto
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: bilanciamento parentesi graffe per individuare l'oggetto JSON
    starts = [i for i, c in enumerate(text) if c == "{"]
    for start in reversed(starts):
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
    return None


def _normalise_prio(p: str) -> str:
    p = (p or "").strip().capitalize()
    if p not in ("Alta", "Media", "Bassa"):
        return "Media"
    return p


# ── Helpers per il fallback narrativo ──────────────────────────────────────────

def _extract_pub_date(item: dict) -> Optional[datetime]:
    """
    Cerca una data nel campo `date`, `first_seen` o nel titolo/snippet.
    Ritorna un datetime se trova qualcosa di plausibile, altrimenti None.
    """
    # 1) campo strutturato
    for key in ("date", "first_seen"):
        v = item.get(key)
        if not v:
            continue
        try:
            return datetime.fromisoformat(str(v)[:19])
        except Exception:
            pass

    # 2) data testuale "13 aprile 2026"
    text = f"{item.get('title','')} {item.get('snippet','')}".lower()
    m = re.search(r"(\d{1,2})\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|"
                  r"luglio|agosto|settembre|ottobre|novembre|dicembre)\s+(\d{4})", text)
    if m:
        try:
            return datetime(int(m.group(3)), _MESI_IT[m.group(2)], int(m.group(1)))
        except Exception:
            pass
    return None


def _format_date_it(d: datetime) -> str:
    return f"{d.day} {_MESI_IT_INV[d.month]} {d.year}"


def _doc_kind(text: str) -> str:
    """Restituisce un'etichetta sintetica del tipo di documento."""
    t = text.lower()
    if "determina" in t or "determinazione" in t:
        return "una determinazione"
    if "circolare" in t:
        return "una circolare"
    if "faq" in t:
        return "un aggiornamento delle FAQ"
    if "linee guida" in t:
        return "delle linee guida"
    if "consultazione" in t:
        return "una consultazione pubblica"
    if "avviso" in t:
        return "un avviso"
    if "decreto" in t:
        return "un decreto"
    return "un aggiornamento normativo"


def _rule_based_narrative(item: dict, priority: str) -> str:
    """
    Costruisce un testo narrativo in stile consulenziale anche senza AI,
    usando i pochi metadati disponibili (titolo, data, link).
    """
    title  = (item.get("title") or "").strip() or "un nuovo aggiornamento"
    url    = (item.get("url") or "").strip()
    pub    = _extract_pub_date(item)
    when   = _format_date_it(pub) if pub else "data non specificata"
    kind   = _doc_kind(title + " " + (item.get("snippet") or ""))

    # Tono leggermente diverso in base alla priorità
    if priority == "Alta":
        urg = (
            "Considerata la natura formale dell'aggiornamento e la possibile "
            "ristrettezza delle finestre temporali, suggeriamo di attivare "
            "tempestivamente i competenti referenti interni."
        )
    elif priority == "Media":
        urg = (
            "Pur non trattandosi di un adempimento immediato, riteniamo "
            "opportuno verificarne l'applicabilità per pianificare per tempo "
            "le eventuali attività di adeguamento."
        )
    else:
        urg = (
            "Non risultano scadenze immediate, ma è opportuno tracciare il "
            "documento all'interno del registro degli aggiornamenti normativi "
            "e valutarne l'eventuale impatto operativo."
        )

    fonte = f"\n\nPer completezza, si riporta il link al documento:\n{url}" if url else ""

    return (
        f"Segnaliamo che in data {when} ACN ha pubblicato {kind} dal titolo "
        f"\"{title}\". L'aggiornamento è stato rilevato dal nostro sistema di "
        f"monitoraggio del portale ACN e, in base a un'analisi preliminare, "
        f"presenta una rilevanza classificata come {priority.lower()} ai fini "
        f"degli adempimenti NIS2.\n\n"
        f"Il documento richiede una verifica puntuale di applicabilità ai "
        f"soggetti NIS2 dell'organizzazione, con particolare attenzione a "
        f"eventuali nuovi obblighi formali, termini di trasmissione e categorie "
        f"di soggetti coinvolte. È opportuno valutare in modo coordinato fra "
        f"funzione Compliance, Sicurezza delle Informazioni e Punto di Contatto "
        f"NIS l'effettivo perimetro di impatto e le eventuali azioni operative "
        f"da intraprendere.\n\n"
        f"In via prudenziale, suggeriamo di: (1) acquisire e leggere "
        f"integralmente il documento; (2) mappare i requisiti rispetto al "
        f"perimetro NIS2 dell'organizzazione; (3) valutare l'aggiornamento "
        f"delle policy, procedure e registri interessati; (4) pianificare "
        f"eventuali comunicazioni o trasmissioni formali verso ACN.{fonte}\n\n"
        f"{urg} Restiamo a disposizione per supportarvi nell'interpretazione "
        f"del documento, nell'analisi di impatto sul vostro perimetro NIS2 e "
        f"nella predisposizione della documentazione eventualmente necessaria. "
        f"Qualora alcuni aspetti non risultassero chiari o desideraste un "
        f"confronto sull'applicabilità al vostro contesto, parliamone: siamo "
        f"a disposizione per un approfondimento dedicato."
    )


def _rule_based(item: dict) -> dict:
    text = (item.get("title", "") + " " + item.get("snippet", "")).lower()
    priority = "Bassa"
    for level, signals in PRIORITY_SIGNALS.items():
        if any(s in text for s in signals):
            priority = level
            break

    title = (item.get("title") or "").strip()
    return {
        "rilevanza_nis2":
            f"Aggiornamento pubblicato dal portale ACN potenzialmente rilevante "
            f"per gli adempimenti NIS2. Oggetto: \"{title or '—'}\".",
        "impatto_ciso_grc":
            "Necessaria verifica di applicabilità sui soggetti NIS2 "
            "dell'organizzazione e sui processi di Compliance/GRC, con "
            "particolare attenzione a nuovi obblighi formali e scadenze.",
        "azioni_consigliate":
            "1. Acquisire e leggere il documento integrale. "
            "2. Mappare i requisiti rispetto al perimetro NIS2. "
            "3. Coordinare la valutazione con il Punto di Contatto NIS. "
            "4. Aggiornare policy, procedure o registri eventualmente impattati.",
        "priorita":           priority,
        "ai_source":          "rule-based",
        "email_narrativa":    _rule_based_narrative(item, priority),
    }


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_item(item: dict, model: str = DEFAULT_MODEL) -> dict:
    snippet = (item.get("snippet") or "")[:600]
    date    = item.get("date") or (item.get("first_seen", "")[:10])
    url     = item.get("url", "")

    prompt = (
        f"{_SYSTEM}\n\n"
        f"--- Articolo da analizzare ---\n"
        f"Titolo: {item.get('title','')}\n"
        f"Data pubblicazione: {date}\n"
        f"URL: {url}\n"
        f"Estratto: {snippet}\n"
        f"--- Fine articolo ---\n\n"
        f"Genera ora il JSON richiesto. Ricorda: il campo "
        f"`email_narrativa` deve essere il corpo di una mail consulenziale "
        f"professionale, NON una semplice ripetizione dei tre campi sintetici."
    )

    raw    = _call_ollama(prompt, model) if _ollama_available() else None
    parsed = _parse_json(raw) if raw else None

    if parsed and parsed.get("rilevanza_nis2"):
        priority = _normalise_prio(parsed.get("priorita", ""))
        narrative = str(parsed.get("email_narrativa") or "").strip()
        # Se il modello ha omesso o accorciato troppo la narrativa, completiamo
        # col fallback rule-based per evitare mail vuote/troppo corte.
        if len(narrative) < 250:
            narrative = _rule_based_narrative(item, priority)

        analysis = {
            "rilevanza_nis2":     str(parsed.get("rilevanza_nis2", "—")).strip(),
            "impatto_ciso_grc":   str(parsed.get("impatto_ciso_grc", "—")).strip(),
            "azioni_consigliate": str(parsed.get("azioni_consigliate", "—")).strip(),
            "priorita":           priority,
            "ai_source":          "ollama",
            "email_narrativa":    narrative,
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
        # Skip se già analizzato (re-run idempotente). Se la narrativa manca
        # — ad esempio articoli salvati con la versione precedente — la
        # ricostruiamo via fallback senza richiamare Ollama.
        if item.get("rilevanza_nis2") and item.get("priorita"):
            if not item.get("email_narrativa"):
                item = {
                    **item,
                    "email_narrativa": _rule_based_narrative(
                        item, _normalise_prio(item.get("priorita", ""))
                    ),
                }
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
