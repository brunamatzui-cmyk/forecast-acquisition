# -*- coding: utf-8 -*-
"""Dashboard de Forecast de Aquisição — clientes que AINDA NÃO assinaram
contrato (etapas 4/5/6 dos pipelines B2B Outbound, Website Table, CSM
Acquisition).

Tabela com forecast de volume de corridas por mês (6 meses a partir do mês
atual), com rampagem (M1 proporcional por dia) e linha de TOTAL.

Rodar local:  streamlit run app.py
Token:        env HUBSPOT_TOKEN (Private App) ou secret no Streamlit Cloud.
"""
import datetime as dt

import pandas as pd
import streamlit as st

import config
import fetch_hubspot as fh
import calc_forecast as cf

# ----- formatação BR ------------------------------------------------------
def fmt_int(n):
    """Inteiro no padrão BR (ponto como separador de milhar). None -> '–'."""
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


# ----- carregamento (cache por sessão) -----------------------------------
@st.cache_data(ttl=900, show_spinner="Buscando deals no HubSpot (etapas 4/5/6 dos 3 pipelines)...")
def carregar():
    deals, owners, fetched_at = fh.fetch_deals(log=lambda *a, **k: None)
    hoje = dt.date.today()
    completos, incompletos, meses = cf.calcular_todos(deals, hoje=hoje)
    return completos, incompletos, meses, fetched_at, hoje


def main():
    st.set_page_config(
        page_title="Forecast de Aquisição",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("Forecast de Aquisição — Clientes em Negociação")
    st.caption(
        "Deals nas etapas **4. Solução**, **5. Negociação** e "
        "**6. Fechamento** dos pipelines B2B Outbound, Website Table e CSM "
        "Acquisition. Volume de corridas previsto por mês (rampagem: M1 "
        "proporcional por dia, 25%→50%→100% ou 25%→50%→75%→100%)."
    )

    completos, incompletos, meses, fetched_at, hoje = carregar()

    # ---- cabeçalho de status --------------------------------------------
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Deals no forecast", len(completos))
    c2.metric("Deals com dados incompletos", len(incompletos))
    c3.metric("Janela", f"{meses[0].strftime('%b/%y')} – {meses[-1].strftime('%b/%y')}")
    c4.metric("Última atualização", fetched_at.strftime("%d/%m/%Y %H:%M"))

    # ---- filtros ---------------------------------------------------------
    st.sidebar.header("Filtros")
    todos_owners = sorted({d["owner_name"] for d in completos})
    todos_pipes = sorted({d["pipeline_label"] for d in completos})
    todos_steps = sorted({d["step"] for d in completos if d["step"]})

    f_owner = st.sidebar.multiselect("Proprietário", todos_owners)
    f_pipe = st.sidebar.multiselect("Pipeline", todos_pipes)
    f_step = st.sidebar.multiselect("Etapa", [f"Etapa {s}" for s in todos_steps])

    if st.sidebar.button("🔄 Atualizar dados agora"):
        st.cache_data.clear()
        st.rerun()

    # aplica filtros
    sel = completos
    if f_owner:
        sel = [d for d in sel if d["owner_name"] in f_owner]
    if f_pipe:
        sel = [d for d in sel if d["pipeline_label"] in f_pipe]
    if f_step:
        nums = [int(s.split()[-1]) for s in f_step]
        sel = [d for d in sel if d["step"] in nums]

    # ---- monta DataFrame -------------------------------------------------
    col_fixas = ["Nome do negócio", "Pipeline", "Etapa", "Proprietário",
                 "Previsão de fechamento", "Data de ativação",
                 "Potencial mês (total)"]
    mes_labels = [m.strftime("%b/%y").capitalize() for m in meses]
    colunas = col_fixas + mes_labels + ["Total (6 meses)"]

    def step_label(d):
        return f"{d['step']}. " + (d["stage_label"].split(". ", 1)[-1]
                                   if ". " in d["stage_label"] else d["stage_label"])

    # destaque visual sutil por etapa: círculo colorido crescente (mais quente
    # quanto mais avançado no funil — 4 verde, 5 amarelo, 6 laranja).
    STEP_BADGE = {4: "🟢", 5: "🟡", 6: "🟠"}

    rows = []
    for d in sel:
        row = {
            "Nome do negócio": d["dealname"],
            "Pipeline": d["pipeline_label"],
            "Etapa": STEP_BADGE.get(d["step"], "") + " " + step_label(d),
            "Proprietário": d["owner_name"] + (" 🔴" if d["atrasado"] else ""),
            "Previsão de fechamento": fmt_data(d["closedate"]),
            "Data de ativação": fmt_data(d["ativacao"]),
            "Potencial mês (total)": fmt_int(d["potencial"]),
        }
        for m, lab in zip(meses, mes_labels):
            row[lab] = fmt_int(d["volumes"].get(m, 0))
        row["Total (6 meses)"] = fmt_int(d["total_linha"])
        rows.append(row)

    df = pd.DataFrame(rows, columns=colunas)

    # ---- linha de TOTAL (recalculada com os filtros) --------------------
    total_row = {c: "" for c in colunas}
    total_row["Nome do negócio"] = "TOTAL"
    for m, lab in zip(meses, mes_labels):
        total_row[lab] = fmt_int(sum(d["volumes"].get(m, 0) for d in sel))
    total_row["Total (6 meses)"] = fmt_int(sum(d["total_linha"] for d in sel))
    df_total = pd.DataFrame([total_row], columns=colunas)

    # ---- destaque visual por etapa --------------------------------------
    st.subheader("Forecast por mês")
    st.write(f"Mostrando **{len(sel)}** deals (de {len(completos)} completos). "
             f"Os totais abaixo refletem os filtros aplicados.")

    # tabela principal com ordenação
    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config={
            "Etapa": st.column_config.TextColumn(help="Etapa do funil (4/5/6)"),
        },
    )

    # legenda de etapa + atraso
    st.markdown(
        "**Etapa:** 🟢 `4. Solução` · 🟡 `5. Negociação` · 🟠 `6. Fechamento`  "
        "&nbsp;&nbsp; 🔴 = fechamento atrasado (data no passado; ativação "
        "calculada a partir de hoje)."
    )

    # ---- linha de total em destaque -------------------------------------
    st.markdown("**Total (recalculado com os filtros)**")
    st.dataframe(df_total, width="stretch", hide_index=True)

    # ---- seção de incompletos -------------------------------------------
    if incompletos:
        with st.expander(f"⚠️ Deals com dados incompletos ({len(incompletos)}) — não incluídos nos totais"):
            inc_rows = []
            for d in incompletos:
                inc_rows.append({
                    "Nome do negócio": d["dealname"],
                    "Pipeline": d["pipeline_label"],
                    "Etapa": step_label(d),
                    "Proprietário": d["owner_name"],
                    "Previsão de fechamento": fmt_data(d["closedate"]),
                    "Potencial mês (total)": fmt_int(d["potencial"]),
                    "Motivo": d.get("motivo_incompleto", "–"),
                })
            st.dataframe(pd.DataFrame(inc_rows), width="stretch", hide_index=True)
            st.caption(
                "Estes deals estão nas etapas 4/5/6 mas faltam previsão de "
                "fechamento e/ou potencial mês — não há como calcular a "
                "rampagem. Preencha no HubSpot para que entrem no forecast."
            )

    st.caption(
        f"Fonte: HubSpot (pipelines B2B Outbound, Website Table, CSM "
        f"Acquisition; etapas 4/5/6). Propriedade de potencial: "
        f"`{config.PROP_POTENCIAL}` ({config.PROP_POTENCIAL_LABEL}). "
        f"Ativação = fechamento + 5 dias úteis (ignora sáb/dom e feriados "
        f"nacionais BR). Probabilidade = 100% (não pondera por etapa). "
        f"Dados em cache por 15 min — use 🔄 para forçar atualização."
    )


if __name__ == "__main__":
    main()
