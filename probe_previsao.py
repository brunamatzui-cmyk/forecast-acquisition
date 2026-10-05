# -*- coding: utf-8 -*-
"""Probe: acha a propriedade de 'previsão de fechamento' no HubSpot pelo label.

O closedate é 'Data de fechamento' (vira real ao fechar). A previsão é outra
propriedade. Lista candidatos com 'previs'/'forecast'/'expected' no label.
"""
import os
import time
import requests

BASE = "https://api.hubapi.com"
TOKEN = os.environ["HUBSPOT_TOKEN"]
HEADERS = {"Authorization": "Bearer " + TOKEN}

props = []
after = ""
while True:
    path = "/crm/v3/properties/deals" + (f"?after={after}" if after else "")
    r = requests.get(BASE + path, headers=HEADERS, timeout=60)
    r.raise_for_status()
    pr = r.json()
    props.extend(pr.get("results", []))
    after = (pr.get("paging") or {}).get("next", {}).get("after")
    if not after:
        break
    time.sleep(0.1)

print(f"Total propriedades: {len(props)}\n")
print("=== candidatos a 'previsão de fechamento' ===")
for p in props:
    lab = (p.get("label") or "").lower()
    name = p.get("name", "")
    if ("previs" in lab or "forecast" in lab or "expected" in lab or "projet" in lab) and ("fech" in lab or "close" in lab or "win" in lab or "deal" in lab or "fecha" in lab):
        print(f"  name={name!r:40s} label={p.get('label')!r:40s} type={p.get('type')}")

print("\n=== closedate (referência: 'Data de fechamento') ===")
for p in props:
    if p.get("name") == "closedate":
        print(f"  name={p['name']!r} label={p.get('label')!r} type={p.get('type')}")
