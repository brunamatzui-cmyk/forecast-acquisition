# -*- coding: utf-8 -*-
"""Probe focado: por que hs_date_entered_<ativacao_id> vem vazio na Search API?

Testa, para um deal real no stage 7. Ativação do Outbound:
  A) Read API do objeto (GET /deals/{id}) com properties=* — vê TODAS as props
     de sistema disponíveis, inclusive hs_date_entered_* de todos os stages.
  B) Compara com a lista de TODAS as props hs_date_entered_* que existem para
     esse deal (nem todas estão no schema, mas a Read API as devolve).
  C) Confere alternativas de data de entrada: hs_lastmodifieddate, closedate,
     e a data de criação do deal (createdate).

Conclusão esperada: qual prop usar como "data de entrada na Ativação".

Uso: PYTHONUTF8=1 HUBSPOT_TOKEN=... python probe_date_entered.py
"""
import os
import time

import requests

import config

BASE = "https://api.hubapi.com"
TOKEN = os.environ["HUBSPOT_TOKEN"]
HEADERS = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}


def hs_search(body, tries=5):
    for a in range(tries):
        r = requests.post(f"{BASE}/crm/v3/objects/deals/search",
                          headers=HEADERS, json=body, timeout=60)
        if r.status_code == 429 and a < tries - 1:
            time.sleep(int(r.headers.get("Retry-After", "10")) + 1); continue
        r.raise_for_status()
        return r.json()


def hs_get(path, tries=5):
    for a in range(tries):
        r = requests.get(BASE + path, headers=HEADERS, timeout=60)
        if r.status_code == 429 and a < tries - 1:
            time.sleep(int(r.headers.get("Retry-After", "10")) + 1); continue
        r.raise_for_status()
        return r.json()


# Outbound, stage 7. Ativação
PID = "890800903"
SID_ATIV = "1342981415"
SID_6 = "1342981413"   # 6. Fechamento — p/ comparar (deals vieram daqui)

# 1. achar 1 deal na Ativação
body = {
    "filterGroups": [{"filters": [
        {"value": PID, "propertyName": "pipeline", "operator": "EQ"},
        {"value": SID_ATIV, "propertyName": "dealstage", "operator": "EQ"},
    ]}],
    "properties": ["dealname"], "limit": 1,
}
res = hs_search(body)
results = res.get("results", [])
if not results:
    print("Nenhum deal na Ativação do Outbound — abortar.")
    raise SystemExit
deal = results[0]
did = deal["id"]


def _val(v):
    if isinstance(v, dict):
        return v.get("value")
    return v


dn = _val(deal.get("properties", {}).get("dealname"))
print(f"Deal: id={did}  name={dn!r}")
print()

# 2. Read API com TODAS as propriedades
full = hs_get(
    f"/crm/v3/objects/deals/{did}?properties=*"
    f"&propertiesWithHistory=false&archived=false")
props = full.get("properties", {})

print("=" * 78)
print("A) TODAS as propriedades hs_date_entered_* deste deal (Read API properties=*)")
print("=" * 78)
entered = sorted(k for k in props if k.startswith("hs_date_entered_"))
if not entered:
    print("  (nenhuma prop hs_date_entered_* retornada)")
for k in entered:
    v = props[k]
    raw = v.get("value") if isinstance(v, dict) else v
    print(f"  {k:42s} = {raw!r}")

# mapear stage_id -> label conhecido
sid2label = {s[0]: s[2] for stages in config.STAGES.values() for s in stages}
sid2label[SID_ATIV] = "7. Ativação (Outbound)"
print()
print("  (decodificando: stage_id -> label)")
for k in entered:
    sid = k.replace("hs_date_entered_", "")
    print(f"    {sid} -> {sid2label.get(sid, '(desconhecido)')!r}")

print()
print("=" * 78)
print("B) A prop do stage de Ativação especificamente:")
print("=" * 78)
key = f"hs_date_entered_{SID_ATIV}"
v = props.get(key)
raw = v.get("value") if isinstance(v, dict) else v
if key in props:
    print(f"  {key} -> {raw!r}")
    if raw:
        import datetime as dt
        try:
            print(f"    como data: {dt.datetime.fromtimestamp(int(raw)/1000)}")
        except Exception as e:
            print(f"    (parse falhou: {e})")
else:
    print(f"  {key} NÃO está no retorno da Read API com properties=*.")

print()
print("=" * 78)
print("C) Alternativas de data (timestamps do deal):")
print("=" * 78)
for k in ("createdate", "hs_lastmodifieddate", "closedate",
          "hs_lastmodifieddate_v2", "hs_pipeline_stage",
          f"hs_date_entered_{SID_6}"):
    v = props.get(k)
    raw = v.get("value") if isinstance(v, dict) else v
    if raw:
        try:
            d = dt.datetime.fromtimestamp(int(raw) / 1000).strftime("%Y-%m-%d %H:%M")
        except Exception:
            d = str(raw)
        print(f"  {k:42s} = {d}")
    else:
        print(f"  {k:42s} = (vazio)")

print()
print("=" * 78)
print("D) Confirmar via Search API: pedir hs_date_entered_<ativ> num batch")
print("=" * 78)
body2 = {
    "filterGroups": [{"filters": [
        {"value": PID, "propertyName": "pipeline", "operator": "EQ"},
        {"value": SID_ATIV, "propertyName": "dealstage", "operator": "EQ"},
    ]}],
    "properties": ["dealname", f"hs_date_entered_{SID_ATIV}",
                   f"hs_date_entered_{SID_6}", "hs_lastmodifieddate",
                   "closedate", "createdate"],
    "limit": 3,
}
res2 = hs_search(body2)
for d in res2.get("results", []):
    p = d.get("properties", {})
    print(f"  deal {d['id']}:")
    for k in (f"hs_date_entered_{SID_ATIV}", f"hs_date_entered_{SID_6}",
              "hs_lastmodifieddate", "closedate", "createdate"):
        v = p.get(k)
        raw = v.get("value") if isinstance(v, dict) else v
        print(f"    {k:40s} = {raw!r}")
