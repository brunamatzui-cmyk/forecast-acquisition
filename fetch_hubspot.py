# -*- coding: utf-8 -*-
"""Camada 1 — coleta de deals do HubSpot (spec 4.1/4.3/4.4).

- Filtra pipelines E etapas direto na consulta (nunca traz tudo p/ filtrar).
- Só pede as propriedades necessárias, página máxima (100).
- Owners em uma única chamada em lote, reutilizada.
- Consultas por pipeline em PARALELO (spec 4.3) via ThreadPoolExecutor.
- Atualização incremental: buscar só deals com hs_lastmodifieddate >= última
  atualização, mesclar com os já carregados; e confirmar elegíveis (ainda em
  4/5/6) com uma consulta leve de IDs.
"""
import datetime as dt
import time
from concurrent.futures import ThreadPoolExecutor

import requests

import config
import theme


def _headers():
    return {
        "Authorization": f"Bearer {config._load_hubspot_token()}",
        "Content-Type": "application/json",
    }


def _val(prop_value):
    if isinstance(prop_value, dict):
        return prop_value.get("value")
    return prop_value


def _search_page(stage_ids, pipeline_id, after=None, modified_since=None):
    """Uma página da Search API. IN usa 'values' (array). Paginação via after.
    modified_since (ms epoch): filtro hs_lastmodifieddate GTE p/ incremental."""
    filters = [
        {"value": pipeline_id, "propertyName": "pipeline", "operator": "EQ"},
        {"values": list(stage_ids), "propertyName": "dealstage", "operator": "IN"},
    ]
    if modified_since is not None:
        filters.append({"value": str(modified_since),
                        "propertyName": config.PROP_LASTMOD, "operator": "GTE"})
    body = {
        "filterGroups": [{"filters": filters}],
        "properties": config.DEAL_PROPERTIES,
        "limit": config.PAGE_SIZE,
    }
    if after is not None:
        body["after"] = int(after)
    for _ in range(5):
        r = requests.post(f"{config.BASE}/crm/v3/objects/deals/search",
                          headers=_headers(), json=body, timeout=60)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", "10")) + 1)
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def _parse_potencial(raw):
    """String c/ separador de milhar BR ('16.000'=16000). Ver v1."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s == "":
        return None
    s = s.replace(" ", "")
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if all(len(p) == 3 for p in parts[1:]) and len(parts) > 1:
            s = "".join(parts)
    elif "," in s:
        s = s.replace(",", ".")
    try:
        n = float(s)
    except ValueError:
        return None
    if n != n or n < 0:
        return None
    return int(round(n))


def _parse_hs_date(raw):
    """closedate/lastmodified: '2026-10-30' ou epoch-ms -> date."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s == "":
        return None
    if s.isdigit() and len(s) >= 12:
        try:
            return dt.datetime.fromtimestamp(int(s) / 1000.0).date()
        except (ValueError, OSError):
            pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def fetch_owners():
    """Mapeia hubspot_owner_id -> nome completo (Owners API v3). Uma chamada
    paginada, reutilizada por todos os pipelines (spec 4.3)."""
    headers = {"Authorization": f"Bearer {config._load_hubspot_token()}"}
    owners = {}
    after = ""
    while True:
        path = f"{config.BASE}/crm/v3/owners?limit=100" + (f"&after={after}" if after else "")
        r = requests.get(path, headers=headers, timeout=60)
        r.raise_for_status()
        res = r.json()
        for o in res.get("results", []):
            fn = (o.get("firstName") or "").strip()
            ln = (o.get("lastName") or "").strip()
            name = (fn + " " + ln).strip() or o.get("email", "")
            if name:
                owners[o["id"]] = name
        after = (res.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break
        time.sleep(0.2)
    return owners


def _fetch_pipeline(pid, plabel, stage_ids, modified_since=None):
    """Busca TODOS os deals de um pipeline (paginado)."""
    raw, after = [], None
    while True:
        page = _search_page(stage_ids, pid, after, modified_since)
        raw.extend(page.get("results", []))
        after = page.get("paging", {}).get("next", {}).get("after")
        if not after:
            break
        time.sleep(0.2)
    return pid, plabel, raw


def _build_deal(d, owners, plabel_default, hoje_date):
    p = d.get("properties", {})
    oid = _val(p.get("hubspot_owner_id"))
    owner_full = owners.get(oid) if oid else None
    owner_name = theme.owner_display_name(owner_full) if owner_full else "(sem proprietário)"
    stage_id = _val(p.get("dealstage"))
    step, stage_label = config.STAGE_BY_ID.get(stage_id, (None, str(stage_id)))
    closedate = _parse_hs_date(_val(p.get("closedate")))
    potencial = _parse_potencial(_val(p.get(config.PROP_POTENCIAL)))
    lastmod = _parse_hs_date(_val(p.get(config.PROP_LASTMOD)))
    pid = _val(p.get("pipeline"))
    return {
        "deal_id": d.get("id"),
        "dealname": (_val(p.get("dealname")) or "(sem nome)").strip(),
        "stage_id": stage_id,
        "step": step,
        "stage_label": stage_label,
        "pipeline_id": pid,
        "pipeline_label": config.PIPELINES.get(pid, plabel_default),
        "owner_name": owner_name,
        "owner_full": owner_full or "",
        "closedate": closedate,
        "potencial": potencial,
        "lastmodified": lastmod,
        "atrasado": bool(closedate and closedate < hoje_date and step in (4, 5, 6)),
    }


def fetch_deals(log=print, modified_since=None, hoje_date=None):
    """Busca deals dos 3 pipelines nas etapas 4/5/6, em paralelo.

    modified_since (datetime): se passado, busca incremental (só modificados
    desde então). None = carga completa.
    Retorna (deals, owners, fetched_at).
    """
    if hoje_date is None:
        hoje_date = dt.date.today()
    owners = fetch_owners()
    log(f"Owners: {len(owners)} mapeados.")

    ms = int(modified_since.timestamp() * 1000) if modified_since else None
    tasks = [(pid, plabel, [s[0] for s in config.STAGES[pid]], ms)
             for pid, plabel in config.PIPELINES.items()]
    deals = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = [ex.submit(_fetch_pipeline, *t) for t in tasks]
        for f in futures:
            pid, plabel, raw = f.result()
            for d in raw:
                deals.append(_build_deal(d, owners, plabel, hoje_date))
            log(f"  {plabel}: {len(raw)} deals.")

    fetched_at = dt.datetime.now()
    return deals, owners, fetched_at


def fetch_eligible_ids(hoje_date=None):
    """Consulta leve: só IDs dos deals ainda em 4/5/6 (spec 4.4).
    Usado p/ remover deals que saíram das etapas num refresh incremental."""
    if hoje_date is None:
        hoje_date = dt.date.today()
    ids = set()
    for pid, plabel in config.PIPELINES.items():
        stage_ids = [s[0] for s in config.STAGES[pid]]
        body = {
            "filterGroups": [{"filters": [
                {"value": pid, "propertyName": "pipeline", "operator": "EQ"},
                {"values": list(stage_ids), "propertyName": "dealstage", "operator": "IN"},
            ]}],
            "properties": ["dealstage"],   # enxuto: só precisa do ID
            "limit": config.PAGE_SIZE,
        }
        after = None
        while True:
            if after:
                body["after"] = int(after)
            r = requests.post(f"{config.BASE}/crm/v3/objects/deals/search",
                              headers=_headers(), json=body, timeout=60)
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", "10")) + 1); continue
            r.raise_for_status()
            page = r.json()
            for d in page.get("results", []):
                ids.add(d.get("id"))
            after = page.get("paging", {}).get("next", {}).get("after")
            if not after:
                break
            time.sleep(0.2)
    return ids
