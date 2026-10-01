# -*- coding: utf-8 -*-
"""Descoberta de schema do HubSpot para o dash forecast acquisition.

NÃO assume IDs: busca pipelines pelo label, stages pelo label e a
propriedade de potencial pelo label. Roda uma vez para confirmar os IDs
reais antes de codar o fetch. Uso: PYTHONUTF8=1 python discover_schema.py
"""
import json
import os
import time

import requests

BASE = "https://api.hubapi.com"
TOKEN = os.environ["HUBSPOT_TOKEN"]
HEADERS = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}


def hs_get(path, tries=5):
    url = BASE + path
    for a in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            if r.status_code == 429 and a < tries - 1:
                time.sleep(int(r.headers.get("Retry-After", "10")) + 1); continue
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.ChunkedEncodingError, ValueError) as e:
            if a < tries - 1:
                time.sleep(1.5 * (a + 1)); continue
            raise


def want_pipeline(label):
    l = label.lower()
    return ("outbound" in l and "b2b" in l) or ("website" in l and "b2b" in l) or ("csm" in l and "acquisition" in l and "b2b" in l)


def stage_matches(label, key):
    l = label.lower()
    # labels tipo "4. Solução (Proposal)", "5. Negociação (externo)", "6. Fechamento (Contrato) (Closing)"
    if key == "4":
        return l.startswith("4") and ("solu" in l or "proposal" in l)
    if key == "5":
        return l.startswith("5") and ("negoc" in l)
    if key == "6":
        return l.startswith("6") and ("fechamento" in l or "closing" in l or "contrato" in l)
    return False


print("=" * 70)
print("1) PIPELINES de deals")
print("=" * 70)
res = hs_get("/crm/v3/pipelines/deals?archived=false")
found = {}
for p in res.get("results", []):
    label = p.get("label", "")
    hit = want_pipeline(label)
    mark = "  <-- USAR" if hit else ""
    print(f"  id={p['id']:>12}  label={label!r}{mark}")
    if hit:
        found[p["id"]] = label
print(f"\nPipelines alvo encontrados: {len(found)}")

print("\n" + "=" * 70)
print("2) STAGES de cada pipeline alvo (procurando 4/5/6)")
print("=" * 70)
stage_ids = {}  # pipeline_label -> {"4": (id,label), "5":..., "6":...}
for pid, plabel in found.items():
    print(f"\n  Pipeline {plabel!r} ({pid}):")
    sr = hs_get(f"/crm/v3/pipelines/deals/{pid}/stages?archived=false")
    picks = {}
    for s in sr.get("results", []):
        slabel = s.get("label", "")
        sid = s.get("id")
        order = s.get("displayOrder")
        matched = None
        for k in ("4", "5", "6"):
            if stage_matches(slabel, k):
                matched = k; break
        mark = f"  <-- {matched}" if matched else ""
        print(f"    order={order:>2}  id={sid:>12}  label={slabel!r}{mark}")
        if matched:
            picks[matched] = (sid, slabel)
    stage_ids[plabel] = picks
    time.sleep(0.2)

print("\n" + "=" * 70)
print("3) PROPRIEDADE customizada de potencial (busca por label)")
print("=" * 70)
# propriedades de deal — paginar
props = []
after = ""
while True:
    path = "/crm/v3/properties/deals" + (f"?after={after}" if after else "")
    pr = hs_get(path)
    props.extend(pr.get("results", []))
    after = (pr.get("paging") or {}).get("next", {}).get("after")
    if not after:
        break
    time.sleep(0.1)
print(f"  Total propriedades de deal: {len(props)}")
cands = []
for p in props:
    lab = (p.get("label") or "").lower()
    name = p.get("name", "")
    if "potencial" in lab and ("m" in lab and ("99" in lab or "total" in lab or "mês" in lab or "mes" in lab)):
        cands.append((name, p.get("label"), p.get("type"), p.get("fieldType")))
    elif "potencial" in lab and "total" in lab:
        cands.append((name, p.get("label"), p.get("type"), p.get("fieldType")))
print(f"  Candidatos a 'Potencial mês (total)':")
for name, lab, typ, ft in cands:
    print(f"    name={name!r:40s} label={lab!r:40s} type={typ} field={ft}")

print("\n" + "=" * 70)
print("RESUMO")
print("=" * 70)
out = {"pipelines": found, "stages": stage_ids, "potencial_candidates": cands}
print(json.dumps(out, ensure_ascii=False, indent=2))
with open("_schema_discovered.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("\nSalvo em _schema_discovered.json")
