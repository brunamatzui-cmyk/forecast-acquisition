# -*- coding: utf-8 -*-
"""Teste do cálculo v2: fetch real + validação das regras (atrasado 2.1,
proporcionalidade, curva, carry-forward, owner names, self-check, sanity).
Roda com: PYTHONUTF8=1 python test_calc.py
"""
import datetime as dt

import fetch_hubspot as fh
import calc_forecast as cf
import selfcheck as sc

HOJE = dt.date(2026, 10, 1)  # spec: usar a data atual real; fixo p/ teste reproduzível

print("Buscando deals (paralelo, 3 pipelines)...")
deals, owners, fetched_at = fh.fetch_deals(log=print)
print(f"Total: {len(deals)} deals | fetched_at: {fetched_at.isoformat()}\n")

completos, incompletos, meses = cf.calcular_todos(deals, hoje=HOJE)
print(f"Completos: {len(completos)} | Incompletos: {len(incompletos)}")
print(f"Janela: {[m.strftime('%b/%y') for m in meses]}\n")

# ---- regra 2.1 atrasados (NOVA) ----
print("=" * 70)
print("ATRASADOS (regra 2.1: close+1m como base, +5dúteis):")
print("=" * 70)
n_atras = 0
for d in completos:
    if d["atrasado"]:
        n_atras += 1
        if n_atras <= 5:
            print(f"  {d['dealname'][:30]!r:32s} close={d['closedate']} "
                  f"base={d['base_fechamento']} ativ={d['ativacao']} "
                  f"atraso={d['dias_atraso']}d")
print(f"  ... total atrasados: {n_atras}\n")

# ---- owner names (primeiro+último) ----
print("=" * 70)
print("OWNER NAMES (primeiro nome + último sobrenome):")
print("=" * 70)
for d in completos[:6]:
    print(f"  full={d['owner_full']!r:40s} -> {d['owner_name']!r}")

# ---- sanity test (spec 5.5) ----
print("\n" + "=" * 70)
print("SANITY TEST (deals fictícios):")
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

# ---- self-check ----
print("\n" + "=" * 70)
print("SELF-CHECK:")
print("=" * 70)
checks = sc.run(completos, incompletos, meses, deals, hoje=HOJE)
print(f"  {sc.summary(checks)}")
for cid, st, msg, dl in checks:
    if st == "warn":
        print(f"  ⚠ [{cid}] {msg} ({len(dl)} deals)")

# ---- total ----
print("\n" + "=" * 70)
print("TOTAL por mês:")
print("=" * 70)
for m in meses:
    print(f"  {m.strftime('%b/%y'):8s} {int(sum(d['volumes'][m] for d in completos)):>10,}")
print(f"  {'TOTAL':8s} {int(sum(d['total_linha'] for d in completos)):>10,}")
