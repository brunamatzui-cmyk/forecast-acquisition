# -*- coding: utf-8 -*-
"""Teste do cálculo: busca deals reais, calcula forecast, e valida casos
manualmente (feriados, proporcionalidade, curva, deals atrasados).
"""
import datetime as dt

import config
import fetch_hubspot as fh
import calc_forecast as cf

HOJE = dt.date(2026, 10, 1)  # spec: hoje é 30/09/2026; uso 01/10 p/ testar janela

print("Buscando deals...")
deals, owners, fetched_at = fh.fetch_deals(log=print)
print(f"Total deals: {len(deals)} | fetched_at: {fetched_at.isoformat()}\n")

completos, incompletos, meses = cf.calcular_todos(deals, hoje=HOJE)
print(f"Completos: {len(completos)} | Incompletos: {len(incompletos)}")
print(f"Janela de meses: {[m.strftime('%b/%y') for m in meses]}\n")

# valida casos conhecidos do probe
print("=" * 70)
print("AMOSTRA de completos (com cálculo):")
print("=" * 70)
for d in completos[:8]:
    print(f"\n  {d['dealname'][:40]!r:42s} {d['pipeline_label']:20s} step={d['step']}")
    print(f"    closedate={d['closedate']}  potencial={d['potencial']:,}  atrasado={d['atrasado']}")
    print(f"    ativacao={d['ativacao']}")
    print(f"    curva={cf._curva(d['potencial'])}  fator_m1={cf._fator_proporcional(d['ativacao']):.4f}")
    vols = {m.strftime('%b/%y'): round(v) for m, v in d['volumes'].items() if v > 0}
    print(f"    volumes: {vols}")
    print(f"    total_linha={int(d['total_linha']):,}")

print("\n" + "=" * 70)
print("INCOMPLETOS:")
print("=" * 70)
for d in incompletos[:10]:
    print(f"  {d['dealname'][:40]!r:42s} {d['pipeline_label']:20s} -> {d['motivo_incompleto']}")

# TOTAL por mês
print("\n" + "=" * 70)
print("TOTAL por mês (todos completos):")
print("=" * 70)
for m in meses:
    tot = sum(d['volumes'][m] for d in completos)
    print(f"  {m.strftime('%b/%y'):8s} {int(tot):>10,}")
print(f"  {'TOTAL':8s} {int(sum(d['total_linha'] for d in completos)):>10,}")
