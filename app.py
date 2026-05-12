"""
app.py — NIS2 AI Regulatory Watch v3
Changes:
  - Toggle letto/da leggere (reversibile) su ogni articolo
  - Due gruppi destinatari: AUTO (invio automatico post-scan) e MANUAL
  - Tab Email riprogettata con gestione visuale dei due gruppi
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import pandas as pd
import streamlit as st

from analyzer import analyze_items, get_available_models
from crawler  import scrape_acn_nis, clear_cache
from mailer   import (
    add_recipient, load_email_config, load_recipients,
    load_auto_recipients, load_manual_recipients,
    remove_recipient, save_email_config, set_recipient_group, send_articles,
)
from store import (
    clear_store, get_all_articles, get_new_articles, get_stats,
    ingest_articles, mark_all_read, mark_all_unread, mark_read,
    mark_unread, toggle_read, auto_send_eligible, record_sent, already_sent_to,
)

# ── Page ───────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="NIS2 Regulatory Watch",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');

html,body,[class*="css"]{font-family:'IBM Plex Sans',sans-serif;}
.stApp{background:#0a0d12;color:#c9d1d9;}
.block-container{padding-top:.8rem;}
section[data-testid="stSidebar"]{display:none;}

.app-hdr{display:flex;align-items:center;gap:14px;padding:16px 0 12px;border-bottom:1px solid #1e2936;margin-bottom:16px;}
.app-hdr h1{font-size:20px;font-weight:700;color:#e6edf3;margin:0;}
.app-hdr .sub{font-size:11px;color:#8b949e;margin:2px 0 0;}
.badge{background:#00d4aa18;border:1px solid #00d4aa55;color:#00d4aa;font-family:'IBM Plex Mono',monospace;font-size:9px;letter-spacing:2px;padding:3px 9px;border-radius:2px;text-transform:uppercase;white-space:nowrap;}
.hdr-stat{text-align:center;}
.hdr-stat .v{font-family:'IBM Plex Mono',monospace;font-size:20px;font-weight:700;line-height:1;}
.hdr-stat .l{font-size:9px;color:#8b949e;letter-spacing:1px;margin-top:2px;}

.p-alta {background:#c0392b;color:#fff;padding:2px 8px;border-radius:3px;font-size:10px;font-weight:700;font-family:'IBM Plex Mono',monospace;}
.p-media{background:#d68910;color:#fff;padding:2px 8px;border-radius:3px;font-size:10px;font-weight:700;font-family:'IBM Plex Mono',monospace;}
.p-bassa{background:#1e8449;color:#fff;padding:2px 8px;border-radius:3px;font-size:10px;font-weight:700;font-family:'IBM Plex Mono',monospace;}

.acard{background:#0d1117;border:1px solid #1e2936;border-left:3px solid #2a3340;border-radius:6px;padding:15px 18px;margin-bottom:10px;}
.acard.alta {border-left-color:#c0392b;}
.acard.media{border-left-color:#d68910;}
.acard.bassa{border-left-color:#1e8449;}
.acard.read {background:#090c0f;opacity:.72;}
.ndot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#00d4aa;margin-right:7px;vertical-align:middle;}
.atitle{font-size:14px;font-weight:600;color:#e6edf3;line-height:1.4;margin-bottom:4px;}
.ameta{font-size:11px;color:#8b949e;font-family:'IBM Plex Mono',monospace;margin-bottom:9px;}
.fl{font-size:9px;text-transform:uppercase;letter-spacing:1.5px;color:#00d4aa;margin-bottom:2px;}
.fv{font-size:12px;color:#c9d1d9;line-height:1.5;margin-bottom:8px;}
.acard a{color:#58a6ff;font-size:11px;}

.dg{font-family:'IBM Plex Mono',monospace;font-size:10px;color:#00d4aa;letter-spacing:2px;text-transform:uppercase;border-bottom:1px solid #1e2936;padding-bottom:5px;margin:20px 0 8px;}

/* Recipient group cards */
.group-card{background:#0d1117;border:1px solid #1e2936;border-radius:8px;padding:16px;margin-bottom:16px;}
.group-card.auto-group{border-top:3px solid #00d4aa;}
.group-card.manual-group{border-top:3px solid #58a6ff;}
.group-title{font-size:13px;font-weight:700;color:#e6edf3;margin-bottom:4px;}
.group-desc{font-size:11px;color:#8b949e;margin-bottom:12px;}
.rrow{background:#0a0d12;border:1px solid #1e2936;border-radius:5px;padding:9px 12px;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center;}
.rn{font-weight:600;color:#e6edf3;font-size:13px;}
.re{color:#8b949e;font-size:11px;font-family:'IBM Plex Mono',monospace;}
.group-badge-auto{background:#00d4aa22;border:1px solid #00d4aa44;color:#00d4aa;font-size:9px;padding:2px 7px;border-radius:10px;font-family:'IBM Plex Mono',monospace;letter-spacing:1px;}
.group-badge-manual{background:#58a6ff22;border:1px solid #58a6ff44;color:#58a6ff;font-size:9px;padding:2px 7px;border-radius:10px;font-family:'IBM Plex Mono',monospace;letter-spacing:1px;}

/* Read state indicator */
.read-badge{display:inline-block;font-size:10px;color:#2ea44f;font-family:'IBM Plex Mono',monospace;}
.unread-badge{display:inline-block;font-size:10px;color:#8b949e;font-family:'IBM Plex Mono',monospace;}

.stButton>button{background:#00d4aa!important;color:#0a0d12!important;font-weight:600!important;border:none!important;border-radius:4px!important;}
.stButton>button:hover{background:#00b894!important;}
div[data-testid="stTabs"] button{color:#8b949e!important;font-size:13px!important;}
div[data-testid="stTabs"] button[aria-selected="true"]{color:#00d4aa!important;border-bottom-color:#00d4aa!important;}
.stTextInput input,.stNumberInput input{background:#0d1117!important;border-color:#1e2936!important;color:#c9d1d9!important;}
.stSelectbox>div>div{background:#0d1117!important;border-color:#1e2936!important;color:#c9d1d9!important;}
.stCheckbox label p{color:#c9d1d9!important;}
</style>
""", unsafe_allow_html=True)


# ── Helpers ────────────────────────────────────────────────────────────────────

def pk(p: str) -> str:
    p = (p or "").lower()
    if "alt" in p: return "alta"
    if "med" in p: return "media"
    if "bas" in p: return "bassa"
    return ""


def pbadge(p: str) -> str:
    k = pk(p)
    return f'<span class="p-{k}">{p}</span>' if k else f'<span style="color:#555;font-size:10px;">{p or "—"}</span>'


def src_badge(s: str) -> str:
    if s == "ollama":
        return '<span style="color:#00d4aa;font-size:10px;font-family:\'IBM Plex Mono\',monospace;">⚡ AI</span>'
    return '<span style="color:#555;font-size:10px;font-family:\'IBM Plex Mono\',monospace;">◎ rule</span>'


def read_badge(is_read: bool) -> str:
    if is_read:
        return '<span class="read-badge">✓ letto</span>'
    return '<span class="unread-badge">● da leggere</span>'


def render_card(art: dict) -> None:
    k       = pk(art.get("priorita", ""))
    is_read = art.get("is_read", False)
    is_new  = art.get("is_new", False)
    dot     = '<span class="ndot"></span>' if is_new else ""
    date    = art.get("date") or art.get("first_seen", "")[:10]
    url     = art.get("url") or "#"
    src     = src_badge(art.get("ai_source", art.get("source", "")))
    rclass  = "read" if is_read else ""

    st.markdown(f"""
    <div class="acard {k} {rclass}">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:3px;">
        <div class="atitle">{dot}{art.get('title','—')}</div>
        {pbadge(art.get('priorita',''))}
      </div>
      <div class="ameta">{date} &nbsp;·&nbsp; {src} &nbsp;·&nbsp; {read_badge(is_read)}</div>
      <div class="fl">Rilevanza NIS2</div>
      <div class="fv">{art.get('rilevanza_nis2','—')}</div>
      <div class="fl">Impatto CISO / GRC</div>
      <div class="fv">{art.get('impatto_ciso_grc','—')}</div>
      <div class="fl">Azioni consigliate</div>
      <div class="fv">{art.get('azioni_consigliate','—')}</div>
      <a href="{url}" target="_blank">→ Vai alla fonte ACN</a>
    </div>""", unsafe_allow_html=True)


def read_toggle_btn(art: dict, key: str) -> None:
    """Single button that toggles between 'Segna letto' and 'Segna da leggere'."""
    is_read = art.get("is_read", False)
    label   = "☑ Segna da leggere" if is_read else "○ Segna letto"
    if st.button(label, key=key):
        toggle_read(art["id"])
        st.rerun()


def _do_send(arts: list[dict], recips: list[dict]) -> None:
    """Helper: send + show result messages. Registra sempre l'invio (anti-duplicati auto)."""
    cfg = load_email_config()
    if not cfg.get("sender_email"):
        st.error("Configura SMTP nella tab ⚙️ Impostazioni.")
        return
    try:
        with st.spinner("Invio in corso…"):
            sent, failed = send_articles(arts, recips, cfg)
        if sent:
            st.success(f"✅ Inviato a: {', '.join(sent)}")
            for a in arts:
                mark_read(a["id"])
                # Anche l'invio manuale viene registrato:
                # se un articolo è inviato manualmente a un destinatario AUTO,
                # non verrà reinviato automaticamente al prossimo scan.
                record_sent(a["id"], sent)
            st.rerun()
        for em, err in failed:
            st.error(f"❌ {em}: {err}")
    except ValueError as e:
        st.error(str(e))


def manual_send_panel(articles: list[dict], key_prefix: str) -> None:
    """
    Panel for manual sending: choose recipients from MANUAL group,
    optionally also include AUTO group members.
    """
    manual_r = load_manual_recipients()
    auto_r   = load_auto_recipients()
    all_r    = load_recipients()

    if not all_r:
        st.warning("Nessun destinatario configurato. Vai alla tab **📧 Email**.")
        return

    st.markdown("**Destinatari**")

    # Show manual group first (pre-selected), auto group optional
    sel_r: list[dict] = []

    if manual_r:
        st.caption("📋 Gruppo Manuale")
        for r in manual_r:
            lbl = f"{r['name']}  —  {r['email']}" if r.get("name") else r["email"]
            if st.checkbox(lbl, value=True, key=f"{key_prefix}_mr_{r['email']}"):
                sel_r.append(r)

    if auto_r:
        st.caption("⚡ Gruppo Automatico (opzionale)")
        for r in auto_r:
            lbl = f"{r['name']}  —  {r['email']}" if r.get("name") else r["email"]
            if st.checkbox(lbl, value=False, key=f"{key_prefix}_ar_{r['email']}"):
                sel_r.append(r)

    st.markdown("**Articoli**")
    sel_all_a = st.checkbox("Tutti", value=True, key=f"{key_prefix}_all_a")
    if sel_all_a:
        arts_to_send = articles
    else:
        chosen = []
        for a in articles:
            if st.checkbox(a["title"][:85], key=f"{key_prefix}_a_{a['id']}"):
                chosen.append(a)
        arts_to_send = chosen

    st.caption(f"{len(arts_to_send)} articoli · {len(sel_r)} destinatari")

    if st.button("📤 Invia email", key=f"{key_prefix}_send"):
        if not sel_r:
            st.error("Seleziona almeno un destinatario.")
        elif not arts_to_send:
            st.error("Seleziona almeno un articolo.")
        else:
            _do_send(arts_to_send, sel_r)


# ── Session state ──────────────────────────────────────────────────────────────

if "last_run"   not in st.session_state: st.session_state.last_run   = None
if "run_errors" not in st.session_state: st.session_state.run_errors = []


# ── Header ─────────────────────────────────────────────────────────────────────

stats = get_stats()

st.markdown(f"""
<div class="app-hdr">
  <span class="badge">ACN · NIS2</span>
  <div>
    <h1>🛡️ NIS2 Regulatory Watch</h1>
    <p class="sub">Monitoraggio automatico aggiornamenti normativi — Portale ACN</p>
  </div>
  <div style="margin-left:auto;display:flex;gap:22px;align-items:center;">
    <div class="hdr-stat"><div class="v" style="color:#00d4aa;">{stats['new']}</div><div class="l">NUOVI</div></div>
    <div class="hdr-stat"><div class="v" style="color:#e88;">{stats['unread']}</div><div class="l">NON LETTI</div></div>
    <div class="hdr-stat"><div class="v" style="color:#c0392b;">{stats['alta']}</div><div class="l">ALTA</div></div>
    <div class="hdr-stat"><div class="v" style="color:#c9d1d9;">{stats['total']}</div><div class="l">TOTALE</div></div>
  </div>
</div>""", unsafe_allow_html=True)


# ── Tabs ───────────────────────────────────────────────────────────────────────

t_new, t_archive, t_email, t_settings = st.tabs([
    f"🆕  Nuovi  ({stats['new']})",
    f"📚  Archivio  ({stats['total']})",
    "📧  Email",
    "⚙️  Impostazioni",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — NUOVI
# ══════════════════════════════════════════════════════════════════════════════

with t_new:
    c1, c2, c3 = st.columns([1.2, 1.2, 4])
    with c1:
        use_cache = st.checkbox("Usa cache (60 min)", value=True, key="uc")
    with c2:
        run_btn = st.button("🔍 Avvia scansione", use_container_width=True, key="run")
    with c3:
        if st.session_state.last_run:
            st.caption(f"Ultima scansione: **{st.session_state.last_run}**")

    # ── Run pipeline ───────────────────────────────────────────────────────────
    if run_btn:
        models = get_available_models()
        model  = models[0] if models else "llama3.2:1b"

        with st.spinner("Crawling portale ACN…"):
            raw_items, errors = scrape_acn_nis(use_cache=use_cache)
            st.session_state.run_errors = errors

        if not raw_items:
            st.warning("Nessun articolo trovato. Portale ACN potrebbe rispondere con 403.")
        else:
            prog = st.progress(0, text="Analisi AI in corso…")
            def _cb(i: int, t: int) -> None:
                prog.progress(i / t, text=f"Analisi {i}/{t}…")
            analyzed = analyze_items(raw_items, model=model, progress_callback=_cb)
            prog.empty()

            new_arts, _ = ingest_articles(analyzed)
            st.session_state.last_run = datetime.now().strftime("%d/%m/%Y %H:%M")

            # ── AUTO send ─────────────────────────────────────────────────────
            # Per ogni destinatario AUTO invia SOLO gli articoli che non gli
            # sono ancora stati inviati automaticamente. Previene i duplicati
            # anche se lo stesso articolo appare in scan consecutivi.
            auto_recips = load_auto_recipients()
            if new_arts and auto_recips:
                cfg = load_email_config()
                if cfg.get("sender_email"):
                    auto_sent_total: list[str] = []
                    for recip in auto_recips:
                        recip_email = recip.get("email", "")
                        # Articoli nuovi non ancora inviati a questo destinatario
                        eligible = [
                            a for a in new_arts
                            if not already_sent_to(a.get("id", ""), recip_email)
                        ]
                        if not eligible:
                            continue
                        try:
                            sent, failed = send_articles(eligible, [recip], cfg)
                            if sent:
                                # Registra per prevenire duplicati futuri
                                for art in eligible:
                                    record_sent(art["id"], sent)
                                auto_sent_total.extend(sent)
                            for em, err in failed:
                                st.warning(f"⚡ Auto-invio fallito per {em}: {err}")
                        except ValueError:
                            pass
                    if auto_sent_total:
                        unique_sent = list(set(auto_sent_total))
                        st.success(
                            f"⚡ Invio automatico: articoli inviati a "
                            f"{', '.join(unique_sent)}"
                        )

            if new_arts:
                st.success(f"✅ {len(new_arts)} nuovo/i articolo/i rilevato/i.")
            else:
                st.info("Nessun nuovo articolo rispetto all'ultima scansione.")
            st.rerun()

    new_arts = get_new_articles()
    order_map = {"alta": 0, "media": 1, "bassa": 2}
    new_arts.sort(key=lambda x: order_map.get(pk(x.get("priorita", "")), 3))

    if not new_arts:
        st.markdown("""<div style="text-align:center;padding:48px;color:#8b949e;">
          <div style="font-size:38px;margin-bottom:10px;">📭</div>
          <div style="color:#c9d1d9;font-size:15px;">Nessun nuovo aggiornamento</div>
          <div style="font-size:12px;margin-top:6px;">Premi <strong>Avvia scansione</strong> per rilevare nuovi contenuti dal portale ACN.</div>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"**{len(new_arts)}** nuovo/i — non presenti nella sessione precedente")

        auto_r   = load_auto_recipients()
        manual_r = load_manual_recipients()
        if auto_r:
            names = ", ".join(r.get("name") or r["email"] for r in auto_r)
            st.info(f"⚡ Invio automatico configurato per: **{names}** (al prossimo scan)")

        st.markdown("---")

        with st.expander("📧 Invio manuale — seleziona destinatari e articoli", expanded=False):
            manual_send_panel(new_arts, "new")

        ba, bb = st.columns([1.5, 1.5])
        with ba:
            if st.button("✓ Segna tutti letti", key="mra_new"):
                mark_all_read(); st.rerun()
        with bb:
            if st.button("○ Segna tutti da leggere", key="mru_new"):
                mark_all_unread(); st.rerun()

        st.markdown("")
        for art in new_arts:
            render_card(art)
            read_toggle_btn(art, key=f"nr_{art['id']}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — ARCHIVIO
# ══════════════════════════════════════════════════════════════════════════════

with t_archive:
    all_arts = get_all_articles()

    if not all_arts:
        st.markdown("""<div style="text-align:center;padding:48px;color:#8b949e;">
          <div style="font-size:38px;margin-bottom:10px;">📂</div>
          <div style="color:#c9d1d9;font-size:15px;">Archivio vuoto</div>
          <div style="font-size:12px;margin-top:6px;">Esegui una scansione per popolare l'archivio.</div>
        </div>""", unsafe_allow_html=True)
    else:
        cf1, cf2, cf3, cf4 = st.columns([1.3, 1.8, 1.4, 2.2])
        with cf1:
            f_stato = st.selectbox("Stato", ["Tutti", "Non letti", "Letti"], key="af1")
        with cf2:
            f_prio  = st.multiselect("Priorità", ["Alta", "Media", "Bassa"],
                                     default=["Alta", "Media", "Bassa"], key="af2")
        with cf3:
            f_sort  = st.selectbox("Ordina", ["Data ↓ (recente)", "Data ↑ (meno recente)", "Priorità"], key="af3")
        with cf4:
            f_q     = st.text_input("🔍 Cerca…", placeholder="keyword nel titolo o testo", key="af4")

        arts = all_arts[:]
        if f_stato == "Non letti": arts = [a for a in arts if not a.get("is_read")]
        elif f_stato == "Letti":   arts = [a for a in arts if a.get("is_read")]
        if f_prio:
            arts = [a for a in arts if any(fp.lower() in (a.get("priorita","")).lower() for fp in f_prio)]
        if f_q:
            q = f_q.lower()
            arts = [a for a in arts
                    if q in (a.get("title","")).lower()
                    or q in (a.get("snippet","")).lower()
                    or q in (a.get("rilevanza_nis2","")).lower()]

        if "Data ↓" in f_sort:   arts.sort(key=lambda x: x.get("first_seen",""), reverse=True)
        elif "Data ↑" in f_sort: arts.sort(key=lambda x: x.get("first_seen",""), reverse=False)
        else:
            om = {"alta":0,"media":1,"bassa":2}
            arts.sort(key=lambda x: om.get(pk(x.get("priorita","")), 3))

        a1, a2, a3, a4 = st.columns([1.2, 1.2, 1.2, 3])
        with a1:
            if st.button("✓ Tutti letti", key="arc_mra"):
                mark_all_read(); st.rerun()
        with a2:
            if st.button("○ Tutti da leggere", key="arc_mru"):
                mark_all_unread(); st.rerun()
        with a3:
            if arts:
                df  = pd.DataFrame(arts)
                csv = df.to_csv(index=False).encode("utf-8")
                st.download_button("⬇️ CSV", csv,
                    file_name=f"nis2_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv", key="arc_dl")

        st.caption(f"{len(arts)} articoli · {stats['unread']} non letti totali")
        st.markdown("---")

        groups: dict[str, list] = defaultdict(list)
        for a in arts:
            day = a.get("first_seen","")[:10] or "—"
            groups[day].append(a)

        asc = "Data ↑" in f_sort
        for day in sorted(groups.keys(), reverse=not asc):
            try:
                day_label = datetime.strptime(day, "%Y-%m-%d").strftime("%A %d %B %Y").capitalize()
            except Exception:
                day_label = day
            unread_n = sum(1 for a in groups[day] if not a.get("is_read"))
            note = f" — {unread_n} non letti" if unread_n else " — tutti letti"
            st.markdown(f'<div class="dg">{day_label}{note}</div>', unsafe_allow_html=True)

            for art in groups[day]:
                render_card(art)
                b1, b2, _ = st.columns([1.2, 0.9, 4])
                with b1:
                    # Reversible toggle
                    read_toggle_btn(art, key=f"arc_t_{art['id']}")
                with b2:
                    toggled = st.session_state.get(f"sp_{art['id']}", False)
                    if st.button("📧 Chiudi" if toggled else "📧 Invia", key=f"arc_s_{art['id']}"):
                        st.session_state[f"sp_{art['id']}"] = not toggled
                        st.rerun()

                if st.session_state.get(f"sp_{art['id']}"):
                    with st.container():
                        st.markdown("**Invia a:**")
                        recips_now = load_recipients()
                        if not recips_now:
                            st.warning("Nessun destinatario. Aggiungi in **📧 Email**.")
                        else:
                            qsel = []
                            qcols = st.columns(min(len(recips_now), 3))
                            for i, r in enumerate(recips_now):
                                group_tag = "⚡" if r.get("group") == "auto" else "📋"
                                lbl2 = f"{group_tag} {r.get('name','')} — {r['email']}".strip()
                                if qcols[i % len(qcols)].checkbox(lbl2, key=f"qcb_{art['id']}_{r['email']}"):
                                    qsel.append(r)
                            if st.button("Invia ora →", key=f"qgo_{art['id']}"):
                                if not qsel:
                                    st.error("Seleziona almeno un destinatario.")
                                else:
                                    _do_send([art], qsel)
                                    st.session_state[f"sp_{art['id']}"] = False

        with st.expander("⚠️ Zona pericolosa — svuota archivio"):
            st.warning("Eliminazione irreversibile di tutti gli articoli salvati.")
            if st.button("🗑️ Svuota archivio completo", key="nuke"):
                clear_store(); st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — EMAIL
# ══════════════════════════════════════════════════════════════════════════════

with t_email:
    st.markdown("""
    <div style="background:#0d1117;border:1px solid #1e2936;border-radius:6px;padding:12px 16px;margin-bottom:18px;font-size:12px;color:#8b949e;">
      <strong style="color:#c9d1d9;">Due gruppi destinatari:</strong><br>
      <span style="color:#00d4aa;">⚡ Automatico</span> — riceve email subito dopo ogni scansione, senza intervento manuale.<br>
      <span style="color:#58a6ff;">📋 Manuale</span> — riceve email solo quando l'utente preme "Invia" esplicitamente.
    </div>
    """, unsafe_allow_html=True)

    el, er = st.columns(2)

    # ── LEFT: recipient management ─────────────────────────────────────────────
    with el:
        recips = load_recipients()
        auto_r   = [r for r in recips if r.get("group") == "auto"]
        manual_r = [r for r in recips if r.get("group") == "manual"]

        # AUTO group
        st.markdown("""<div class="group-card auto-group">
          <div class="group-title">⚡ Gruppo Automatico</div>
          <div class="group-desc">Questi destinatari ricevono email automaticamente ad ogni scan con nuovi articoli.</div>
        </div>""", unsafe_allow_html=True)

        if auto_r:
            for r in auto_r:
                rc1, rc2, rc3 = st.columns([3, 1.2, 0.6])
                with rc1:
                    st.markdown(f"""<div class="rrow">
                      <div class="rn">{r.get('name','') or '—'}</div>
                      <div class="re">{r['email']}</div>
                    </div>""", unsafe_allow_html=True)
                with rc2:
                    if st.button("→ Manuale", key=f"tomn_{r['email']}"):
                        set_recipient_group(r["email"], "manual"); st.rerun()
                with rc3:
                    if st.button("✕", key=f"del_a_{r['email']}"):
                        remove_recipient(r["email"]); st.rerun()
        else:
            st.caption("Nessun destinatario automatico configurato.")

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        # MANUAL group
        st.markdown("""<div class="group-card manual-group">
          <div class="group-title">📋 Gruppo Manuale</div>
          <div class="group-desc">Questi destinatari ricevono email solo su invio esplicito dall'utente.</div>
        </div>""", unsafe_allow_html=True)

        if manual_r:
            for r in manual_r:
                rc1, rc2, rc3 = st.columns([3, 1.2, 0.6])
                with rc1:
                    st.markdown(f"""<div class="rrow">
                      <div class="rn">{r.get('name','') or '—'}</div>
                      <div class="re">{r['email']}</div>
                    </div>""", unsafe_allow_html=True)
                with rc2:
                    if st.button("→ Auto", key=f"toau_{r['email']}"):
                        set_recipient_group(r["email"], "auto"); st.rerun()
                with rc3:
                    if st.button("✕", key=f"del_m_{r['email']}"):
                        remove_recipient(r["email"]); st.rerun()
        else:
            st.caption("Nessun destinatario manuale configurato.")

        st.markdown("---")
        st.markdown("#### ➕ Aggiungi destinatario")
        an    = st.text_input("Nome (opzionale)", placeholder="Mario Rossi", key="an")
        ae    = st.text_input("Email *", placeholder="mario@example.com", key="ae")
        ag    = st.radio("Gruppo", ["Manuale 📋", "Automatico ⚡"], horizontal=True, key="ag")
        grp   = "auto" if "Auto" in ag else "manual"

        if st.button("Aggiungi destinatario", key="add_r"):
            if ae and "@" in ae and "." in ae:
                add_recipient(an, ae, grp)
                st.success(f"Aggiunto: {ae} → gruppo {'automatico ⚡' if grp == 'auto' else 'manuale 📋'}")
                st.rerun()
            else:
                st.error("Inserisci un indirizzo email valido.")

    # ── RIGHT: manual bulk send ────────────────────────────────────────────────
    with er:
        st.markdown("### 📤 Invio manuale")
        all_stored = get_all_articles()
        all_r      = load_recipients()

        if not all_stored:
            st.info("Nessun articolo in archivio da inviare.")
        elif not all_r:
            st.warning("Aggiungi almeno un destinatario nella colonna sinistra.")
        else:
            mode = st.radio("Articoli da inviare",
                ["Solo nuovi", "Solo non letti", "Seleziona manualmente"],
                horizontal=True, key="em_mode")

            if mode == "Solo nuovi":
                pool = [a for a in all_stored if a.get("is_new")]
            elif mode == "Solo non letti":
                pool = [a for a in all_stored if not a.get("is_read")]
            else:
                pool = all_stored

            if mode == "Seleziona manualmente":
                chosen = []
                for a in pool[:30]:
                    if st.checkbox(a["title"][:80], key=f"em_a_{a['id']}"):
                        chosen.append(a)
                arts_to_send = chosen
            else:
                arts_to_send = pool

            st.markdown("**Destinatari:**")
            sel_r: list[dict] = []

            manual_now = load_manual_recipients()
            auto_now   = load_auto_recipients()

            if manual_now:
                st.caption("📋 Gruppo Manuale")
                all_m = st.checkbox("Tutti manuale", value=True, key="em_allm")
                for r in manual_now:
                    lbl = f"{r.get('name','') or r['email']}  —  {r['email']}"
                    if st.checkbox(lbl, value=all_m, key=f"em_mr_{r['email']}"):
                        sel_r.append(r)

            if auto_now:
                st.caption("⚡ Gruppo Automatico (opzionale)")
                for r in auto_now:
                    lbl = f"{r.get('name','') or r['email']}  —  {r['email']}"
                    if st.checkbox(lbl, value=False, key=f"em_ar_{r['email']}"):
                        sel_r.append(r)

            st.caption(f"{len(arts_to_send)} articoli · {len(sel_r)} destinatari")

            if st.button("📤 Invia", key="em_send"):
                if not arts_to_send:
                    st.error("Nessun articolo selezionato.")
                elif not sel_r:
                    st.error("Nessun destinatario selezionato.")
                else:
                    _do_send(arts_to_send, sel_r)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — IMPOSTAZIONI
# ══════════════════════════════════════════════════════════════════════════════

with t_settings:
    sl, sr = st.columns(2)

    with sl:
        st.markdown("### 📧 Configurazione SMTP")
        cfg    = load_email_config()
        s_host = st.text_input("Host SMTP",        value=cfg.get("smtp_host","smtp.gmail.com"), key="sh")
        s_port = st.number_input("Porta SMTP",     value=int(cfg.get("smtp_port",587)), min_value=1, max_value=65535, key="sp2")
        s_name = st.text_input("Nome mittente",    value=cfg.get("sender_name","NIS2 Regulatory Watch"), key="sn2")
        s_mail = st.text_input("Email mittente *", value=cfg.get("sender_email",""), key="sm", placeholder="noreply@yourdomain.com")
        s_pass = st.text_input("Password / App Password *", value=cfg.get("sender_password",""), key="spw", type="password")

        st.markdown("""<small style="color:#8b949e;">
        💡 <strong>Gmail</strong>: usa <em>App Password</em>, non la password normale.<br>
        <a href="https://myaccount.google.com/apppasswords" target="_blank" style="color:#58a6ff;">→ Crea App Password</a>
        </small>""", unsafe_allow_html=True)

        if st.button("💾 Salva configurazione SMTP", key="save_smtp"):
            save_email_config({
                "smtp_host": s_host, "smtp_port": s_port,
                "sender_name": s_name, "sender_email": s_mail,
                "sender_password": s_pass,
            })
            st.success("Configurazione SMTP salvata.")

        st.markdown("#### 📨 Invia email di test")
        t_mail = st.text_input("Email di test", placeholder="tuo@email.com", key="tm")
        if st.button("Invia test", key="t_send"):
            if not t_mail or "@" not in t_mail:
                st.error("Inserisci un'email valida.")
            elif not s_mail:
                st.error("Configura prima l'email mittente.")
            else:
                test_art = {
                    "id": "test-001", "title": "Test NIS2 Watch — verifica SMTP",
                    "url": "https://www.acn.gov.it/portale/nis",
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "rilevanza_nis2": "Email di test dalla configurazione SMTP.",
                    "impatto_ciso_grc": "Nessun impatto reale — test di configurazione.",
                    "azioni_consigliate": "Se ricevi questa email, SMTP è configurato correttamente.",
                    "priorita": "Bassa", "ai_source": "test",
                    "first_seen": datetime.now().isoformat(),
                    "is_new": False, "is_read": False,
                }
                cfg_t = {"smtp_host":s_host,"smtp_port":s_port,"sender_name":s_name,"sender_email":s_mail,"sender_password":s_pass}
                try:
                    with st.spinner("Invio…"):
                        sent, failed = send_articles([test_art],[{"name":"Test","email":t_mail,"group":"manual"}],cfg_t)
                    if sent: st.success(f"✅ Test inviato a {t_mail}")
                    else:
                        for _, err in failed: st.error(f"❌ {err}")
                except ValueError as e:
                    st.error(str(e))

    with sr:
        st.markdown("### 🤖 AI & Crawler")
        models = get_available_models()
        if models:
            st.success(f"✅ Ollama attivo — {len(models)} modello/i disponibile/i")
            st.selectbox("Modello attivo", models, key="mod_sel")
        else:
            st.warning("⚠️ Ollama non raggiungibile — modalità rule-based attiva")
            st.code("ollama pull llama3.2:1b\nollama serve", language="bash")

        st.markdown("---")
        st.markdown("### 🗄️ Cache scraping")
        if st.button("🗑️ Svuota cache", key="clr_cache"):
            clear_cache()
            st.success("Cache rimossa — la prossima scansione farà un fetch live.")
        st.caption("Cache TTL: 60 min. Svuotarla forza un nuovo fetch del portale ACN.")

        st.markdown("---")
        auto_cnt   = len(load_auto_recipients())
        manual_cnt = len(load_manual_recipients())
        st.markdown("### ℹ️ Stato sistema")
        st.json({
            "articoli_totali":       stats["total"],
            "non_letti":             stats["unread"],
            "nuovi_ultima_run":      stats["new"],
            "alta_priorita":         stats["alta"],
            "destinatari_auto":      auto_cnt,
            "destinatari_manuale":   manual_cnt,
            "timestamp":             datetime.now().strftime("%d/%m/%Y %H:%M"),
            "ai_engine":             "Ollama" if models else "rule-based",
        })
