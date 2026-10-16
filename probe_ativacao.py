# -*- coding: utf-8 -*-
"""Probe da aba Ativação (spec D.1) — NÃO assume, confirma:

1. Para cada pipeline do config.py: lista TODOS os stages, confere que os
   IDs 4/5/6 do config realmente pertencem a ele, e acha o stage "Ativação"
   (label contém "ativa").
2. Para cada stage de Ativação encontrado: busca até 5 deals reais pedindo a
   prop hs_date_entered_<stage_id> + potencial + dealname + owner, e relata
   se a prop de entrada volta populada (properties de sistema não aparecem
   no schema, mas são queryáveis na Search API — é isso que confirmamos).

Uso: PYTHONUTF8=1 HUBSPOT_TOKEN=... python probe_ativacao.py
"""
import datetime as dt
import os
import time

import requests

import config

BASE = "https://api.hubapi.com"
TOKEN = os.environ["HUBSPOT_TOKEN"]
HEADERS = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}


def hs_get(path, tries=5):
    url = BASE + path
    for a in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            if r.status_code == 404:
                return None
            if r.status_code == 429 and a < tries - 1:
                time.sleep(int(r.headers.get("Retry-After", "10")) + 1); continue
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.ChunkedEncodingError) as e:
            if a < tries - 1:
                time.sleep(1.5 * (a + 1)); continue
            raise


def hs_search(body, tries=5):
    for a in range(tries):
        r = requests.post(f"{BASE}/crm/v3/objects/deals/search",
                          headers=HEADERS, json=body, timeout=60)
        if r.status_code == 429 and a < tries - 1:
            time.sleep(int(r.headers.get("Retry-After", "10")) + 1); continue
        r.raise_for_status()
        return r.json()


print("=" * 78)
print("1) STAGES de cada pipeline do config — conferir 4/5/6 + achar Ativação")
print("=" * 78)
ativacao = {}  # pid -> (stage_id, label)
for pid, plabel in config.PIPELINES.items():
    sr = hs_get(f"/crm/v3/pipelines/deals/{pid}/stages?archived=false")
    if sr is None:
        print(f"\n  !! Pipeline {plabel!r} ({pid}): 404 — ID inválido/archived.")
        continue
    print(f"\n  Pipeline config='{plabel}' ({pid}) — {len(sr.get('results', []))} stages:")
    atv = None
    for s in sr.get("results", []):
        slabel = s.get("label", "")
        sid = s.get("id")
        # conferir contra config.STAGES
        in_cfg = next((f"<-- config.{step}" for (csid, step, _)
                       in config.STAGES.get(pid, []) if csid == sid), "")
        atv_mark = ""
        if "ativa" in slabel.lower():
            atv = (sid, slabel); atv_mark = "  <-- ATIVAÇÃO"
        print(f"    order={s.get('displayOrder'):>2}  id={sid:>12}  label={slabel!r}{in_cfg}{atv_mark}")
    if atv is None:
        print(f"    !! 'Ativação' NÃO encontrada neste pipeline.")
    ativacao[pid] = atv

print("\n" + "=" * 78)
print("2) Deals reais no stage de Ativação — hs_date_entered_<id> populado?")
print("=" * 78)
for pid, plabel in config.PIPELINES.items():
    atv = ativacao.get(pid)
    if not atv:
        print(f"\n  {plabel}: sem stage de Ativação — pulando.")
        continue
    sid, slabel = atv
    prop_entered = f"hs_date_entered_{sid}"
    props = ["dealname", "hubspot_owner_id", config.PROP_POTENCIAL,
             config.PROP_PREVISAO, prop_entered]
    body = {
        "filterGroups": [{"filters": [
            {"value": pid, "propertyName": "pipeline", "operator": "EQ"},
            {"value": sid, "propertyName": "dealstage", "operator": "EQ"},
        ]}],
        "properties": props, "limit": 5,
    }
    res = hs_search(body)
    results = res.get("results", [])
    n_total = res.get("total", "?")
    print(f"\n  {plabel} | stage '{slabel}' ({sid}) | {len(results)} amostra(s) (total={n_total}):")
    print(f"    prop testada: {prop_entered}")
    if not results:
        print("    (nenhum deal nesta etapa)")
        continue
    pop = 0
    for d in results:
        p = d.get("properties", {})
        entered_raw = p.get(prop_entered)
        ent = "(vazio)" if not entered_raw else str(entered_raw)[:40]
        pot = p.get(config.PROP_POTENCIAL)
        nm = (p.get("dealname") or {}).get("value", p.get("dealname")) if isinstance(p.get("dealname"), dict) else p.get("dealname")
        if entered_raw:
            pop += 1
        print(f"    - {str(nm)[:32]!r:34s} potencial={str(pot)[:10]:10s} entered={ent}")
    print(f"    -> {pop}/{len(results)} deals com {prop_entered} populada.")

print("\n" + "=" * 78)
print("RESUMO Ativação por pipeline:")
print("=" * 78)
for pid, plabel in config.PIPELINES.items():
    atv = ativacao.get(pid)
    if atv:
        print(f"  {plabel:24s} pid={pid}  stage_id={atv[0]}  label={atv[1]!r}")
    else:
        print(f"  {plabel:24s} pid={pid}  SEM stage de Ativação !!")
