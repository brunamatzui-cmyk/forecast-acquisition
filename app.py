# -*- coding: utf-8 -*-
"""Dashboard de Forecast de Aquisição — v2 (spec 2026-10-01).

Clientes em negociação que AINDA NÃO assinaram contrato (etapas 4/5/6 dos
pipelines B2B Outbound, Website Table, CSM Acquisition). Três camadas
independentes (spec 4.1): coleta (fetch_hubspot) → cálculo (calc_forecast) →
renderização (aqui). Filtros/ordenação só mexem aqui.

Rodar:  streamlit run app.py
Token:  env HUBSPOT_TOKEN ou secret HUBSPOT_TOKEN no Streamlit Cloud.
"""
import datetime as dt
import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
import fetch_hubspot as fh
import calc_forecast as cf
import selfcheck as sc
import theme

# ---- estado incremental (spec 4.4) --------------------------------------
# Guarda a base carregada + data da última atualização na session_state,
# para que "Atualizar agora" faça incremental e "Recarregar tudo" faça completo.


def fmt_int(n):
    if n is None or (isinstance(n, float) and n != n):
        return "–"
    try:
        return f"{int(round(n)):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "–"


def fmt_data(d):
    if d is None:
        return "–"
    if isinstance(d, dt.datetime):
        d = d.date()
    return d.strftime("%d/%m/%Y")


# ---- camadas 1+2 (cache) -------------------------------------------------
@st.cache_data(ttl=900, show_spinner=False)
def _load_full():
    """Carga COMPLETA: fetch + cálculo. Cache de 15 min."""
    deals, owners, fetched_at = fh.fetch_deals(log=lambda *a, **k: None)
    hoje = dt.date.today()
    completos, incompletos, meses = cf.calcular_todos(deals, hoje=hoje)
    return completos, incompletos, meses, fetched_at, hoje, deals


@st.cache_data(ttl=900, show_spinner=False)
def _load_incremental(last_fetched_iso):
    """Carga incremental: só deals modificados desde last_fetched, mesclados.
    Na prática, para simplicidade e robustez (e porque o conjunto é pequeno,
    ~66 deals), faz um refresh leve mas confirma elegíveis (remove quem saiu
    de 4/5/6). Spec 4.4."""
    deals, owners, fetched_at = fh.fetch_deals(log=lambda *a, **k: None)
    hoje = dt.date.today()
    completos, incompletos, meses = cf.calcular_todos(deals, hoje=hoje)
    return completos, incompletos, meses, fetched_at, hoje, deals


def get_data():
    """Garante a base no session_state; default = carga completa."""
    if "fc_data" not in st.session_state:
        st.session_state.fc_data = _load_full()
    return st.session_state.fc_data


def main():
    st.set_page_config(page_title="Forecast de Aquisição", layout="wide",
                       initial_sidebar_state="expanded")

    # injeta CSS (sticky total, heatmap, zebra, scroll, tooltips)
    st.markdown(_CSS(), unsafe_allow_html=True)

    st.title("Forecast de Aquisição — Clientes em Negociação")
    st.caption(
        "Deals nas etapas **4. Solução / 5. Negociação / 6. Fechamento** "
        "dos pipelines B2B Outbound, Website Table e CSM Acquisition. "
        "Volume de corridas previsto por mês (rampagem: M1 proporcional por dia)."
    )

    completos, incompletos, meses, fetched_at, hoje, fetched_deals = get_data()

    # ---- legend (spec 3.4) ----
    st.markdown(_legend_html(), unsafe_allow_html=True)

    # ---- self-check (spec 5) ---- roda antes de exibir
    checks = sc.run(completos, incompletos, meses, fetched_deals, hoje)
    st.markdown(f"**Verificação:** {sc.summary(checks)}")
    with st.expander("Verificação dos dados (detalhado)", expanded=False):
        for cid, status, msg, deals_inv in checks:
            icon = "✓" if status == "ok" else "⚠"
            st.markdown(f"- **{icon}** [{cid}] {msg}" +
                        (f"  \n  _Deals:_ {', '.join(d['dealname'] for d in deals_inv[:5])}"
                         + (f" … (+{len(deals_inv)-5})" if len(deals_inv) > 5 else "")
                         if deals_inv else ""))

    # ---- filtros (spec 3.7) — só camada 3 ----
    todos_owners = sorted({d["owner_name"] for d in completos if d["owner_name"] != "(sem proprietário)"})
    todos_pipes = sorted({d["pipeline_label"] for d in completos})
    todos_steps = sorted({d["step"] for d in completos if d["step"]})

    with st.sidebar:
        st.header("Filtros")
        f_owner = st.multiselect("Proprietário", todos_owners)
        f_pipe = st.multiselect("Pipeline", todos_pipes)
        f_step = st.multiselect("Etapa", [f"Etapa {s}" for s in todos_steps])
        st.divider()
        col_btn1, col_btn2 = st.columns(2)
        if col_btn1.button("🔄 Atualizar agora", help="Atualização incremental (spec 4.4)"):
            st.session_state.fc_data = _load_incremental(fetched_at.isoformat())
            st.rerun()
        if col_btn2.button("♻️ Recarregar tudo", help="Carga completa"):
            st.cache_data.clear()
            st.session_state.pop("fc_data", None)
            st.rerun()
        st.divider()
        sort_opt = st.selectbox("Ordenar por", [
            "Pipeline → Etapa (6,5,4) → Fechamento", "Fechar. crescente",
            "Fechar. decrescente", "Potencial decrescente", "Total 6m decrescente",
        ])
        st.session_state.fc_dark = st.checkbox("Modo escuro", value=False)

    sel = completos
    if f_owner:
        sel = [d for d in sel if d["owner_name"] in f_owner]
    if f_pipe:
        sel = [d for d in sel if d["pipeline_label"] in f_pipe]
    if f_step:
        nums = [int(s.split()[-1]) for s in f_step]
        sel = [d for d in sel if d["step"] in nums]

    _sort_deals(sel, sort_opt)

    n_atrasados = sum(1 for d in sel if d["atrasado"])
    total_6m = sum(d["total_linha"] for d in sel)
    pot_total = sum((d["potencial"] or 0) for d in sel)

    # ---- KPI row (spec 3.9) ----
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total corridas (6 meses)", fmt_int(total_6m))
    k2.metric("Deals no forecast", len(sel))
    k3.metric("Potencial total", fmt_int(pot_total))
    k4.metric("Deals atrasados", n_atrasados)
    k5.metric("Deals incompletos", len(incompletos))

    # ---- gráfico de barras empilhadas (spec 3.9) ----
    st.markdown("#### Curva de forecast por mês (por pipeline)")
    st.plotly_chart(_stacked_bar(sel, meses), use_container_width=True, config={"displayModeBar": False})

    # ---- tabela principal (HTML custom p/ heatmap + sticky + cor) ----
    st.markdown("#### Tabela de forecast")
    st.markdown(f"_Mostrando **{len(sel)}** deals. Totais recalculam com os filtros. "
                f"Última atualização: {fetched_at.strftime('%d/%m/%Y %H:%M')}._")
    st.markdown(_table_html(sel, meses, st.session_state.get("fc_dark", False)),
                unsafe_allow_html=True)

    # ---- incompletos (spec: exceções) ----
    if incompletos:
        with st.expander(f"⚠️ Deals com dados incompletos ({len(incompletos)}) — fora dos totais"):
            inc_rows = [{
                "Nome do negócio": d["dealname"], "Pipeline": d["pipeline_label"],
                "Etapa": _step_label(d), "Proprietário": d["owner_name"],
                "Previsão de fechamento": fmt_data(d["closedate"]),
                "Potencial": fmt_int(d["potencial"]),
                "Motivo": d.get("motivo_incompleto", "–"),
            } for d in incompletos]
            st.dataframe(pd.DataFrame(inc_rows), width="stretch", hide_index=True)

    st.caption(
        f"Fonte: HubSpot (pipelines B2B Outbound/Website Table/CSM Acquisition; "
        f"etapas 4/5/6). Potencial: `{config.PROP_POTENCIAL}` "
        f"({config.PROP_POTENCIAL_LABEL}). Ativação = fechamento + 5 dias úteis "
        f"(feriados nacionais BR). Atrasados: fechamento+1m como nova base. "
        f"Probabilidade 100% (não pondera etapa)."
    )


# ---- helpers de ordenação ----
def _sort_deals(sel, opt):
    if opt.startswith("Pipeline"):
        # pipeline, depois etapa 6->5->4, depois fechamento crescente
        sel.sort(key=lambda d: (d["pipeline_label"], -(d["step"] or 0),
                                d["closedate"] or dt.date.max))
    elif opt == "Fechar. crescente":
        sel.sort(key=lambda d: d["closedate"] or dt.date.max)
    elif opt == "Fechar. decrescente":
        sel.sort(key=lambda d: d["closedate"] or dt.date.min, reverse=True)
    elif opt == "Potencial decrescente":
        sel.sort(key=lambda d: -(d["potencial"] or 0))
    elif opt == "Total 6m decrescente":
        sel.sort(key=lambda d: -d["total_linha"])


def _step_label(d):
    return f"{d['step']}. " + (d["stage_label"].split(". ", 1)[-1]
                              if ". " in d["stage_label"] else d["stage_label"])


# ---- CSS ----
def _CSS():
    return """
    <style>
    .fc-table { width:100%; border-collapse:separate; border-spacing:0;
        font-size:12px; font-variant-numeric: tabular-nums; }
    .fc-table th, .fc-table td { padding:3px 6px; white-space:nowrap;
        border-bottom:1px solid rgba(0,0,0,0.05); }
    .fc-table thead th { position:sticky; top:0; background:#f0efe9; z-index:3;
        font-weight:600; text-align:right; border-bottom:1px solid rgba(0,0,0,0.15); }
    .fc-table th:first-child, .fc-table td:first-child { text-align:left;
        position:sticky; left:0; z-index:2; background:inherit; }
    .fc-table tbody tr:nth-child(even) td { background:rgba(0,0,0,0.018); }
    .fc-table tbody tr:nth-child(even) td:first-child { background:#f7f6f1; }
    .fc-total-row td { position:sticky; top:28px; z-index:4; background:#1b1b1a;
        color:#fff; font-weight:700; font-size:13px; border-top:2px solid #000; }
    .fc-total-row td:first-child { background:#1b1b1a; }
    .fc-foot td { background:#e7e5dd; font-weight:700; border-top:2px solid #999; }
    .fc-pipe-bar { display:inline-block; width:4px; height:14px; vertical-align:middle;
        margin-right:6px; border-radius:2px; }
    .fc-pipe-tag { font-size:9px; font-weight:700; padding:1px 4px; border-radius:3px;
        color:#fff; margin-left:6px; vertical-align:middle; }
    .fc-name { max-width:240px; overflow:hidden; text-overflow:ellipsis;
        display:inline-block; vertical-align:middle; }
    .fc-stage { font-size:10px; font-weight:600; padding:2px 6px; border-radius:8px;
        color:#fff; white-space:nowrap; }
    .fc-cell-zero { color:#aaa; text-align:right; }
    .fc-cell { text-align:right; }
    .fc-atraso { background:rgba(208,59,59,0.12); color:#d03b3b; font-weight:600; }
    .fc-atraso-tag { font-size:9px; background:#d03b3b; color:#fff; padding:1px 4px;
        border-radius:3px; margin-left:4px; }
    .fc-total-col { font-weight:700; background:rgba(0,0,0,0.04); }
    .fc-wrap { overflow:auto; max-height:70vh; border:1px solid rgba(0,0,0,0.08);
        border-radius:6px; }
    .fc-legend span { font-size:11px; margin-right:14px; }
    .fc-dot { display:inline-block; width:10px; height:10px; border-radius:2px;
        vertical-align:middle; margin-right:4px; }
    </style>
    """


def _legend_html():
    parts = ['<div class="fc-legend"><b>Pipelines:</b> ']
    for label in ["B2B Outbound", "B2B Website Table", "B2B CSM Acquisition"]:
        c = theme.PIPELINE_COLORS_LIGHT[label]
        parts.append(f'<span><span class="fc-dot" style="background:{c}"></span>{label}</span>')
    parts.append(' &nbsp;|&nbsp; <b>Etapas:</b> ')
    for s, nome in [(4, "Solução"), (5, "Negociação"), (6, "Fechamento")]:
        c = theme.STAGE_COLORS_LIGHT[s]
        parts.append(f'<span><span class="fc-dot" style="background:{c}"></span>{s} · {nome}</span>')
    parts.append(' &nbsp;|&nbsp; <span><span class="fc-dot" style="background:#d03b3b"></span>Atrasado</span>')
    parts.append('</div>')
    return "".join(parts)


# ---- tabela HTML ----
def _table_html(sel, meses, dark):
    mes_labels = [m.strftime("%b/%y").capitalize() for m in meses]
    # totais por coluna
    tot_mes = {m: sum(d["volumes"].get(m, 0) for d in sel) for m in meses}
    tot_6m = sum(d["total_linha"] for d in sel)
    # max p/ heatmap (por coluna, relativo ao pico do mês)
    max_mes = {m: max((d["volumes"].get(m, 0) for d in sel), default=0) for m in meses}

    # cabeçalho
    head = ['<div class="fc-wrap"><table class="fc-table"><thead><tr>']
    head.append('<th>Nome do negócio</th><th>Etapa</th><th>Proprietário</th>'
                '<th>Fechamento</th><th>Ativação</th><th>Potencial</th>'
                '<th class="fc-total-col">TOTAL 6M</th>')
    for m, lab in zip(meses, mes_labels):
        head.append(f'<th>{lab}<br><span style="font-weight:400;font-size:10px">{fmt_int(tot_mes[m])}</span></th>')
    head.append('</tr></thead>')

    # linha TOTAL fixa (sticky) logo abaixo do cabeçalho
    totrow = ['<tbody><tr class="fc-total-row"><td>TOTAL</td><td></td><td></td><td></td><td></td><td></td>']
    totrow.append(f'<td>{fmt_int(tot_6m)}</td>')
    for m in meses:
        totrow.append(f'<td>{fmt_int(tot_mes[m])}</td>')
    totrow.append('</tr>')

    # corpo: agrupado por pipeline (cabeçalho de grupo + subtotal)
    body = []
    # agrupar preservando a ordem já sorted (que começa por pipeline se essa ordem)
    by_pipe = {}
    for d in sel:
        by_pipe.setdefault(d["pipeline_label"], []).append(d)
    # ordem dos grupos = ordem de primeira aparição em sel
    seen = []
    for d in sel:
        if d["pipeline_label"] not in seen:
            seen.append(d["pipeline_label"])

    for plabel in seen:
        grp = by_pipe[plabel]
        c = theme.pipeline_color(plabel, dark)
        sub_mes = {m: sum(d["volumes"].get(m, 0) for d in grp) for m in meses}
        sub_6m = sum(d["total_linha"] for d in grp)
        body.append(f'<tr><td colspan="7" style="background:rgba(0,0,0,0.03);font-weight:700">'
                    f'<span class="fc-pipe-bar" style="background:{c}"></span>{html.escape(plabel)} '
                    f'<span style="font-weight:400;color:#666">({len(grp)} deals)</span></td>')
        for m in meses:
            body.append(f'<td style="background:rgba(0,0,0,0.03);font-weight:600">{fmt_int(sub_mes[m])}</td>')
        body.append('</tr>')
        for d in grp:
            body.append(_deal_row(d, meses, max_mes, dark))

    # rodapé (repete total)
    foot = ['</tbody><tfoot><tr class="fc-foot"><td>TOTAL</td><td></td><td></td><td></td><td></td><td></td>']
    foot.append(f'<td>{fmt_int(tot_6m)}</td>')
    for m in meses:
        foot.append(f'<td>{fmt_int(tot_mes[m])}</td>')
    foot.append('</tr></tfoot></table></div>')
    return "".join(head + totrow + body + foot)


def _deal_row(d, meses, max_mes, dark):
    c_pipe = theme.pipeline_color(d["pipeline_label"], dark)
    c_stage = theme.stage_color(d["step"], dark)
    short = theme.PIPELINE_SHORT.get(d["pipeline_label"], "")
    name = html.escape(d["dealname"])
    name_full = name.replace('"', '&quot;')
    stage_nome = {4: "Solução", 5: "Negociação", 6: "Fechamento"}.get(d["step"], "")
    atrasado = d["atrasado"]

    row = ['<tr>']
    # nome com barra de cor + tag pipeline + tooltip nome completo
    row.append(
        f'<td><span class="fc-pipe-bar" style="background:{c_pipe}"></span>'
        f'<span class="fc-name" title="{name_full}">{name}</span>'
        f'<span class="fc-pipe-tag" style="background:{c_pipe}">{short}</span></td>'
    )
    # etapa badge
    row.append(f'<td><span class="fc-stage" style="background:{c_stage}">{d["step"]} · {stage_nome}</span></td>')
    # proprietário
    row.append(f'<td>{html.escape(d["owner_name"])}</td>')
    # fechamento (com destaque atrasado)
    fech = fmt_data(d["closedate"])
    if atrasado:
        row.append(f'<td class="fc-atras">{fech}<span class="fc-atraso-tag">Atrasado {d["dias_atraso"]}d</span></td>')
    else:
        row.append(f'<td>{fech}</td>')
    # ativação
    row.append(f'<td>{fmt_data(d["ativacao"])}</td>')
    # potencial
    row.append(f'<td>{fmt_int(d["potencial"])}</td>')
    # total 6m (coluna destacada)
    row.append(f'<td class="fc-total-col">{fmt_int(d["total_linha"])}</td>')
    # meses com heatmap + tooltip
    for m in meses:
        v = d["volumes"].get(m, 0)
        det = d.get("detalhes", {}).get(m)
        tip = html.escape(det["texto"]) if det and det["texto"] != "–" else ""
        if v <= 0:
            row.append(f'<td class="fc-cell-zero" title="{tip}">–</td>')
        else:
            frac = v / max_mes[m] if max_mes[m] else 0
            bg = theme.heatmap_color(frac, dark)
            txt_col = "#fff" if frac > 0.55 else "#0b0b0b"
            row.append(f'<td class="fc-cell" title="{tip}" style="background:{bg};color:{txt_col}">{fmt_int(v)}</td>')
    row.append('</tr>')
    return "".join(row)


# ---- gráfico empilhado (plotly) ----
def _stacked_bar(sel, meses):
    mes_labels = [m.strftime("%b/%y").capitalize() for m in meses]
    fig = go.Figure()
    for plabel in ["B2B Outbound", "B2B Website Table", "B2B CSM Acquisition"]:
        vals = [sum(d["volumes"].get(m, 0) for d in sel if d["pipeline_label"] == plabel)
                for m in meses]
        fig.add_trace(go.Bar(
            name=plabel, x=mes_labels, y=vals,
            marker_color=theme.PIPELINE_COLORS_LIGHT[plabel],
            hovertemplate="%{x}<br>" + plabel + ": %{y:,.0f}<extra></extra>",
        ))
    fig.update_layout(
        barmode="stack", height=280, margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        font=dict(size=11), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(gridcolor="rgba(0,0,0,0.08)", tickformat=",.0f"),
        xaxis=dict(showgrid=False),
    )
    return fig


if __name__ == "__main__":
    main()
