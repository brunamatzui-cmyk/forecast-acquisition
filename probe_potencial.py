# -*- coding: utf-8 -*-
"""Probe: traz 10 deals reais dos stages 4/5/6 dos 3 pipelines e mostra os
valores de TODOS os candidatos a 'potencial', para confirmar qual é o
potencial absoluto (número de corridas) vs qual é share/razão.
"""
import os
import time
import requests

BASE = "https://api.hubapi.com"
TOKEN = os.environ["HUBSPOT_TOKEN"]
HEADERS = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}

PIPELINES = {
    "890800903": "B2B Outbound",
    "917378965": "B2B Website Table",
    "927024659": "B2B CSM Acquisition",
}
# stage ids 4/5/6 por pipeline
STAGES = {
    "890800903": ["1342982404", "1342982407", "1342981413"],
    "917378965": ["1399082600", "1399082601", "1399082602"],
    "927024659": ["1420435112", "1420435113", "1420435114"],
}
POT_COLS = [
    "share_vs_potencial_total",        # "Potencial Mês (Total)"
    "potencial_total_de_corridas_mensal",  # "Potencial Total"
    "potencial_mes_99",                # "Potencial Mês (99)"
    "potencial_trips_total",           # "Potencial mensal total (trips)"
    "potencial_trips_99",              # "Potencial mensal 99 (trips)"
    "corridas_potencial_99app",        # "Potencial Mês (Estimado)"
    "potencial_de_corridas_mes",       # "Potencial de corridas mês"
]
PROPS = ["dealname", "dealstage", "hubspot_owner_id", "closedate"] + POT_COLS


def search(pid, stage_ids, after=None):
    body = {
        "filterGroups": [{"filters": [
            {"value": pid, "propertyName": "pipeline", "operator": "EQ"},
            {"values": stage_ids, "propertyName": "dealstage", "operator": "IN"},
        ]}],
        "properties": PROPS, "limit": 10,
    }
    if after:
        body["after"] = after
    r = requests.post(f"{BASE}/crm/v3/objects/deals/search", headers=HEADERS, json=body, timeout=60)
    r.raise_for_status()
    return r.json()


for pid, plabel in PIPELINES.items():
    print("=" * 80)
    print(f"{plabel} ({pid})")
    print("=" * 80)
    page = search(pid, STAGES[pid])
    for d in page.get("results", []):
        p = d.get("properties", {})
        name = (p.get("dealname") or {}).get("value") if isinstance(p.get("dealname"), dict) else p.get("dealname")
        stage = p.get("dealstage")
        if isinstance(stage, dict): stage = stage.get("value")
        print(f"\n  {name!r}  stage={stage}")
        for c in POT_COLS:
            v = p.get(c)
            if isinstance(v, dict): v = v.get("value")
            print(f"    {c:38s} = {v!r}")
    time.sleep(0.3)
