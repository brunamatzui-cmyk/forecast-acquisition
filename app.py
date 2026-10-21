# -*- coding: utf-8 -*-
"""Dashboard de Forecast de Aquisição — v2 (spec 2026-10-15).

Três abas:
  1. Negociação — deals nas etapas 4/5/6 (ainda não assinaram).
  2. Ativação   — deals na etapa 7 Ativação (rampa desde o closedate).
  3. Consolidado — soma das duas + gráfico empilhado + KPI 6 meses.

Três camadas independentes (spec 4.1): coleta (fetch_hubspot) → cálculo
(calc_forecast) → renderização (aqui). Filtros/ordenação só mexem aqui.

Mudanças v2: (A) filtros sidebar, (B) ordenação por clique via st.dataframe
nativo (valores numéricos reais, não texto), (C) visual mais limpo, (D) aba
Ativação. A linha TOTAL fica num dataframe separado (não ordenável).

Rodar:  streamlit run app.py
Token:  env HUBSPOT_TOKEN ou secret HUBSPOT_TOKEN no Streamlit Cloud.
"""
import datetime as dt

import numpy as np
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


def mes_label(m):
    """out/26, nov/26..."""
    nomes = ["jan", "fev", "mar", "abr", "mai", "jun",
             "jul", "ago", "set", "out", "nov", "dez"]
    return f"{nomes[m.month - 1]}/{str(m.year)[-2:]}"


# ---- camadas 1+2 (cache) -------------------------------------------------
# Funções nomeadas _v2 p/ invalidar caches obsoletos do deploy anterior: a
# chave do st.cache_data inclui a identidade da função, então renomear busta
# qualquer entrada antiga (o deploy pré-v2 cacheava um 6-tupla; o novo código
# devolve 7 — desempacotar 7 de 6 levantava ValueError no Cloud).
@st.cache_data(ttl=900, show_spinner=False)
def _load_full_v2():
    """Carga COMPLETA: fetch + cálculo. Cache de 15 min."""
    deals, owners, fetched_at = fh.fetch_deals(log=lambda *a, **k: None)
    hoje = dt.date.today()
    neg, ativ, inc, meses = cf.calcular_todos(deals, hoje=hoje)
    neg_15 = cf._calc_negociacao_15_safe(neg, meses, hoje)
    ativ_15 = cf._calc_ativacao_15_safe(ativ, meses, hoje)
    return neg, ativ, inc, meses, fetched_at, hoje, deals, neg_15, ativ_15


@st.cache_data(ttl=900, show_spinner=False)
def _load_incremental_v2(last_fetched_iso):
    """Carga incremental: só deals modificados desde last_fetched, mesclados.
    Na prática, para simplicidade e robustez (conjunto pequeno), faz um refresh
    leve mas confirma elegíveis (remove quem saiu de 4/5/6/7). Spec 4.4."""
    deals, owners, fetched_at = fh.fetch_deals(log=lambda *a, **k: None)
    hoje = dt.date.today()
    neg, ativ, inc, meses = cf.calcular_todos(deals, hoje=hoje)
    neg_15 = cf._calc_negociacao_15_safe(neg, meses, hoje)
    ativ_15 = cf._calc_ativacao_15_safe(ativ, meses, hoje)
    return neg, ativ, inc, meses, fetched_at, hoje, deals, neg_15, ativ_15


def get_data():
    """Garante a base no session_state; default = carga completa.
    Limpa o cache uma vez por sessão (cinto de segurança p/ mudança de shape)."""
    if not st.session_state.get("fc_cache_busted"):
        st.cache_data.clear()
        st.session_state.fc_cache_busted = True
    if "fc_data" not in st.session_state:
        st.session_state.fc_data = _load_full_v2()
    return st.session_state.fc_data


def main():
    st.set_page_config(page_title="Forecast de Aquisição", layout="wide",
                       initial_sidebar_state="expanded")

    # CSS mínimo: visual limpo (spec C). Sem bordas pesadas, espaçamento uniforme.
    st.markdown(_CSS(), unsafe_allow_html=True)

    st.title("Forecast de Aquisição")
    st.caption(
        "Deals em **Negociação** (etapas 4/5/6) e **Ativação** (etapa 7) dos "
        "pipelines B2B Outbound, Website Table e CSM Acquisition. "
        "Volume de corridas previsto por mês (rampagem)."
    )

    neg, ativ, inc, meses, fetched_at, hoje, fetched_deals, neg_15, ativ_15 = get_data()

    # ---- self-check (spec 5) ---- roda antes de exibir
    checks = sc.run(neg, ativ, inc, meses, fetched_deals, hoje)
    st.markdown(f"**Verificação:** {sc.summary(checks)}")
    with st.expander("Verificação dos dados (detalhado)", expanded=False):
        for cid, status, msg, deals_inv in checks:
            icon = "✓" if status == "ok" else "⚠"
            st.markdown(f"- **{icon}** [{cid}] {msg}" +
                        (f"  \n  _Deals:_ {', '.join(d['dealname'] for d in deals_inv[:5])}"
                         + (f" … (+{len(deals_inv)-5})" if len(deals_inv) > 5 else "")
                         if deals_inv else ""))

    # ---- filtros (spec A) — só camada 3, sobre o cache ----
    todos_deals = neg + ativ
    todos_owners = sorted({d["owner_name"] for d in todos_deals
                           if d["owner_name"] != "(sem proprietário)"})
    todos_pipes = sorted({d["pipeline_label"] for d in todos_deals})
    # etapas 4/5/6 só pra aba Negociação
    todos_steps = sorted({d["step"] for d in neg if d["step"]})

    with st.sidebar:
        st.header("Filtros")
        f_pipe = st.multiselect("Pipeline", todos_pipes, key="f_pipe")
        f_owner = st.multiselect("Proprietário", todos_owners, key="f_owner")
        f_step = st.multiselect("Etapa (só Negociação)",
                                [f"Etapa {s}" for s in todos_steps], key="f_step")
        if st.button("🧹 Limpar filtros"):
            for k in ("f_pipe", "f_owner", "f_step"):
                st.session_state.pop(k, None)
            st.rerun()
        st.divider()
        col_btn1, col_btn2 = st.columns(2)
        if col_btn1.button("🔄 Atualizar agora", help="Atualização incremental (spec 4.4)"):
            st.session_state.fc_data = _load_incremental_v2(fetched_at.isoformat())
            st.rerun()
        if col_btn2.button("♻️ Recarregar tudo", help="Carga completa"):
            st.cache_data.clear()
            st.session_state.pop("fc_data", None)
            st.rerun()
        st.divider()
        st.session_state.fc_agrupar = st.checkbox(
            "Agrupar por pipeline", value=False,
            help="Quando desligado (padrão), a ordenação por clique é global.")
        st.session_state.fc_dark = st.checkbox("Modo escuro", value=False)

    dark = st.session_state.get("fc_dark", False)
    agrupar = st.session_state.get("fc_agrupar", False)

    def aplica_filtros(lista):
        sel = list(lista)
        if f_pipe:
            sel = [d for d in sel if d["pipeline_label"] in f_pipe]
        if f_owner:
            sel = [d for d in sel if d["owner_name"] in f_owner]
        return sel

    neg_sel = aplica_filtros(neg)
    if f_step:
        nums = [int(s.split()[-1]) for s in f_step]
        neg_sel = [d for d in neg_sel if d["step"] in nums]
    ativ_sel = aplica_filtros(ativ)
    # A aba "Negociação Potencial atualizado" usa os MESMOS filtros da aba
    # Negociação (mesmos deals, mesmos filtros pipeline/owner/etapa). Como
    # neg_15 é paralelo a neg (mesma ordem), aplicamos os filtros sobre os
    # deal_ids que sobreviveram em neg_sel.
    neg_15_sel = _filtrar_paralelo(neg_15, neg_sel)
    # Mesmo raciocínio p/ "Ativação Potencial Atualizado": ativ_15 é paralelo
    # a ativ (mesma ordem), usamos os deal_ids que sobreviveram em ativ_sel.
    ativ_15_sel = _filtrar_paralelo(ativ_15, ativ_sel)

    # ordenação padrão (quando nada clicado): pipeline > etapa (6,5,4) > fechamento
    _sort_padrao(neg_sel)
    _sort_padrao(ativ_sel)
    _sort_padrao(neg_15_sel)
    _sort_padrao(ativ_15_sel)

    # ---- abas ----
    tab_neg, tab_neg15, tab_ativ, tab_ativ15, tab_cons = st.tabs(
        ["Negociação", "Negociação Potencial atualizado", "Ativação",
         "Ativação Potencial Atualizado", "Consolidado"])

    with tab_neg:
        _render_negociacao(neg_sel, inc, meses, fetched_at, dark, agrupar)
    with tab_neg15:
        _render_negociacao_15(neg_15_sel, inc, meses, fetched_at, dark, agrupar)
    with tab_ativ:
        _render_ativacao(ativ_sel, inc, meses, fetched_at, dark, agrupar)
    with tab_ativ15:
        _render_ativacao_15(ativ_15_sel, inc, meses, fetched_at, dark, agrupar)
    with tab_cons:
        _render_consolidado(neg_sel, ativ_sel, meses, dark)

    st.caption(
        f"Fonte: HubSpot (pipelines B2B Outbound/Website Table/CSM Acquisition). "
        f"Potencial: `{config.PROP_POTENCIAL_LABEL}`. "
        f"Negociação: ativação = fechamento + 5 dias úteis (feriados BR). "
        f"Ativação: rampa desde o fechamento real (`closedate`). "
        f"Curva <20k: 25/50/100 · ≥20k: 25/50/75/100. "
        f"Probabilidade 100% (não pondera etapa). "
        f"Última atualização: {fetched_at.strftime('%d/%m/%Y %H:%M')}."
    )


# ---- ordenação padrão (spec B: pipeline > etapa 6,5,4 > fechamento) ------
def _sort_padrao(sel):
    sel.sort(key=lambda d: (d["pipeline_label"], -(d["step"] or 0),
                            d.get("previsao_fechamento") or dt.date.max))


# ---- renderização: Negociação -------------------------------------------
def _render_negociacao(sel, incompletos, meses, fetched_at, dark, agrupar):
    inc_neg = [d for d in incompletos if d.get("origem", "negociacao") == "negociacao"]
    total_6m = sum(d["total_linha"] for d in sel)
    pot_total = sum((d["potencial"] or 0) for d in sel)
    n_atrasados = sum(1 for d in sel if d["atrasado"])

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total corridas (6 meses)", fmt_int(total_6m))
    k2.metric("Deals", len(sel))
    k3.metric("Potencial total", fmt_int(pot_total))
    k4.metric("Atrasados", n_atrasados)
    k5.metric("Incompletos", len(inc_neg))

    st.markdown(f"_Mostrando **{len(sel)}** deals. Última atualização: "
                f"{fetched_at.strftime('%d/%m/%Y %H:%M')}._")

    df = _df_negociacao(sel, meses)
    _linha_total(df, meses, label="TOTAL")
    _tabela_principal(df, meses, dark, agrupar, aba="negociacao")
    _linha_total(df, meses, label="TOTAL")

    _incompletos_expander(inc_neg, aba="negociacao", dark=dark)


def _filtrar_paralelo(lista_paralela, lista_filtrada):
    """Filtra `lista_paralela` (neg_15) mantendo só os deals cujo deal_id está
    em `lista_filtrada` (neg_sel), preservando a ordem de lista_paralela.
    Garante que a aba 15% mostre exatamente os mesmos deals da aba Negociação
    sob os filtros ativos, sem duplicar a lógica de filtro."""
    ids = {d["deal_id"] for d in lista_filtrada}
    return [d for d in lista_paralela if d["deal_id"] in ids]


# ---- renderização: Negociação Potencial atualizado (forecast sobre 15%) ------
def _render_negociacao_15(sel, incompletos, meses, fetched_at, dark, agrupar):
    """Mesma estrutura da aba Negociação, mas com a coluna "15% potencial"
    à direita de "Potencial" e o forecast (TOTAL 6M + meses) baseado em 15%.

    sel: lista de deals da variante calcular_negociacao_15 (potencial_15,
         volumes/total_linha sobre 15%; potencial = ORIGINAL preservado).
    """
    inc_neg = [d for d in incompletos if d.get("origem", "negociacao") == "negociacao"]
    total_6m = sum(d["total_linha"] for d in sel)
    pot_15_total = sum((d["potencial_15"] or 0) for d in sel)
    pot_total = sum((d["potencial"] or 0) for d in sel)
    n_atrasados = sum(1 for d in sel if d["atrasado"])

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total corridas (6 meses)", fmt_int(total_6m))
    k2.metric("Deals", len(sel))
    k3.metric("Potencial total (15%)", fmt_int(pot_15_total))
    k4.metric("Atrasados", n_atrasados)
    k5.metric("Incompletos", len(inc_neg))

    st.markdown(
        f"_Mostrando **{len(sel)}** deals com forecast baseado em **15% do "
        f"potencial**. Potencial original: {fmt_int(pot_total)} → "
        f"15%: {fmt_int(pot_15_total)}. Última atualização: "
        f"{fetched_at.strftime('%d/%m/%Y %H:%M')}._")

    df = _df_negociacao_15(sel, meses)
    _linha_total(df, meses, label="TOTAL")
    _tabela_principal(df, meses, dark, agrupar, aba="negociacao_15")
    _linha_total(df, meses, label="TOTAL")

    _incompletos_expander(inc_neg, aba="negociacao", dark=dark)


def _render_ativacao(sel, incompletos, meses, fetched_at, dark, agrupar):
    inc_ativ = [d for d in incompletos if d.get("origem", "negociacao") == "ativacao"]
    total_6m = sum(d["total_linha"] for d in sel)
    pot_total = sum((d["potencial"] or 0) for d in sel)
    # inconsistências: > 90 dias em ativação e ainda abaixo de 100% (spec D.3)
    inconst = [d for d in sel if (d.get("dias_ativacao") or 0) > 90
               and d["total_linha"] < (d["potencial"] or 0) * 6 - 1]

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total corridas (6 meses)", fmt_int(total_6m))
    k2.metric("Deals em ativação", len(sel))
    k3.metric("Potencial total", fmt_int(pot_total))
    k4.metric("Inconsistentes (>90d <100%)", len(inconst))
    k5.metric("Incompletos", len(inc_ativ))

    st.markdown(f"_Mostrando **{len(sel)}** deals em ativação. Última atualização: "
                f"{fetched_at.strftime('%d/%m/%Y %H:%M')}._")

    df = _df_ativacao(sel, meses)
    _linha_total(df, meses, label="TOTAL")
    _tabela_principal(df, meses, dark, agrupar, aba="ativacao")
    _linha_total(df, meses, label="TOTAL")

    _incompletos_expander(inc_ativ, aba="ativacao", dark=dark)


# ---- renderização: Ativação Potencial Atualizado (forecast sobre 15%) ------
def _render_ativacao_15(sel, incompletos, meses, fetched_at, dark, agrupar):
    """Mesma estrutura da aba Ativação, mas com a coluna "15% potencial" à
    direita de "Potencial mês (total)" e o forecast (meses + TOTAL 6M) baseado
    em 15%. "% rampa mês atual" é inalterada (fração da curva, independe do
    potencial); "Corridas esperadas mês atual" e meses são 15%-based.

    sel: lista de deals da variante calcular_ativacao_15 (potencial_15,
         volumes/total_linha sobre 15%; potencial = ORIGINAL preservado;
         dias_ativacao/entrada_ativacao preservados).
    """
    inc_ativ = [d for d in incompletos if d.get("origem", "negociacao") == "ativacao"]
    total_6m = sum(d["total_linha"] for d in sel)
    pot_15_total = sum((d["potencial_15"] or 0) for d in sel)
    pot_total = sum((d["potencial"] or 0) for d in sel)
    # inconsistências: > 90 dias em ativação e ainda abaixo de 100% (sobre pot15)
    inconst = [d for d in sel if (d.get("dias_ativacao") or 0) > 90
               and d["total_linha"] < (d["potencial_15"] or 0) * 6 - 1]

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total corridas (6 meses)", fmt_int(total_6m))
    k2.metric("Deals em ativação", len(sel))
    k3.metric("Potencial total (15%)", fmt_int(pot_15_total))
    k4.metric("Inconsistentes (>90d <100%)", len(inconst))
    k5.metric("Incompletos", len(inc_ativ))

    st.markdown(
        f"_Mostrando **{len(sel)}** deals em ativação com forecast baseado em "
        f"**15% do potencial**. Potencial original: {fmt_int(pot_total)} → "
        f"15%: {fmt_int(pot_15_total)}. Última atualização: "
        f"{fetched_at.strftime('%d/%m/%Y %H:%M')}._")

    df = _df_ativacao_15(sel, meses)
    _linha_total(df, meses, label="TOTAL")
    _tabela_principal(df, meses, dark, agrupar, aba="ativacao_15")
    _linha_total(df, meses, label="TOTAL")

    _incompletos_expander(inc_ativ, aba="ativacao", dark=dark)


def _render_consolidado(neg_sel, ativ_sel, meses, dark):
    total_6m = sum(d["total_linha"] for d in neg_sel) + sum(d["total_linha"] for d in ativ_sel)
    n_neg = len(neg_sel); n_ativ = len(ativ_sel)

    k1, k2, k3 = st.columns(3)
    k1.metric("Total corridas (6 meses)", fmt_int(total_6m))
    k2.metric("Deals em negociação", n_neg)
    k3.metric("Deals em ativação", n_ativ)

    st.markdown("#### Curva de forecast por mês (Negociação vs. Ativação)")
    st.plotly_chart(_stacked_bar_consolidado(neg_sel, ativ_sel, meses),
                    use_container_width=True, config={"displayModeBar": False})

    st.markdown("#### Tabela consolidada por mês")
    # tabela mês x (Negociação, Ativação, Total)
    rows = []
    for m in meses:
        vn = sum(d["volumes"].get(m, 0) for d in neg_sel)
        va = sum(d["volumes"].get(m, 0) for d in ativ_sel)
        rows.append({"Mês": mes_label(m), "Negociação": int(vn),
                     "Ativação": int(va), "Total": int(vn + va)})
    tot_vn = sum(r["Negociação"] for r in rows)
    tot_va = sum(r["Ativação"] for r in rows)
    rows.append({"Mês": "TOTAL 6 MESES", "Negociação": int(tot_vn),
                 "Ativação": int(tot_va), "Total": int(tot_vn + tot_va)})
    dfc = pd.DataFrame(rows)
    cc = {"Negociação": st.column_config.NumberColumn(format="%d"),
          "Ativação": st.column_config.NumberColumn(format="%d"),
          "Total": st.column_config.NumberColumn(format="%d")}
    st.dataframe(_zebra_styler(dfc, dark), column_config=cc,
                 use_container_width=True, hide_index=True)


# ---- dataframes por aba --------------------------------------------------
def _df_negociacao(sel, meses):
    # Schema fixo (garante colunas + dtypes certos mesmo com sel vazio).
    # Valores numéricos como int (spec B: nunca converter p/ texto — senão a
    # ordenação por clique vira alfabética). Datas como date.
    data = {
        "Nome do negócio": [], "Pipeline": [], "Etapa": [], "Proprietário": [],
        "Fechamento": [], "Ativação": [], "Potencial": [], "TOTAL 6M": [],
    }
    for m in meses:
        data[mes_label(m)] = []
    for d in sel:
        data["Nome do negócio"].append(d["dealname"])
        data["Pipeline"].append(d["pipeline_label"])
        data["Etapa"].append(_step_label(d))
        data["Proprietário"].append(d["owner_name"])
        data["Fechamento"].append(d.get("previsao_fechamento"))
        data["Ativação"].append(d.get("ativacao"))
        data["Potencial"].append(int(d["potencial"] or 0))
        data["TOTAL 6M"].append(int(d["total_linha"]))
        for m in meses:
            data[mes_label(m)].append(int(d["volumes"].get(m, 0)))
    df = pd.DataFrame(data)
    for m in meses:
        df[mes_label(m)] = df[mes_label(m)].astype(int)
    df["Potencial"] = df["Potencial"].astype(int)
    df["TOTAL 6M"] = df["TOTAL 6M"].astype(int)
    df["Fechamento"] = pd.to_datetime(df["Fechamento"], errors="coerce").dt.date
    df["Ativação"] = pd.to_datetime(df["Ativação"], errors="coerce").dt.date
    return df


def _df_negociacao_15(sel, meses):
    """DataFrame da aba "Negociação Potencial atualizado".

    Igual ao _df_negociacao, mas com a coluna "15% potencial" posicionada
    entre "Potencial" e "TOTAL 6M". Os meses e TOTAL 6M refletem o forecast
    sobre 15% (d["volumes"] / d["total_linha"] já são 15%-based nesta variante).
    "Potencial" mostra o valor ORIGINAL (preservado em d["potencial"]).
    """
    data = {
        "Nome do negócio": [], "Pipeline": [], "Etapa": [], "Proprietário": [],
        "Fechamento": [], "Ativação": [], "Potencial": [], "15% potencial": [],
        "TOTAL 6M": [],
    }
    for m in meses:
        data[mes_label(m)] = []
    for d in sel:
        data["Nome do negócio"].append(d["dealname"])
        data["Pipeline"].append(d["pipeline_label"])
        data["Etapa"].append(_step_label(d))
        data["Proprietário"].append(d["owner_name"])
        data["Fechamento"].append(d.get("previsao_fechamento"))
        data["Ativação"].append(d.get("ativacao"))
        data["Potencial"].append(int(d["potencial"] or 0))
        data["15% potencial"].append(int(d["potencial_15"] or 0))
        data["TOTAL 6M"].append(int(d["total_linha"]))
        for m in meses:
            data[mes_label(m)].append(int(d["volumes"].get(m, 0)))
    df = pd.DataFrame(data)
    for m in meses:
        df[mes_label(m)] = df[mes_label(m)].astype(int)
    for c in ("Potencial", "15% potencial", "TOTAL 6M"):
        df[c] = df[c].astype(int)
    df["Fechamento"] = pd.to_datetime(df["Fechamento"], errors="coerce").dt.date
    df["Ativação"] = pd.to_datetime(df["Ativação"], errors="coerce").dt.date
    return df


def _df_ativacao(sel, meses):
    data = {
        "Nome do negócio": [], "Pipeline": [], "Proprietário": [],
        "Entrada na Ativação": [], "Dias em ativação": [],
        "Potencial mês (total)": [], "% rampa mês atual": [],
        "Corridas esperadas mês atual": [], "TOTAL 6M": [],
    }
    for m in meses:
        data[mes_label(m)] = []
    for d in sel:
        data["Nome do negócio"].append(d["dealname"])
        data["Pipeline"].append(d["pipeline_label"])
        data["Proprietário"].append(d["owner_name"])
        data["Entrada na Ativação"].append(d.get("entrada_ativacao"))
        data["Dias em ativação"].append(int(d.get("dias_ativacao") or 0))
        data["Potencial mês (total)"].append(int(d["potencial"] or 0))
        data["% rampa mês atual"].append(_pct_rampa_atual(d, meses))
        data["Corridas esperadas mês atual"].append(int(d["volumes"].get(meses[0], 0)))
        data["TOTAL 6M"].append(int(d["total_linha"]))
        for m in meses:
            data[mes_label(m)].append(int(d["volumes"].get(m, 0)))
    df = pd.DataFrame(data)
    for m in meses:
        df[mes_label(m)] = df[mes_label(m)].astype(int)
    for c in ("Dias em ativação", "Potencial mês (total)", "% rampa mês atual",
              "Corridas esperadas mês atual", "TOTAL 6M"):
        df[c] = df[c].astype(int)
    df["Entrada na Ativação"] = pd.to_datetime(df["Entrada na Ativação"], errors="coerce").dt.date
    return df


def _df_ativacao_15(sel, meses):
    """DataFrame da aba "Ativação Potencial Atualizado".

    Igual ao _df_ativacao, mas com a coluna "15% potencial" posicionada
    entre "Potencial mês (total)" e "% rampa mês atual". "% rampa mês atual"
    é inalterada (fração da curva); meses, "Corridas esperadas mês atual" e
    TOTAL 6M refletem o forecast sobre 15%. "Potencial mês (total)" mostra
    o valor ORIGINAL (preservado em d["potencial"]).
    """
    data = {
        "Nome do negócio": [], "Pipeline": [], "Proprietário": [],
        "Entrada na Ativação": [], "Dias em ativação": [],
        "Potencial mês (total)": [], "15% potencial": [], "% rampa mês atual": [],
        "Corridas esperadas mês atual": [], "TOTAL 6M": [],
    }
    for m in meses:
        data[mes_label(m)] = []
    for d in sel:
        data["Nome do negócio"].append(d["dealname"])
        data["Pipeline"].append(d["pipeline_label"])
        data["Proprietário"].append(d["owner_name"])
        data["Entrada na Ativação"].append(d.get("entrada_ativacao"))
        data["Dias em ativação"].append(int(d.get("dias_ativacao") or 0))
        data["Potencial mês (total)"].append(int(d["potencial"] or 0))
        data["15% potencial"].append(int(d["potencial_15"] or 0))
        data["% rampa mês atual"].append(_pct_rampa_atual(d, meses))
        data["Corridas esperadas mês atual"].append(int(d["volumes"].get(meses[0], 0)))
        data["TOTAL 6M"].append(int(d["total_linha"]))
        for m in meses:
            data[mes_label(m)].append(int(d["volumes"].get(m, 0)))
    df = pd.DataFrame(data)
    for m in meses:
        df[mes_label(m)] = df[mes_label(m)].astype(int)
    for c in ("Dias em ativação", "Potencial mês (total)", "15% potencial",
              "% rampa mês atual", "Corridas esperadas mês atual", "TOTAL 6M"):
        df[c] = df[c].astype(int)
    df["Entrada na Ativação"] = pd.to_datetime(df["Entrada na Ativação"], errors="coerce").dt.date
    return df


def _pct_rampa_atual(d, meses):
    """% da rampa no mês atual (meses[0]) p/ coluna da aba Ativação."""
    det = d.get("detalhes", {}).get(meses[0])
    if not det or det.get("frac") is None:
        return 0
    return int(round(det["frac"] * 100))


def _step_label(d):
    return f"{d['step']}. " + (d["stage_label"].split(". ", 1)[-1]
                              if ". " in d["stage_label"] else d["stage_label"])


# ---- linha TOTAL fixa (separada, não ordenável) -------------------------
def _linha_total(df, meses, label="TOTAL"):
    """Exibe uma linha de totais alinhada às colunas, acima e abaixo da tabela.
    Não participa da ordenação (spec B)."""
    tot = {"Nome do negócio": label}
    cols_num = ["Potencial", "15% potencial", "Potencial mês (total)", "TOTAL 6M",
                "Corridas esperadas mês atual", "Dias em ativação", "% rampa mês atual"]
    for c in df.columns:
        if c in cols_num:
            tot[c] = int(df[c].sum()) if c in df.columns else 0
    for m in meses:
        lab = mes_label(m)
        if lab in df.columns:
            tot[lab] = int(df[lab].sum())
    dft = pd.DataFrame([tot])
    # formatar exibição: inteiros BR
    cc = {}
    for c in dft.columns:
        if c in cols_num or mes_col_is_month(c, meses):
            cc[c] = st.column_config.NumberColumn(c, format="%d")
    st.dataframe(dft, column_config=cc, use_container_width=True,
                 hide_index=True, height=68)


def mes_col_is_month(col, meses):
    return col in [mes_label(m) for m in meses]


# ---- zebra striping (pandas.Styler pintado no canvas do st.dataframe) -----
# st.dataframe em 1.61.1 renderiza num <canvas> (Glide Data Grid), então CSS
# em td/tr não pega o corpo. Passamos um pandas.Styler: o Streamlit extrai os
# estilos de célula (_marshall_styles -> drawCell) e pinta no canvas, mantendo
# ordenação por clique, column_config (datas/números BR) e heatmap futuro.
# docstring arrow.py L651: column_config tem precedência sobre Styler p/ texto.
def _zebra_styler(df, dark):
    """Reveste df com fundo intercalado nas linhas pares (0-indexed: 1ª, 3ª, ...).
    Devolve um pandas.Styler; células ímpares ficam vazias (cor da superfície)."""
    if df.empty:
        return df.style  # styler vazio: sem efeito, só mantém o shape
    bg = theme.ZEBRA_BG["dark" if dark else "light"]
    def _paint(_df):
        # Estilo por linha (par -> bg, ímpar -> vazio) repetido p/ todas as cols.
        per_row = np.where(np.arange(len(_df)) % 2 == 0,
                           f"background-color: {bg}", "")
        css = np.broadcast_to(per_row[:, None], _df.shape)
        return pd.DataFrame(css, index=_df.index, columns=_df.columns)
    return df.style.apply(_paint, axis=None)


# ---- tabela principal (st.dataframe nativo + heatmap + ordenação clique) -
def _tabela_principal(df, meses, dark, agrupar, aba):
    if df.empty:
        st.info("Nenhum deal com os filtros atuais.")
        return
    # column_config: datas como DateColumn, números como NumberColumn,
    # meses com BarColumn (heatmap de um único tom, intensidade proporcional).
    cc = {}
    if aba == "negociacao":
        cc["Fechamento"] = st.column_config.DateColumn("Fechamento", format="DD/MM/YYYY")
        cc["Ativação"] = st.column_config.DateColumn("Ativação", format="DD/MM/YYYY")
        cc["Potencial"] = st.column_config.NumberColumn("Potencial", format="%d")
        cc["TOTAL 6M"] = st.column_config.NumberColumn("TOTAL 6M", format="%d")
    elif aba == "negociacao_15":
        cc["Fechamento"] = st.column_config.DateColumn("Fechamento", format="DD/MM/YYYY")
        cc["Ativação"] = st.column_config.DateColumn("Ativação", format="DD/MM/YYYY")
        cc["Potencial"] = st.column_config.NumberColumn("Potencial", format="%d")
        cc["15% potencial"] = st.column_config.NumberColumn(
            "15% potencial", format="%d",
            help="15% do Potencial = round(potencial × 0,15). "
                 "O forecast desta aba (TOTAL 6M e meses) é baseado neste valor.")
        cc["TOTAL 6M"] = st.column_config.NumberColumn("TOTAL 6M", format="%d")
    elif aba == "ativacao":
        cc["Entrada na Ativação"] = st.column_config.DateColumn("Entrada na Ativação", format="DD/MM/YYYY")
        cc["Dias em ativação"] = st.column_config.NumberColumn("Dias em ativação", format="%d")
        cc["Potencial mês (total)"] = st.column_config.NumberColumn("Potencial mês (total)", format="%d")
        cc["% rampa mês atual"] = st.column_config.NumberColumn("% rampa mês atual", format="%d")
        cc["Corridas esperadas mês atual"] = st.column_config.NumberColumn("Corridas esperadas mês atual", format="%d")
        cc["TOTAL 6M"] = st.column_config.NumberColumn("TOTAL 6M", format="%d")
    elif aba == "ativacao_15":
        cc["Entrada na Ativação"] = st.column_config.DateColumn("Entrada na Ativação", format="DD/MM/YYYY")
        cc["Dias em ativação"] = st.column_config.NumberColumn("Dias em ativação", format="%d")
        cc["Potencial mês (total)"] = st.column_config.NumberColumn("Potencial mês (total)", format="%d")
        cc["15% potencial"] = st.column_config.NumberColumn(
            "15% potencial", format="%d",
            help="15% do Potencial mês (total) = round(potencial × 0,15). "
                 "O forecast desta aba (TOTAL 6M, meses e Corridas esperadas mês "
                 "atual) é baseado neste valor. % rampa mês atual é inalterada "
                 "(fração da curva, independe do potencial).")
        cc["% rampa mês atual"] = st.column_config.NumberColumn("% rampa mês atual", format="%d")
        cc["Corridas esperadas mês atual"] = st.column_config.NumberColumn("Corridas esperadas mês atual", format="%d")
        cc["TOTAL 6M"] = st.column_config.NumberColumn("TOTAL 6M", format="%d")
    else:
        cc["Entrada na Ativação"] = st.column_config.DateColumn("Entrada na Ativação", format="DD/MM/YYYY")
        cc["Dias em ativação"] = st.column_config.NumberColumn("Dias em ativação", format="%d")
        cc["Potencial mês (total)"] = st.column_config.NumberColumn("Potencial mês (total)", format="%d")
        cc["% rampa mês atual"] = st.column_config.NumberColumn("% rampa mês atual", format="%d")
        cc["Corridas esperadas mês atual"] = st.column_config.NumberColumn("Corridas esperadas mês atual", format="%d")
        cc["TOTAL 6M"] = st.column_config.NumberColumn("TOTAL 6M", format="%d")
    # meses como NumberColumn (inteiro visível + ordenável por clique, spec B).
    # Nota: BarColumn não existe no Streamlit 1.61.1 ( só a partir de versões
    # posteriores); ProgressColumn mostrar só a fração, não o valor bruto. A
    # spec B (valores numéricos p/ ordenação) é hard e prevalece sobre o
    # heatmap cosmético da spec C — por isso NumberColumn puro. O heatmap de
    # um único tom pode ser readicionado via CSS quando subir p/ uma versão
    # com BarColumn, sem mexer nos dados.
    for m in meses:
        lab = mes_label(m)
        if lab in df.columns:
            cc[lab] = st.column_config.NumberColumn(lab, format="%d",
                help="Volume previsto de corridas neste mês (clique p/ ordenar).")
    # Pipeline como coluna própria (chip de cor viria via CSS; spec C).
    st.dataframe(_zebra_styler(df, dark), column_config=cc,
                 use_container_width=True, hide_index=True, on_select="ignore")


# ---- expander de incompletos --------------------------------------------
def _incompletos_expander(incompletos, aba, dark):
    if not incompletos:
        return
    with st.expander(f"⚠️ Deals com dados incompletos ({len(incompletos)}) — fora dos totais"):
        rows = [{
            "Nome do negócio": d["dealname"], "Pipeline": d["pipeline_label"],
            "Etapa": _step_label(d) if aba == "negociacao" else "7. Ativação",
            "Proprietário": d["owner_name"],
            "Fechamento": fmt_data(d.get("previsao_fechamento") if aba == "negociacao"
                                   else d.get("closedate")),
            "Potencial": fmt_int(d["potencial"]),
            "Motivo": d.get("motivo_incompleto", "–"),
        } for d in incompletos]
        st.dataframe(_zebra_styler(pd.DataFrame(rows), dark),
                     use_container_width=True, hide_index=True)


# ---- gráfico empilhado Consolidado (Negociação vs Ativação) --------------
def _stacked_bar_consolidado(neg_sel, ativ_sel, meses):
    labels = [mes_label(m) for m in meses]
    vn = [sum(d["volumes"].get(m, 0) for d in neg_sel) for m in meses]
    va = [sum(d["volumes"].get(m, 0) for d in ativ_sel) for m in meses]
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Negociação", x=labels, y=vn,
                         marker_color=theme.PIPELINE_COLORS_LIGHT["B2B Outbound"],
                         hovertemplate="%{x}<br>Negociação: %{y:,.0f}<extra></extra>"))
    fig.add_trace(go.Bar(name="Ativação", x=labels, y=va,
                         marker_color=theme.PIPELINE_COLORS_LIGHT["B2B CSM Acquisition"],
                         hovertemplate="%{x}<br>Ativação: %{y:,.0f}<extra></extra>"))
    fig.update_layout(
        barmode="stack", height=300, margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        font=dict(size=11), plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(gridcolor="rgba(0,0,0,0.08)", tickformat=",.0f"),
        xaxis=dict(showgrid=False),
    )
    return fig


# ---- CSS (visual limpo, spec C) -----------------------------------------
def _CSS():
    return """
    <style>
    /* dataframes compactos, sem bordas pesadas */
    .stDataFrame { font-variant-numeric: tabular-nums; }
    .stDataFrame td, .stDataFrame th { font-size: 12px; }
    /* legenda de pipeline (chips discretos) */
    .fc-legend span { font-size: 11px; margin-right: 14px; }
    .fc-dot { display:inline-block; width:10px; height:10px; border-radius:50%;
        vertical-align:middle; margin-right:4px; }
    </style>
    """


if __name__ == "__main__":
    main()
