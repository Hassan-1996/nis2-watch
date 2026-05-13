"""
mailer.py — Structured email delivery v3.

v3 changes:
- Layout email completamente rifatto in stile consulenziale.
  Il corpo principale è ora `email_narrativa` (testo lungo, prosa
  professionale) e non più la tabella a tre celle.
- Riquadro "Scheda tecnica" in fondo con i tre campi sintetici
  (Rilevanza / Impatto / Azioni) come riferimento operativo.
- Sezione "Parliamone" con call-to-action esplicita.
- Email multi-articolo: ogni articolo diventa una sezione narrativa
  separata con il suo titolo + link + scheda tecnica.
- Versione plain-text fedele alla narrativa (non solo titolo + URL).
"""

from __future__ import annotations

import html
import json
import re
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

DATA_DIR    = Path(__file__).parent.parent / "data"
CONFIG_PATH = DATA_DIR / "email_config.json"
RECIP_PATH  = DATA_DIR / "recipients.json"

_DEFAULTS = {
    "smtp_host":        "smtp.gmail.com",
    "smtp_port":        587,
    "sender_email":     "",
    "sender_password":  "",
    "sender_name":      "NIS2 Regulatory Watch",
}

_COLOR = {"alta": "#c0392b", "media": "#d68910", "bassa": "#1e8449"}
_LABEL = {"alta": "ALTA",    "media": "MEDIA",   "bassa": "BASSA"}


def _prio_key(p: str) -> str:
    p = (p or "").lower()
    if "alt" in p: return "alta"
    if "med" in p: return "media"
    if "bas" in p: return "bassa"
    return "media"


# ── Config ─────────────────────────────────────────────────────────────────────

def load_email_config() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        return dict(_DEFAULTS)
    try:
        saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return {**_DEFAULTS, **saved}
    except Exception:
        return dict(_DEFAULTS)


def save_email_config(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_recipients() -> list[dict]:
    if not RECIP_PATH.exists():
        return []
    try:
        data = json.loads(RECIP_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        for r in data:
            if "group" not in r:
                r["group"] = "manual"
        return data
    except Exception:
        return []


def load_auto_recipients() -> list[dict]:
    return [r for r in load_recipients() if r.get("group") == "auto"]


def load_manual_recipients() -> list[dict]:
    return [r for r in load_recipients() if r.get("group") == "manual"]


def save_recipients(recips: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RECIP_PATH.write_text(
        json.dumps(recips, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def add_recipient(name: str, email: str, group: str = "manual") -> None:
    recips = load_recipients()
    email_l = email.strip().lower()
    if not any(r["email"].lower() == email_l for r in recips):
        recips.append({
            "name":  name.strip(),
            "email": email_l,
            "group": group if group in ("auto", "manual") else "manual",
        })
        save_recipients(recips)


def set_recipient_group(email: str, group: str) -> None:
    recips = load_recipients()
    for r in recips:
        if r["email"].lower() == email.lower():
            r["group"] = group if group in ("auto", "manual") else "manual"
    save_recipients(recips)


def remove_recipient(email: str) -> None:
    save_recipients([r for r in load_recipients()
                     if r["email"].lower() != email.lower()])


# ── HTML builder ───────────────────────────────────────────────────────────────

def _safe(v, default="—") -> str:
    return str(v).strip() if v else default


def _narrative_to_html(text: str) -> str:
    """
    Converte la narrativa (testo con \\n\\n fra paragrafi e eventuali
    elenchi numerati / trattini) in HTML email-safe.
    """
    if not text:
        return "<p style='color:#888;'>(Analisi narrativa non disponibile)</p>"

    text = text.strip()
    paragraphs = re.split(r"\n\s*\n", text)

    out: list[str] = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        lines = [l.strip() for l in para.splitlines() if l.strip()]
        # Lista numerata "1. ..." su righe consecutive
        if all(re.match(r"^\d+\.\s+", l) for l in lines) and len(lines) > 1:
            cleaned = [re.sub(r"^\d+\.\s+", "", l) for l in lines]
            items = "".join(
                f"<li style='margin-bottom:6px;'>{html.escape(c)}</li>"
                for c in cleaned
            )
            out.append(
                f"<ol style='margin:0 0 14px 0;padding-left:22px;color:#2c3e50;"
                f"font-size:14px;line-height:1.65;'>{items}</ol>"
            )
            continue

        # Lista con trattini
        if all(l.startswith(("- ", "– ", "• ")) for l in lines) and len(lines) > 1:
            cleaned = [re.sub(r"^[-–•]\s+", "", l) for l in lines]
            items = "".join(
                f"<li style='margin-bottom:6px;'>{html.escape(c)}</li>"
                for c in cleaned
            )
            out.append(
                f"<ul style='margin:0 0 14px 0;padding-left:22px;color:#2c3e50;"
                f"font-size:14px;line-height:1.65;'>{items}</ul>"
            )
            continue

        # Paragrafo standard — linkifichiamo eventuali URL
        safe = html.escape(para).replace("\n", "<br>")
        safe = re.sub(
            r"(https?://[^\s&lt;]+)",
            r"<a href='\1' style='color:#1a237e;'>\1</a>",
            safe,
        )
        out.append(
            f"<p style='margin:0 0 14px 0;color:#2c3e50;font-size:14px;"
            f"line-height:1.65;'>{safe}</p>"
        )

    return "\n".join(out)


def _scheda_tecnica(a: dict) -> str:
    """Riquadro compatto con i tre campi sintetici, in fondo alla sezione."""
    rel    = _safe(a.get("rilevanza_nis2"))
    impact = _safe(a.get("impatto_ciso_grc"))
    azioni = _safe(a.get("azioni_consigliate"))
    pk     = _prio_key(a.get("priorita", ""))
    color  = _COLOR.get(pk, "#888")

    return f"""
<div style="background:#f5f6fa;border-left:3px solid {color};border-radius:4px;
            padding:14px 18px;margin:10px 0 4px 0;font-family:Arial,sans-serif;">
  <div style="font-size:10px;font-weight:700;color:#666;letter-spacing:2px;
              text-transform:uppercase;margin-bottom:10px;">
    Scheda tecnica
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:12.5px;">
    <tr>
      <td style="width:140px;padding:5px 0;color:#555;font-weight:700;
                 vertical-align:top;">Rilevanza NIS2</td>
      <td style="padding:5px 0;color:#333;">{html.escape(rel)}</td>
    </tr>
    <tr>
      <td style="padding:5px 0;color:#555;font-weight:700;
                 vertical-align:top;">Impatto CISO/GRC</td>
      <td style="padding:5px 0;color:#333;">{html.escape(impact)}</td>
    </tr>
    <tr>
      <td style="padding:5px 0;color:#555;font-weight:700;
                 vertical-align:top;">Azioni operative</td>
      <td style="padding:5px 0;color:#333;">{html.escape(azioni)}</td>
    </tr>
  </table>
</div>"""


def _article_section(a: dict, idx: int, total: int) -> str:
    """Una sezione narrativa per articolo."""
    pk        = _prio_key(a.get("priorita", ""))
    color     = _COLOR.get(pk, "#888")
    label     = _LABEL.get(pk, _safe(a.get("priorita")))
    url       = _safe(a.get("url"), "#")
    title     = _safe(a.get("title"))
    date      = _safe(a.get("date") or a.get("first_seen", "")[:10])
    narrative = _narrative_to_html(a.get("email_narrativa", ""))

    multi_hdr = ""
    if total > 1:
        multi_hdr = (
            f"<div style='font-size:11px;color:#888;font-weight:700;"
            f"letter-spacing:2px;text-transform:uppercase;margin-bottom:6px;'>"
            f"Aggiornamento {idx} di {total}</div>"
        )

    return f"""
<div style="background:#ffffff;border:1px solid #e3e6ea;border-left:4px solid {color};
            border-radius:6px;padding:22px 26px;margin-bottom:22px;
            font-family:Arial,sans-serif;">
  {multi_hdr}
  <div style="margin-bottom:8px;">
    <span style="background:{color};color:#fff;font-size:10.5px;font-weight:700;
                 padding:3px 10px;border-radius:3px;letter-spacing:1px;">
      PRIORITÀ {label}
    </span>
    <span style="color:#888;font-size:12px;margin-left:10px;">{html.escape(date)}</span>
  </div>
  <h2 style="margin:0 0 18px 0;font-size:17px;line-height:1.4;color:#1a237e;">
    {html.escape(title)}
  </h2>

  {narrative}

  <div style="margin:18px 0 10px 0;">
    <a href="{html.escape(url)}" style="background:#1a237e;color:#fff;
       padding:9px 18px;border-radius:4px;text-decoration:none;font-size:12.5px;
       font-weight:600;">→ Apri il documento sul portale ACN</a>
  </div>

  {_scheda_tecnica(a)}
</div>"""


def build_html_email(articles: list[dict], recipient_name: str = "") -> str:
    now      = datetime.now().strftime("%d/%m/%Y %H:%M")
    today    = datetime.now().strftime("%d/%m/%Y")
    greeting = f"Gentile {recipient_name}," if recipient_name else "Gentile,"
    count    = len(articles)

    alta    = sum(1 for a in articles if "alt" in (a.get("priorita","")).lower())
    media_n = sum(1 for a in articles if "med" in (a.get("priorita","")).lower())
    bassa_n = sum(1 for a in articles if "bas" in (a.get("priorita","")).lower())

    sections = "\n".join(
        _article_section(a, i + 1, count) for i, a in enumerate(articles)
    )

    if count == 1:
        intro = (
            f"{greeting}<br><br>"
            f"di seguito una segnalazione relativa a un aggiornamento "
            f"rilevato in data odierna sul portale ACN, accompagnato da "
            f"una breve analisi di impatto NIS2 e dalle azioni che riteniamo "
            f"opportuno valutare."
        )
    else:
        intro = (
            f"{greeting}<br><br>"
            f"di seguito {count} aggiornamenti rilevati in data odierna "
            f"sul portale ACN, classificati per priorità operativa e corredati "
            f"da analisi di impatto NIS2 e azioni consigliate."
        )

    plurale_seg = "e" if count == 1 else "i"

    return f"""<!DOCTYPE html>
<html lang="it"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NIS2 Regulatory Watch</title></head>
<body style="margin:0;padding:0;background:#eef0f4;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#eef0f4;padding:28px 0;">
<tr><td align="center">
<table width="660" cellpadding="0" cellspacing="0" style="max-width:660px;width:100%;">

  <tr><td style="background:#1a237e;border-radius:8px 8px 0 0;padding:26px 32px;">
    <div style="color:#90caf9;font-size:10px;letter-spacing:3px;font-weight:700;margin-bottom:6px;">
      ACN · NIS2 REGULATORY WATCH</div>
    <div style="color:#fff;font-size:22px;font-weight:700;">
      Aggiornamenti normativi NIS2 — {today}</div>
    <div style="color:#9fa8da;font-size:12.5px;margin-top:6px;">
      {count} segnalazion{plurale_seg} ·
      Alta: {alta} · Media: {media_n} · Bassa: {bassa_n}</div>
  </td></tr>

  <tr><td style="background:#eef0f4;padding:22px 32px 4px 32px;">
    <p style="color:#2c3e50;font-size:14px;line-height:1.65;margin:0 0 18px 0;">
      {intro}
    </p>

    {sections}

    <!-- Parliamone -->
    <div style="background:#fff8e1;border:1px solid #ffe082;border-left:4px solid #f9a825;
                border-radius:6px;padding:18px 22px;margin:6px 0 18px 0;">
      <div style="font-size:11px;font-weight:700;color:#8d6e00;letter-spacing:2px;
                  text-transform:uppercase;margin-bottom:8px;">Parliamone</div>
      <p style="margin:0;color:#5d4e00;font-size:14px;line-height:1.6;">
        Qualora qualche aspetto dell'analisi non risultasse chiaro, o desideriate
        un confronto sull'applicabilità di questi aggiornamenti al vostro
        specifico perimetro NIS2, restiamo a disposizione per un approfondimento
        dedicato. Possiamo supportarvi nell'interpretazione dei documenti, nella
        mappatura degli adempimenti, nella predisposizione della documentazione
        e nel coordinamento con il Punto di Contatto NIS.
      </p>
    </div>

    <div style="background:#e8eaf6;border-radius:6px;padding:13px 18px;
                margin:0 0 8px 0;font-size:11.5px;color:#5d6c8a;line-height:1.55;">
      <strong style="color:#1a237e;">Nota metodologica.</strong>
      Le analisi sono generate da NIS2 Regulatory Watch tramite un sistema di
      monitoraggio automatico del portale ACN integrato con motore di analisi
      AI. Il contenuto non sostituisce la valutazione legale e di compliance
      del soggetto destinatario.
      Fonte ufficiale:
      <a href="https://www.acn.gov.it/portale/nis" style="color:#1a237e;">
        acn.gov.it/portale/nis</a>.
    </div>
  </td></tr>

  <tr><td style="background:#1a237e;border-radius:0 0 8px 8px;padding:14px 32px;text-align:center;">
    <span style="color:#9fa8da;font-size:11px;">
      NIS2 Regulatory Watch · generato il {now} ·
      <a href="https://www.acn.gov.it/portale/nis" style="color:#90caf9;">
        Portale ACN NIS</a>
    </span>
  </td></tr>

</table></td></tr></table>
</body></html>"""


def build_plain_email(articles: list[dict], recipient_name: str = "") -> str:
    """Versione testuale fedele alla narrativa (non solo titolo + URL)."""
    greeting = f"Gentile {recipient_name}," if recipient_name else "Gentile,"
    today    = datetime.now().strftime("%d/%m/%Y")
    count    = len(articles)

    intro_word = "o" if count == 1 else "i"
    lines = [
        greeting,
        "",
        (f"di seguito {count} aggiornament{intro_word} "
         f"rilevat{intro_word} in data {today} sul portale ACN, "
         f"con relativa analisi di impatto NIS2.\n"),
    ]

    for i, a in enumerate(articles, 1):
        prio  = _safe(a.get("priorita"))
        title = _safe(a.get("title"))
        url   = _safe(a.get("url"))
        narr  = _safe(a.get("email_narrativa")).strip()
        lines.append("=" * 70)
        if count > 1:
            lines.append(f"AGGIORNAMENTO {i}/{count} — PRIORITA' {prio.upper()}")
        else:
            lines.append(f"PRIORITA' {prio.upper()}")
        lines.append(f"Oggetto: {title}")
        lines.append(f"Fonte:   {url}")
        lines.append("=" * 70)
        lines.append("")
        lines.append(narr)
        lines.append("")
        lines.append("--- Scheda tecnica ---")
        lines.append(f"Rilevanza NIS2  : {_safe(a.get('rilevanza_nis2'))}")
        lines.append(f"Impatto CISO/GRC: {_safe(a.get('impatto_ciso_grc'))}")
        lines.append(f"Azioni operative: {_safe(a.get('azioni_consigliate'))}")
        lines.append("")

    lines.append("=" * 70)
    lines.append("PARLIAMONE")
    lines.append("=" * 70)
    lines.append(
        "Qualora qualche aspetto dell'analisi non risultasse chiaro, o "
        "desideraste un confronto sull'applicabilita' degli aggiornamenti al "
        "vostro perimetro NIS2, restiamo a disposizione per un approfondimento "
        "dedicato."
    )
    lines.append("")
    lines.append("--")
    lines.append("NIS2 Regulatory Watch - monitoraggio automatico portale ACN")
    lines.append("https://www.acn.gov.it/portale/nis")
    return "\n".join(lines)


# ── SMTP sender ────────────────────────────────────────────────────────────────

def send_articles(
    articles: list[dict],
    recipients: list[dict],
    config: dict | None = None,
) -> tuple[list[str], list[tuple[str, str]]]:
    """
    Send one email per recipient.

    Raises ValueError if credentials are not configured.
    Returns (sent_list, failed_list).
    """
    if not articles:
        return [], []
    if not recipients:
        return [], []

    cfg      = {**_DEFAULTS, **(config or load_email_config())}
    host     = cfg["smtp_host"]
    port     = int(cfg["smtp_port"])
    sender   = cfg["sender_email"].strip()
    password = cfg["sender_password"].strip()
    s_name   = cfg["sender_name"]

    if not sender or not password:
        raise ValueError(
            "Credenziali SMTP mancanti. Configura email e password nella tab Impostazioni."
        )

    count = len(articles)
    if count == 1:
        first_title = _safe(articles[0].get("title"))[:90]
        subject = f"[NIS2 Watch] {first_title}"
    else:
        subject = (
            f"[NIS2 Watch] {count} aggiornamenti normativi NIS2 — "
            f"{datetime.now().strftime('%d/%m/%Y')}"
        )

    sent:   list[str] = []
    failed: list[tuple[str, str]] = []
    ctx     = ssl.create_default_context()

    for recip in recipients:
        email = (recip.get("email") or "").strip()
        name  = (recip.get("name") or "").strip()
        if not email:
            continue
        try:
            html_body = build_html_email(articles, name)
            plain     = build_plain_email(articles, name)

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = f"{s_name} <{sender}>"
            msg["To"]      = f"{name} <{email}>" if name else email
            msg.attach(MIMEText(plain,     "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html",  "utf-8"))

            with smtplib.SMTP(host, port, timeout=15) as srv:
                srv.ehlo()
                srv.starttls(context=ctx)
                srv.login(sender, password)
                srv.sendmail(sender, email, msg.as_string())

            sent.append(email)
        except Exception as e:
            failed.append((email, str(e)))

    return sent, failed
