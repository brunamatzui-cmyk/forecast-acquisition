# -*- coding: utf-8 -*-
"""Configuração do Dashboard de Forecast de Aquisição.

Escopo: SOMENTE clientes que ainda NÃO assinaram contrato — deals nas
etapas 4 (Solução), 5 (Negociação) e 6 (Fechamento) dos pipelines B2B
Outbound, B2B Website Table e B2B CSM Acquisition. Clientes que já
assinaram (etapa 7 Ativação em diante) são tratados em outro escopo.

IDs descobertos dinamicamente via discover_schema.py em 2026-10-01 (não
assumidos — confirmados pelo label exato no HubSpot). Se um pipeline for
recriado/etapa renomeada, rodar discover_schema.py de novo.

Token: variável de ambiente HUBSPOT_TOKEN (Private App), mesma convenção
do ../dashboard/activation/config.py — nunca hardcoded (o token está
exposto nos extract_*.py da pasta pai do funnel automation, mas este
dashboard segue o padrão migrated de 2026-09-10: env/secret).
"""
import os

try:
    import streamlit as st
except ImportError:
    st = None


def _load_hubspot_token():
    """Token: secret do Streamlit > env HUBSPOT_TOKEN. Diagnóstico claro se faltar."""
    diag = []
    if st is not None:
        try:
            secret = st.secrets.get("HUBSPOT_TOKEN")
            if secret:
                return str(secret)
            try:
                keys = list(st.secrets.keys())
            except Exception:
                keys = []
            diag.append(
                f"secret 'HUBSPOT_TOKEN' ausente ou vazio (keys disponíveis: "
                f"{keys or 'nenhum'})"
            )
        except Exception as e:
            diag.append(
                f"st.secrets ilegível ({type(e).__name__}) — provável erro de "
                f"sintaxe TOML no Secret Manager: {e}"
            )
    else:
        diag.append("Streamlit não importado")
    env_token = os.environ.get("HUBSPOT_TOKEN")
    if env_token:
        return env_token
    diag.append("env var HUBSPOT_TOKEN não definida")
    raise RuntimeError(
        "HUBSPOT_TOKEN não encontrado. Diagnóstico: " + " | ".join(diag) + ". "
        "No Streamlit Cloud: Settings → Secrets, cole exatamente:\n"
        'HUBSPOT_TOKEN = "pat-na1-seu-token-aqui"'
    )


BASE = "https://api.hubapi.com"
PAGE_SIZE = 100  # Search API: máx 100 por página

# Pipelines alvo (id -> label amigável). Descobertos pelo label exato.
PIPELINES = {
    "890800903": "B2B Outbound",
    "917378965": "B2B Website Table",
    "927024659": "B2B CSM Acquisition",
}

# Stage IDs das etapas 4/5/6 por pipeline (descobertos pelo label).
# (stage_id, step_number, stage_label)
STAGES = {
    "890800903": [
        ("1342982404", 4, "4. Solução"),
        ("1342982407", 5, "5. Negociação"),
        ("1342981413", 6, "6. Fechamento (Contrato)"),
    ],
    "917378965": [
        ("1399082600", 4, "4. Solução (interno)"),
        ("1399082601", 5, "5. Negociação (externo)"),
        ("1399082602", 6, "6. Fechamento (Contrato)"),
    ],
    "927024659": [
        ("1420435112", 4, "4. Solução (interno)"),
        ("1420435113", 5, "5. Negociação (externo)"),
        ("1420435114", 6, "6. Fechamento (Contrato)"),
    ],
}

# Stage da etapa 7 "Ativação" por pipeline (spec D.1 — aba Ativação).
# Descoberto em 2026-10-15 pelo label exato (probe_ativacao.py).
# (stage_id, step_number, stage_label)
STAGES_ATIVACAO = {
    "890800903": ("1342981415", 7, "7. Ativação"),
    "917378965": ("1399082603", 7, "7. Ativação"),
    "927024659": ("1420435115", 7, "7. Ativação"),
}

# Todos os stage_ids alvo: 4/5/6 (Negociação) + 7 Ativação. A aba Ativação
# entra na MESMA consulta da Search API (filtro IN com todos os stages),
# sem consulta extra por pipeline — spec "Desempenho".
ALL_STAGE_IDS = ([s[0] for stages in STAGES.values() for s in stages]
                 + [s[0] for s in STAGES_ATIVACAO.values()])
ALL_ATIVACAO_STAGE_IDS = [s[0] for s in STAGES_ATIVACAO.values()]

# Mapeamento stage_id -> (step, label) para resolver o que vier no deal.
# Inclui 4/5/6 (Negociação) e 7 (Ativação).
STAGE_BY_ID = {s[0]: (s[1], s[2]) for stages in STAGES.values() for s in stages}
STAGE_BY_ID.update({s[0]: (s[1], s[2]) for s in STAGES_ATIVACAO.values()})

# Propriedade de potencial confirmada por probe_potencial.py em 2026-10-01:
# share_vs_potencial_total (label "Potencial Mês (Total)") é número absoluto
# de corridas (não share/razão), é o campo mais populado nos deals, e seu
# valor é sempre >= potencial_mes_99 (faz sentido: total >= mês específico).
# ATENÇÃO: vem como string e pode ter separador de milhar BR ("16.000"=16000).
PROP_POTENCIAL = "share_vs_potencial_total"
PROP_POTENCIAL_LABEL = "Potencial Mês (Total)"

# Previsão de fechamento (NÃO usar closedate — esse é "Close Date", a data
# real quando o deal fecha, que fica no passado/errada pra deals abertos).
# previsao_de_fechamento (label "Previsão de Fechamento", tipo date) é a
# previsão real — confirmado por probe_previsao.py em 2026-10-05: vem
# populada onde closedate vem None, e traz datas futuras coerentes.
PROP_PREVISAO = "previsao_de_fechamento"
PROP_PREVISAO_LABEL = "Previsão de Fechamento"

# Propriedades trazidas por deal na Search API.
# hs_lastmodifieddate = atualização incremental (spec 4.4): nas rodadas
# seguintes, buscar só deals modificados desde a última atualização.
# closedate = data real de fechamento; usado como proxy da "data de entrada
# na Ativação" (spec D.1). hs_date_entered_<stage_id> NÃO é retornável pela
# CRM API v3 — ver probe_date_entered.py e a memória
# forecast-ativacao-stage-discovery.
DEAL_PROPERTIES = [
    "dealname", "dealstage", "pipeline", "hubspot_owner_id",
    PROP_PREVISAO, PROP_POTENCIAL, "closedate", "hs_lastmodifieddate",
]
PROP_LASTMOD = "hs_lastmodifieddate"
PROP_CLOSEDATE = "closedate"   # data real de fechamento (proxy entrada Ativação)

# ---- Regras de cálculo (spec) --------------------------------------------
DIAS_UTEIS_POS_FECHAMENTO = 5  # ativação = fechamento + 5 dias úteis
MESES_JANELA = 6               # 6 meses a partir do mês atual (inclusive)

# Curva de rampagem (fração do potencial total por mês da rampa).
# Mês 1 é sempre 25% (com proporcionalidade por dia no mês calendário).
# - potencial < 20.000:  [25, 50, 100] (atinge 100% no mês 3)
# - potencial >= 20.000: [25, 50, 75, 100] (atinge 100% no mês 4)
CURVA_RAMPAGEM = {
    "low":  [0.25, 0.50, 1.00],            # potencial < 20.000
    "high": [0.25, 0.50, 0.75, 1.00],      # potencial >= 20.000
}
LIMITE_POTENCIAL_ALTO = 20000
