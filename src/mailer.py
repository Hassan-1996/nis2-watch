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

DATA_DIR = Path(__file__).parent.parent / "data"
CONFIG_PATH = DATA_DIR / "email_config.json"
RECIP_PATH = DATA_DIR / "recipients.json"

_DEFAULTS = {
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "sender_email": "",
    "sender_password": "",
    "sender_name": "NIS2 Regulatory Watch",
}


def _safe(v, default="—") -> str:
    return str(v).strip() if v else default


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
        json.dumps(cfg, ensure_ascii=False, indent=2),
        encoding="utf-8",
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
        json.dumps(recips, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_recipient(name: str, email: str, group: str = "manual") -> None:
    recips = load_recipients()
    email_l = email.strip().lower()

    if not any(r["email"].lower() == email_l for r in recips):
        recips.append({
            "name": name.strip(),
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
    save_recipients([
        r for r in load_recipients()
        if r["email"].lower() != email.lower()
    ])


def _narrative_to_html(text: str) -> str:
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

        if all(re.match(r"^\d+\.\s+", l) for l in lines) and len(lines) > 1:
            cleaned = [re.sub(r"^\d+\.\s+", "", l) for l in lines]

            items = "".join(
                f"<li style='margin-bottom:6px;'>{html.escape(c)}</li>"
                for c in cleaned
            )

            out.append(
                "<ol style='margin:0 0 14px 0;"
                "padding-left:22px;"
                "color:#222;"
                "font-size:14px;"
                "line-height:1.65;'>"
                f"{items}</ol>"
            )
            continue

        if all(l.startswith(("- ", "– ", "• ")) for l in lines) and len(lines) > 1:
            cleaned = [re.sub(r"^[-–•]\s+", "", l) for l in lines]

            items = "".join(
                f"<li style='margin-bottom:6px;'>{html.escape(c)}</li>"
                for c in cleaned
            )

            out.append(
                "<ul style='margin:0 0 14px 0;"
                "padding-left:22px;"
                "color:#222;"
                "font-size:14px;"
                "line-height:1.65;'>"
                f"{items}</ul>"
            )
            continue

        safe = html.escape(para).replace("\n", "<br>")

        safe = re.sub(
            r"(https?://[^\s&lt;]+)",
            r"<a href='\1' style='color:#1a237e;'>\1</a>",
            safe,
        )

        out.append(
            "<p style='margin:0 0 14px 0;"
            "color:#222;"
            "font-size:14px;"
            "line-height:1.65;'>"
            f"{safe}</p>"
        )

    return "\n".join(out)


def _article_section(a: dict, idx: int, total: int) -> str:
    url = _safe(a.get("url"), "#")
    narrative = _narrative_to_html(a.get("email_narrativa", ""))

    separator = ""
    if total > 1 and idx > 1:
        separator = """
        <hr style="border:none;border-top:1px solid #dddddd;margin:28px 0;">
        """

    return f"""
{separator}
<div style="font-family:Arial,sans-serif;
            font-size:14px;
            line-height:1.65;
            color:#222;
            margin-bottom:28px;">

  {narrative}

  <p style="margin:18px 0 0 0;
            color:#222;
            font-size:14px;
            line-height:1.65;">
    <strong>Fonte ufficiale ACN:</strong><br>
    <a href="{html.escape(url)}" style="color:#1a237e;">
      {html.escape(url)}
    </a>
  </p>

</div>
"""


def build_html_email(articles: list[dict], recipient_name: str = "") -> str:
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    sections = "\n".join(
        _article_section(a, i + 1, len(articles))
        for i, a in enumerate(articles)
    )

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>NIS2 Regulatory Watch</title>
</head>

<body style="margin:0;
             padding:0;
             background:#ffffff;
             font-family:Arial,sans-serif;
             color:#222;">

  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#ffffff;padding:24px 0;">
    <tr>
      <td align="center">

        <table width="760" cellpadding="0" cellspacing="0"
               style="max-width:760px;width:100%;background:#ffffff;">

          <tr>
            <td style="padding:0 28px 24px 28px;
                       font-family:Arial,sans-serif;
                       font-size:14px;
                       line-height:1.65;
                       color:#222;">

              {sections}

              <p style="margin:28px 0 0 0;
                        font-size:14px;
                        line-height:1.65;
                        color:#222;">
                Cordiali saluti,<br>
                NIS2 Regulatory Watch
              </p>

              <p style="margin:22px 0 0 0;
                        font-size:11px;
                        line-height:1.5;
                        color:#777;">
                Nota: comunicazione generata sulla base degli aggiornamenti rilevati sul portale ACN.
                Il contenuto non sostituisce una valutazione legale o di compliance specifica.
                Generato il {now}.
              </p>

            </td>
          </tr>

        </table>

      </td>
    </tr>
  </table>

</body>
</html>"""


def build_plain_email(articles: list[dict], recipient_name: str = "") -> str:
    lines = []

    for i, a in enumerate(articles, 1):
        if len(articles) > 1:
            lines.append("=" * 70)
            lines.append(f"AGGIORNAMENTO {i} DI {len(articles)}")
            lines.append("=" * 70)
            lines.append("")

        narr = _safe(a.get("email_narrativa")).strip()
        url = _safe(a.get("url"))

        lines.append(narr)
        lines.append("")
        lines.append("Fonte ufficiale ACN:")
        lines.append(url)
        lines.append("")

    lines.append("Cordiali saluti,")
    lines.append("NIS2 Regulatory Watch")

    return "\n".join(lines)


def send_articles(
    articles: list[dict],
    recipients: list[dict],
    config: dict | None = None,
) -> tuple[list[str], list[tuple[str, str]]]:

    if not articles:
        return [], []

    if not recipients:
        return [], []

    cfg = {**_DEFAULTS, **(config or load_email_config())}

    host = cfg["smtp_host"]
    port = int(cfg["smtp_port"])
    sender = cfg["sender_email"].strip()
    password = cfg["sender_password"].strip()
    s_name = cfg["sender_name"]

    if not sender or not password:
        raise ValueError(
            "Credenziali SMTP mancanti. Configura email e password nella tab Impostazioni."
        )

    if len(articles) == 1:
        first_title = _safe(articles[0].get("title"))[:90]
        subject = f"[NIS2 Watch] {first_title}"
    else:
        subject = (
            f"[NIS2 Watch] {len(articles)} aggiornamenti normativi NIS2 — "
            f"{datetime.now().strftime('%d/%m/%Y')}"
        )

    sent: list[str] = []
    failed: list[tuple[str, str]] = []

    ctx = ssl.create_default_context()

    for recip in recipients:
        email = (recip.get("email") or "").strip()
        name = (recip.get("name") or "").strip()

        if not email:
            continue

        try:
            html_body = build_html_email(articles, name)
            plain_body = build_plain_email(articles, name)

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{s_name} <{sender}>"
            msg["To"] = f"{name} <{email}>" if name else email

            msg.attach(MIMEText(plain_body, "plain", "utf-8"))
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