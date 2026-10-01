# -*- coding: utf-8 -*-
"""Busca todos os deals nas etapas 4/5/6 dos 3 pipelines de aquisição via
HubSpot Search API, com paginação. Resolve o nome do proprietário pelo ID
(via Owners API). Mesma abordagem do ../dashboard/activation/fetch_hubspot.py:
REST direta + Private App Token, nunca MCP.

Retorna:
  deals:   lista de dicts com dados do deal (sem o volume calculado).
  owners:  dict hubspot_owner_id -> nome.
  incompletos: deals sem closedate ou potencial (separados, fora dos totais).
  fetched_at: timestamp ISO da busca.
"""
import datetime as dt
import time

import requests

import config


def _headers():
    return {
        "Authorization": f"Bearer {config._load_hubspot_token()}",
        "Content-Type": "application/json",
    }


def _val(prop_value):
    """Propriedades vêm como {'value': ..., 'timestamp': ...} ou direto."""
    if isinstance(prop_value, dict):
        return prop_value.get("value")
    return prop_value


def _search_page(stage_ids, pipeline_id, after=None):
    """Uma página da Search API. Filtro IN usa 'values' (array), não 'value'
    string. Paginação via body['after'] = int(cursor)."""
    body = {
        "filterGroups": [{"filters": [
            {"value": pipeline_id, "propertyName": "pipeline", "operator": "EQ"},
            {"values": list(stage_ids), "propertyName": "dealstage", "operator": "IN"},
        ]}],
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
    """Potencial vem como string. Pode ter separador de milhar brasileiro
    ('16.000' = 16000, NÃO 16.0). Heurística BR: se há '.' e a parte após
    tem != 3 dígitos, é decimal; se tem 3 dígitos (ou múltiplos grupos),
    é separador de milhar. Também trata ',' como decimal BR.
    Retorna int >= 0 ou None se vazio/inválido."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s == "":
        return None
    s = s.replace(" ", "")
    has_dot = "." in s
    has_comma = "," in s
    if has_dot and has_comma:
        # BR: ponto=milhar, vírgula=decimal  ->  "1.234,56"
        s = s.replace(".", "").replace(",", ".")
    elif has_dot:
        parts = s.split(".")
        # grupos de milhar: todos com 3 dígitos exceto o primeiro -> separador
        if all(len(p) == 3 for p in parts[1:]) and len(parts) > 1:
            s = "".join(parts)           # "16.000" -> "16000"
        # senão mantém como decimal (ex: "1.5" -> 1.5)
    elif has_comma:
        # só vírgula -> decimal BR  "1234,56" -> "1234.56"
        s = s.replace(",", ".")
    try:
        n = float(s)
    except ValueError:
        return None
    if n != n or n < 0:  # NaN ou negativo
        return None
    return int(round(n))


def fetch_owners():
    """Mapeia hubspot_owner_id -> nome completo (Owners API v3)."""
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


def fetch_deals(log=print):
    """Busca TODOS os deals dos 3 pipelines nas etapas 4/5/6.

    Retorna (deals, owners, fetched_at):
      deals: lista de dicts com chaves
        deal_id, dealname, stage_id, step, stage_label, pipeline_id,
        pipeline_label, owner_name, closedate (datetime|None),
        potencial (int|None), atrasado (bool).
    """
    owners = fetch_owners()
    log(f"Owners: {len(owners)} mapeados.")

    raw_deals = []
    for pid, plabel in config.PIPELINES.items():
        stage_ids = [s[0] for s in config.STAGES[pid]]
        after = None
        n_before = len(raw_deals)
        while True:
            page = _search_page(stage_ids, pid, after)
            raw_deals.extend(page.get("results", []))
            after = page.get("paging", {}).get("next", {}).get("after")
            if not after:
                break
            time.sleep(0.25)
        log(f"  {plabel}: {len(raw_deals) - n_before} deals.")

    fetched_at = dt.datetime.now()
    deals = []
    for d in raw_deals:
        p = d.get("properties", {})
        oid = _val(p.get("hubspot_owner_id"))
        owner_name = owners.get(oid) if oid else None
        if not owner_name:
            owner_name = "(sem proprietário)"
        stage_id = _val(p.get("dealstage"))
        step, stage_label = config.STAGE_BY_ID.get(stage_id, (None, str(stage_id)))
        closed_raw = _val(p.get("closedate"))
        closedate = _parse_hs_date(closed_raw)
        potencial = _parse_potencial(_val(p.get(config.PROP_POTENCIAL)))
        deals.append({
            "deal_id": d.get("id"),
            "dealname": (_val(p.get("dealname")) or "(sem nome)").strip(),
            "stage_id": stage_id,
            "step": step,
            "stage_label": stage_label,
            "pipeline_id": d.get("pipeline") if "pipeline" in d else pid,
            "pipeline_label": plabel if False else config.PIPELINES.get(
                _val(p.get("pipeline")), plabel),
            "owner_name": owner_name,
            "closedate": closedate,
            "potencial": potencial,
            "atrasado": bool(closedate and closedate < fetched_at.date()
                             and step in (4, 5, 6)),
        })
    return deals, owners, fetched_at


def _parse_hs_date(raw):
    """HubSpot closedate vem como '2026-10-30' ou epoch-ms. Retorna date."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s == "":
        return None
    # epoch millis
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
