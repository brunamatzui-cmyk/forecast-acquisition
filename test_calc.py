# -*- coding: utf-8 -*-
"""Teste do cálculo v2: fetch real + validação das regras de Negociação E
Ativação (atrasado 2.1, proporcionalidade, curva, carry-forward, owner names,
self-check, sanity de ambas as abas, duplicidade, consolidado).

Roda com: PYTHONUTF8=1 HUBSPOT_TOKEN=... python test_calc.py
"""
import datetime as dt

import fetch_hubspot as fh
import calc_forecast as cf
import selfcheck as sc

HOJE = dt.date(2026, 10, 15)  # data real; fixo p/ teste reproduzível

print("Buscando deals (4/5/6 + 7 Ativação, paralelo)...")
deals, owners, fetched_at = fh.fetch_deals(log=print)
print(f"Total: {len(deals)} deals | fetched_at: {fetched_at.isoformat()}\n")

neg, ativ, inc, meses = cf.calcular_todos(deals, hoje=HOJE)
print(f"Negociacao: {len(neg)} | Ativacao: {len(ativ)} | Incompletos: {len(inc)}")
print(f"Janela: {[m.strftime('%b/%y') for m in meses]}\n")

# ---- regra 2.1 atrasados (Negociação) ----
print("=" * 70)
print("ATRASADOS (regra 2.1: close+1m como base, +5dúteis):")
print("=" * 70)
n_atras = 0
for d in neg:
    if d["atrasado"]:
        n_atras += 1
        if n_atras <= 5:
            print(f"  {d['dealname'][:30]!r:32s} prev={d['previsao_fechamento']} "
                  f"base={d['base_fechamento']} ativ={d['ativacao']} "
                  f"atraso={d['dias_atraso']}d")
print(f"  ... total atrasados: {n_atras}\n")

# ---- ATIVAÇÃO (spec D) ----
print("=" * 70)
print("ATIVAÇÃO (rampa desde closedate, sem +5dúteis):")
print("=" * 70)
for d in ativ:
    v = [int(d["volumes"][m]) for m in meses]
    print(f"  {d['dealname'][:28]!r:30s} pipe={d['pipeline_label'][:18]:18s} "
          f"closed={d['entrada_ativacao']} dias={d['dias_ativacao']} "
          f"pot={d['potencial']} total6m={int(d['total_linha'])}")
    print(f"     meses: {v}")
print(f"  ... total em ativação: {len(ativ)}\n")

# ---- owner names (primeiro+último) ----
print("=" * 70)
print("OWNER NAMES (primeiro nome + último sobrenome):")
print("=" * 70)
for d in (neg + ativ)[:6]:
    print(f"  full={d['owner_full']!r:40s} -> {d['owner_name']!r}")

# ---- duplicidade entre abas ----
print()
print("=" * 70)
print("DUPLICIDADE Negociação x Ativação (esperado 0):")
print("=" * 70)
ids_neg = {d["deal_id"] for d in neg}
ids_ativ = {d["deal_id"] for d in ativ}
dup = ids_neg & ids_ativ
print(f"  {len(dup)} deal(s) em ambas as abas.")

# ---- sanity test Negociação (spec 5.5) ----
print("\n" + "=" * 70)
print("SANITY TEST Negociação (deals fictícios):")
print("=" * 70)
for desc, esp, curva, fator, out in cf.sanity_test_deals(HOJE):
    print(f"  {desc}: curva={curva} fator={fator:.4f} (esp 16/31={16/31:.4f})")
    esp_m1, esp_m2 = esp['m1'], esp['m2']
    esp_m3 = esp.get('m3', esp.get('m3+', 0))
    ok = (abs(fator-16/31)<0.001 and abs(out[0]-esp_m1)<2 and
          abs(out[1]-esp_m2)<2 and abs(out[2]-esp_m3)<2)
    print(f"    M1={int(out[0]):,} (esp {int(esp_m1):,}) | "
          f"M2={int(out[1]):,} (esp {int(esp_m2):,}) | "
          f"M3={int(out[2]):,} (esp {int(esp_m3):,})")
    print(f"    -> {'OK' if ok else 'FALHOU'}")

# ---- sanity test Ativação (spec 5.9) ----
print("\n" + "=" * 70)
print("SANITY TEST Ativação (deals fictícios):")
print("=" * 70)
for desc, esp, v, ok in cf.sanity_test_ativacao(hoje=HOJE):
    print(f"  {desc}: {[int(x) for x in v]} -> {'OK' if ok else 'FALHOU'}")

# ---- sanity test Negociação Potencial atualizado (aba 15%) ----
print("\n" + "=" * 70)
print("SANITY TEST Negociação Potencial atualizado (15%):")
print("=" * 70)
for desc, esp, v, ok in cf.sanity_test_negociacao_15(HOJE):
    print(f"  {desc}: {[int(x) for x in v]} -> {'OK' if ok else 'FALHOU'}")

# ---- aba Negociação Potencial atualizado (forecast sobre 15%) ----
print("\n" + "=" * 70)
print("NEGOCIAÇÃO POTENCIAL ATUALIZADO (forecast sobre 15%):")
print("=" * 70)
neg_15 = cf.calcular_negociacao_15(neg, meses, HOJE)
pot_orig = sum((d["potencial"] or 0) for d in neg_15)
pot15 = sum(d["potencial_15"] for d in neg_15)
print(f"  Deals: {len(neg_15)} | potencial original: {pot_orig:,} -> "
      f"15%: {pot15:,} | total 6m: {int(sum(d['total_linha'] for d in neg_15)):,}")
print("  (primeiros 8 deals: potencial -> 15% -> total6m -> meses)")
for d in neg_15[:8]:
    v = [int(d["volumes"][m]) for m in meses]
    print(f"  {d['dealname'][:28]!r:30s} pot={d['potencial']:>7,} "
          f"-> 15%={d['potencial_15']:>6,} total6m={int(d['total_linha']):>8,}")
    print(f"     meses: {v}")
print(f"  ... total deals 15%: {len(neg_15)}\n")
print("  TOTAL por mês (aba 15%):")
for m in meses:
    t = sum(d["volumes"][m] for d in neg_15)
    print(f"  {m.strftime('%b/%y'):8s} 15%={int(t):>10,}")
t6 = sum(d["total_linha"] for d in neg_15)
print(f"  {'TOTAL':8s} 15%={int(t6):>10,}")

# ---- self-check ----
print("\n" + "=" * 70)
print("SELF-CHECK:")
print("=" * 70)
checks = sc.run(neg, ativ, inc, meses, deals, hoje=HOJE)
print(f"  {sc.summary(checks)}")
for cid, st, msg, dl in checks:
    if st == "warn":
        print(f"  ⚠ [{cid}] {msg} ({len(dl)} deals)")

# ---- total consolidado ----
print("\n" + "=" * 70)
print("TOTAL por mês (Negociação + Ativação):")
print("=" * 70)
for m in meses:
    tn = sum(d['volumes'][m] for d in neg)
    ta = sum(d['volumes'][m] for d in ativ)
    print(f"  {m.strftime('%b/%y'):8s} neg={int(tn):>10,} ativ={int(ta):>8,} soma={int(tn+ta):>10,}")
tn6 = sum(d['total_linha'] for d in neg); ta6 = sum(d['total_linha'] for d in ativ)
print(f"  {'TOTAL':8s} neg={int(tn6):>10,} ativ={int(ta6):>8,} soma={int(tn6+ta6):>10,}")
