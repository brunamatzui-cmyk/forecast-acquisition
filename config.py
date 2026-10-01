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
    """Token: secret do Streamlit > env HUBSPOT_TOKEN."""
    if st is not None:
        try:
            secret = st.secrets.get("HUBSPOT_TOKEN")
            if secret:
                return secret
        except Exception:
            pass
    env_token = os.environ.get("HUBSPOT_TOKEN")
    if env_token:
        return env_token
    raise RuntimeError(
        "HUBSPOT_TOKEN não encontrado. Defina a variável de ambiente "
        "HUBSPOT_TOKEN ou configure o secret HUBSPOT_TOKEN no Streamlit."
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

# Todos os stage_ids alvo (para o filtro IN da Search API).
ALL_STAGE_IDS = [s[0] for stages in STAGES.values() for s in stages]

# Mapeamento stage_id -> (step, label) para resolver o que vier no deal.
STAGE_BY_ID = {s[0]: (s[1], s[2]) for stages in STAGES.values() for s in stages}

# Propriedade de potencial confirmada por probe_potencial.py em 2026-10-01:
# share_vs_potencial_total (label "Potencial Mês (Total)") é número absoluto
# de corridas (não share/razão), é o campo mais populado nos deals, e seu
# valor é sempre >= potencial_mes_99 (faz sentido: total >= mês específico).
# ATENÇÃO: vem como string e pode ter separador de milhar BR ("16.000"=16000).
PROP_POTENCIAL = "share_vs_potencial_total"
PROP_POTENCIAL_LABEL = "Potencial Mês (Total)"

# Propriedades trazidas por deal na Search API.
DEAL_PROPERTIES = [
    "dealname", "dealstage", "pipeline", "hubspot_owner_id",
    "closedate", PROP_POTENCIAL,
]

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
