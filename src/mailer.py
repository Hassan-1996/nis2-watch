"""
mailer.py — Structured email delivery v2.

Fixes:
- Raises ValueError with clear message when config missing (caught in app)
- build_html_email handles None/missing fields gracefully (no KeyError)
- send_articles reconnects per recipient to avoid stale SMTP session
- Plain text fallback properly formatted
- _prio_key consistent with app.py helper
"""

from __future__ import annotations

import json
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

_COLOR  = {"alta": "#c0392b", "media": "#d68910", "bassa": "#1e8449"}
_LABEL  = {"alta": "🔴 ALTA",  "media": "🟡 MEDIA", "bassa": "🟢 BASSA"}


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
        return {**_DEFAULTS, **saved}          # always has all keys
    except Exception:
        return dict(_DEFAULTS)


def save_email_config(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_recipients() -> list[dict]:
    """
    Returns list of dicts: [{name, email, group}]
    group = "auto"   → receives email automatically after each scan
    group = "manual" → receives email only when user triggers manually
    Legacy entries without group default to "manual".
    """
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
    """Return only recipients in the 'auto' group."""
    return [r for r in load_recipients() if r.get("group") == "auto"]


def load_manual_recipients() -> list[dict]:
    """Return only recipients in the 'manual' group."""
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
    """Move a recipient between 'auto' and 'manual' groups."""
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


def _article_block(a: dict) -> str:
    pk     = _prio_key(a.get("priorita", ""))
    color  = _COLOR.get(pk, "#888")
    label  = _LABEL.get(pk, _safe(a.get("priorita")))
    url    = _safe(a.get("url"), "#")
    title  = _safe(a.get("title"))
    date   = _safe(a.get("date") or a.get("first_seen", "")[:10])
    rel    = _safe(a.get("rilevanza_nis2"))
    impact = _safe(a.get("impatto_ciso_grc"))
    azioni = _safe(a.get("azioni_consigliate"))

    return f"""
<div style="background:#fff;border:1px solid #e0e0e0;border-left:4px solid {color};
            border-radius:6px;padding:20px 24px;margin-bottom:20px;font-family:Arial,sans-serif;">
  <div style="margin-bottom:10px;">
    <span style="background:{color};color:#fff;font-size:11px;font-weight:700;
                 padding:3px 10px;border-radius:3px;">{label}</span>
    <span style="color:#999;font-size:12px;margin-left:10px;">{date}</span>
  </div>
  <h2 style="margin:0 0 14px 0;font-size:16px;line-height:1.4;">
    <a href="{url}" style="color:#1a237e;text-decoration:none;">{title}</a>
  </h2>
  <table style="width:100%;border-collapse:collapse;font-size:13px;">
    <tr>
      <td style="width:150px;padding:6px 0;color:#555;font-weight:700;vertical-align:top;">Rilevanza NIS2</td>
      <td style="padding:6px 0;color:#333;">{rel}</td>
    </tr>
    <tr style="background:#fafafa;">
      <td style="padding:6px 8px;color:#555;font-weight:700;vertical-align:top;">Impatto CISO/GRC</td>
      <td style="padding:6px 8px;color:#333;">{impact}</td>
    </tr>
    <tr>
      <td style="padding:6px 0;color:#555;font-weight:700;vertical-align:top;">Azioni consigliate</td>
      <td style="padding:6px 0;color:#333;">{azioni}</td>
    </tr>
  </table>
  <div style="margin-top:14px;">
    <a href="{url}" style="background:#1a237e;color:#fff;padding:8px 16px;
                           border-radius:4px;text-decoration:none;font-size:12px;font-weight:600;">
      → Leggi sul portale ACN
    </a>
  </div>
</div>"""


def build_html_email(articles: list[dict], recipient_name: str = "") -> str:
    now       = datetime.now().strftime("%d/%m/%Y %H:%M")
    greeting  = f"Gentile {recipient_name}," if recipient_name else "Gentile,"
    count     = len(articles)
    alta      = sum(1 for a in articles if "alt" in (a.get("priorita","")).lower())
    media_n   = sum(1 for a in articles if "med" in (a.get("priorita","")).lower())
    bassa_n   = sum(1 for a in articles if "bas" in (a.get("priorita","")).lower())
    blocks    = "\n".join(_article_block(a) for a in articles)

    return f"""<!DOCTYPE html>
<html lang="it"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NIS2 Regulatory Watch</title></head>
<body style="margin:0;padding:0;background:#f5f5f7;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f7;padding:28px 0;">
<tr><td align="center">
<table width="620" cellpadding="0" cellspacing="0" style="max-width:620px;width:100%;">

  <tr><td style="background:#1a237e;border-radius:8px 8px 0 0;padding:26px 30px;">
    <div style="color:#90caf9;font-size:10px;letter-spacing:3px;font-weight:700;margin-bottom:5px;">
      ACN · NIS2 REGULATORY WATCH</div>
    <div style="color:#fff;font-size:21px;font-weight:700;">🛡️ Aggiornamenti Normativi NIS2</div>
    <div style="color:#9fa8da;font-size:12px;margin-top:4px;">{now} — {count} aggiornamento/i</div>
  </td></tr>

  <tr><td style="background:#283593;padding:10px 30px;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td align="center" style="color:#ef9a9a;font-size:13px;font-weight:700;">🔴 Alta: {alta}</td>
      <td align="center" style="color:#ffe082;font-size:13px;font-weight:700;">🟡 Media: {media_n}</td>
      <td align="center" style="color:#a5d6a7;font-size:13px;font-weight:700;">🟢 Bassa: {bassa_n}</td>
    </tr></table>
  </td></tr>

  <tr><td style="background:#f5f5f7;padding:22px 30px;">
    <p style="color:#555;font-size:14px;margin:0 0 18px 0;">
      {greeting}<br><br>
      Di seguito gli aggiornamenti NIS2 rilevati dal portale ACN in data <strong>{now}</strong>,
      classificati per priorità operativa con analisi di impatto CISO/GRC.
    </p>
    {blocks}
    <div style="background:#e8eaf6;border-radius:6px;padding:13px 17px;margin-top:6px;font-size:12px;color:#666;">
      <strong>Nota:</strong> Analisi generata automaticamente da NIS2 Watch.
      Non sostituisce la valutazione legale/compliance.
      Fonte: <a href="https://www.acn.gov.it/portale/nis" style="color:#1a237e;">acn.gov.it/portale/nis</a>
    </div>
  </td></tr>

  <tr><td style="background:#1a237e;border-radius:0 0 8px 8px;padding:14px 30px;text-align:center;">
    <span style="color:#9fa8da;font-size:11px;">NIS2 Regulatory Watch &middot;
      <a href="https://www.acn.gov.it/portale/nis" style="color:#90caf9;">Portale ACN NIS</a>
    </span>
  </td></tr>

</table></td></tr></table>
</body></html>"""


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

    count   = len(articles)
    subject = f"[NIS2 Watch] {count} nuovo/i aggiornamento/i — {datetime.now().strftime('%d/%m/%Y')}"

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
            plain = "\n\n".join(
                f"[{a.get('priorita','?')}] {a.get('title','')}\n{a.get('url','')}"
                for a in articles
            )
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = f"{s_name} <{sender}>"
            msg["To"]      = f"{name} <{email}>" if name else email
            msg.attach(MIMEText(plain, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))

            with smtplib.SMTP(host, port, timeout=15) as srv:
                srv.ehlo()
                srv.starttls(context=ctx)
                srv.login(sender, password)
                srv.sendmail(sender, email, msg.as_string())

            sent.append(email)
        except Exception as e:
            failed.append((email, str(e)))

    return sent, failed
