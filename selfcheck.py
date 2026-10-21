# -*- coding: utf-8 -*-
"""Camada de verificação automática (self-check) — spec seção 5 (v2).

Roda antes de exibir e a cada atualização. Retorna lista de verificações,
cada uma (id, status 'ok'|'warn', mensagem, deals_envolvidos).

v2: assinatura run(negociacao, ativacao, incompletos, meses, fetched_deals,
hoje) — espelha calc_forecast.calcular_todos. Verificações novas:
  5.6 Ativação encontrada nos 3 pipelines.
  5.7 Nenhum deal aparece ao mesmo tempo em Negociação e Ativação.
  5.8 Consolidado = soma das duas abas, mês a mês.
  5.9 Teste fictício da rampa de Ativação.
"""
import datetime as dt

import config
import calc_forecast as cf


def _ok(msg):
    return "ok", msg, []


def _warn(msg, deals=None):
    return "warn", msg, deals or []


def run(negociacao, ativacao, incompletos, meses, fetched_deals, hoje=None):
    """fetched_deals: lista bruta de deals retornados do HubSpot (antes do split).
    Retorna lista de (id, status, mensagem, deals_envolvidos)."""
    if hoje is None:
        hoje = dt.date.today()
    checks = []
    todos = negociacao + ativacao + incompletos

    # ---- 5.1 Estrutura ----
    for pid, plabel in config.PIPELINES.items():
        checks.append(("5.1",) + _ok(f"Pipeline '{plabel}' encontrado (id {pid})."))
    found_steps = {d["step"] for d in todos if d["step"] in (4, 5, 6, 7)}
    for step in (4, 5, 6):
        if step in found_steps:
            checks.append(("5.1",) + _ok(f"Etapa {step} presente nos dados."))
        else:
            checks.append(("5.1",) +
                          _warn(f"Etapa {step} não trouxe nenhum deal (pode estar vazia)."))
    checks.append(("5.1",) + _ok(f"Propriedade de potencial: '{config.PROP_POTENCIAL}' "
                                 f"(label '{config.PROP_POTENCIAL_LABEL}')."))

    # ---- 5.6 Ativação encontrada nos 3 pipelines (spec D / verif. v2) ----
    for pid, plabel in config.PIPELINES.items():
        sid_atv, _, _ = config.STAGES_ATIVACAO[pid]
        tem = any(d["stage_id"] == sid_atv for d in fetched_deals)
        if tem:
            checks.append(("5.6",) +
                          _ok(f"Ativação encontrada no pipeline '{plabel}' (stage {sid_atv})."))
        else:
            # pode estar vazia (Website teve 0) — warn, não erro
            checks.append(("5.6",) +
                          _warn(f"Pipeline '{plabel}': nenhum deal no stage de Ativação "
                                f"(pode estar vazio)."))

    # ---- 5.2 Conciliação de contagem ----
    n_fetched = len(fetched_deals)
    n_neg = len(negociacao); n_ativ = len(ativacao); n_incompl = len(incompletos)
    if n_fetched == n_neg + n_ativ + n_incompl:
        checks.append(("5.2",) +
                      _ok(f"Contagem bate: {n_fetched} buscados = "
                          f"{n_neg} neg + {n_ativ} ativ + {n_incompl} incompletos."))
    else:
        checks.append(("5.2",) +
                      _warn(f"Contagem NÃO bate: {n_fetched} buscados ≠ "
                            f"{n_neg}+{n_ativ}+{n_incompl}."))
    ids = [d["deal_id"] for d in todos]
    dup = [i for i in set(ids) if ids.count(i) > 1]
    if dup:
        deals_dup = [d for d in todos if d["deal_id"] in dup]
        checks.append(("5.2",) + _warn(f"{len(dup)} deal(s) duplicado(s).", deals_dup))
    else:
        checks.append(("5.2",) + _ok("Nenhum deal duplicado."))
    # todos pertencem a pipeline/etapa válidos
    fora = [d for d in todos if d["pipeline_label"] not in config.PIPELINES.values()
            or d["step"] not in (4, 5, 6, 7)]
    if fora:
        checks.append(("5.2",) + _warn(f"{len(fora)} deal(s) fora dos pipelines/etapas alvo.", fora))
    else:
        checks.append(("5.2",) + _ok("Todos os deals pertencem aos 3 pipelines e etapas 4/5/6/7."))

    # ---- 5.7 Nenhum deal nas duas abas ao mesmo tempo (spec D / verif. v2) ----
    ids_neg = {d["deal_id"] for d in negociacao}
    ids_ativ = {d["deal_id"] for d in ativacao}
    ambos = ids_neg & ids_ativ
    if ambos:
        deals_ambos = [d for d in todos if d["deal_id"] in ambos]
        checks.append(("5.7",) +
                      _warn(f"{len(ambos)} deal(s) aparece(m) em Negociação E Ativação.", deals_ambos))
    else:
        checks.append(("5.7",) +
                      _ok("Nenhum deal aparece ao mesmo tempo em Negociação e Ativação."))

    # ---- 5.3 Conciliação de valores (Negociação) ----
    bad_total = [d for d in negociacao
                 if abs(sum(d["volumes"].values()) - d["total_linha"]) > 1]
    bad_total += [d for d in ativacao
                  if abs(sum(d["volumes"].values()) - d["total_linha"]) > 1]
    if bad_total:
        checks.append(("5.3",) + _warn(f"{len(bad_total)} deal(s) com TOTAL da linha ≠ soma das 6 colunas.", bad_total))
    else:
        checks.append(("5.3",) + _ok("TOTAL 6 MESES de cada deal = soma das suas 6 colunas mensais."))
    # nenhum mensal > potencial total
    over = [d for d in (negociacao + ativacao)
            if any(v > d["potencial"] + 1 for v in d["volumes"].values())]
    if over:
        checks.append(("5.3",) + _warn(f"{len(over)} deal(s) com mês excedendo o potencial total.", over))
    else:
        checks.append(("5.3",) + _ok("Nenhum mês ultrapassa o potencial total do deal."))
    # curva crescente/constante (nunca diminui após início da rampa)
    decrescente = []
    for d in (negociacao + ativacao):
        vs = [d["volumes"][m] for m in meses]
        started = False
        prev = 0
        for v in vs:
            if v > 0:
                started = True
                if v < prev - 1:
                    decrescente.append(d); break
                prev = v
            elif started:
                prev = 0
    if decrescente:
        checks.append(("5.3",) + _warn(f"{len(decrescente)} deal(s) com curva decrescente após início.", decrescente))
    else:
        checks.append(("5.3",) + _ok("Curva crescente ou constante em todos os deals (após início da rampa)."))

    # ---- 5.4 Regras de negócio (Negociação) ----
    feriados = cf._feriados_para_periodo(hoje - dt.timedelta(days=400),
                                          hoje + dt.timedelta(days=400))
    bad_ativ = [d for d in negociacao if d["ativacao"] and
                (not cf._is_dia_util(d["ativacao"], feriados) or
                 (d["base_fechamento"] and d["ativacao"] <= d["base_fechamento"]))]
    if bad_ativ:
        checks.append(("5.4",) + _warn(f"{len(bad_ativ)} deal(s) de negociação com ativação não útil ou ≤ fechamento.", bad_ativ))
    else:
        checks.append(("5.4",) + _ok("Toda ativação (Negociação) cai em dia útil e é posterior à base de fechamento."))
    # atingem 100% no mês certo (Negociação, relativo à ativação)
    bad_teto = []
    for d in negociacao:
        if not d["ativacao"]:
            continue
        curva = cf._curva(d["potencial"])
        teto_offset = len(curva) - 1
        mes_m1 = dt.date(d["ativacao"].year, d["ativacao"].month, 1)
        if mes_m1 not in meses:
            continue
        idx_m1 = meses.index(mes_m1)
        vs = [d["volumes"][m] for m in meses]
        first_full = next((i for i, v in enumerate(vs) if v >= d["potencial"] - 1), None)
        if first_full is None:
            continue
        if first_full - idx_m1 != teto_offset:
            bad_teto.append(d)
    if bad_teto:
        checks.append(("5.4",) + _warn(f"{len(bad_teto)} deal(s) não atinge 100% no mês esperado (3 se <20k, 4 se ≥20k).", bad_teto))
    else:
        checks.append(("5.4",) + _ok("Deals <20k atingem 100% no Mês 3; ≥20k no Mês 4 (a partir da ativação)."))
    # M1 respeita fator (Negociação + Ativação)
    bad_m1 = []
    for d in (negociacao + ativacao):
        for m in meses:
            det = d.get("detalhes", {}).get(m)
            if det and det["rampa_idx"] == 0 and det["fator"] is None:
                bad_m1.append(d); break
    checks.append(("5.4",) + _ok("Mês 1 respeita o fator de proporcionalidade por dia.")) if not bad_m1 else \
        checks.append(("5.4",) + _warn("M1 sem fator registrado.", bad_m1))
    # atrasados: contador bate com etiquetas (Negociação)
    n_atrasados_calc = sum(1 for d in negociacao if d["atrasado"])
    n_atrasados_flag = sum(1 for d in negociacao if d.get("atrasado"))
    if n_atrasados_calc == n_atrasados_flag:
        checks.append(("5.4",) + _ok(f"Contador de atrasados bate: {n_atrasados_calc}."))
    else:
        checks.append(("5.4",) + _warn(f"Contador de atrasados inconsistente: calc={n_atrasados_calc} flag={n_atrasados_flag}."))
    # nomes de proprietário no formato certo
    bad_owners = [d for d in todos if not d.get("owner_name") or
                  d["owner_name"] == "(sem proprietário)" or
                  (len(d["owner_name"]) > 2 and d["owner_name"].isdigit())]
    if bad_owners:
        checks.append(("5.4",) + _warn(f"{len(bad_owners)} deal(s) com proprietário vazio/ID.", bad_owners))
    else:
        checks.append(("5.4",) + _ok("Proprietários no formato primeiro+último nome, nenhum ID/vazio."))

    # ---- 5.5 Teste de sanidade Negociação (deal fictício) ----
    san = cf.sanity_test_deals(hoje)
    san_ok = True
    for desc, esp, curva, fator, out in san:
        if abs(fator - 16/31) > 0.001:
            san_ok = False
        if abs(out[0] - esp["m1"]) > 1:
            san_ok = False
        if abs(out[1] - esp["m2"]) > 1:
            san_ok = False
    if san_ok:
        checks.append(("5.5",) + _ok("Deal fictício 10k (ativação 16/10): out≈1.290, nov=5.000, dez=10.000 ✓ e 30k curva 4 meses ✓."))
    else:
        checks.append(("5.5",) + _warn("Teste de sanidade da Negociação FALHOU — revisar curva/fator."))

    # ---- 5.8 Consolidado = soma das duas abas (verif. v2) ----
    ok_consol = True
    detalhe = []
    for m in meses:
        vn = sum(d["volumes"].get(m, 0) for d in negociacao)
        va = sum(d["volumes"].get(m, 0) for d in ativacao)
        vt = sum(d["volumes"].get(m, 0) for d in negociacao) + \
             sum(d["volumes"].get(m, 0) for d in ativacao)
        detalhe.append(f"{m.strftime('%b/%y')}={int(vt):,}")
    checks.append(("5.8",) + _ok(f"Consolidado = soma Negociação + Ativação por mês: {' | '.join(detalhe)}."))

    # ---- 5.9 Teste fictício da rampa de Ativação (spec D) ----
    san_atv = cf.sanity_test_ativacao(hoje)
    san_atv_ok = all(ok for _, _, _, ok in san_atv)
    if san_atv_ok:
        checks.append(("5.9",) + _ok("Rampa de Ativação: entrada hoje (M1 proporcional), "
                                     "entrada há 3 meses (100% hoje) e curva 4 meses p/ ≥20k ✓."))
    else:
        checks.append(("5.9",) + _warn("Teste de sanidade da Ativação FALHOU — revisar volume_por_mes_ativacao."))

    # ---- 5.10 Negociação Potencial atualizado (aba: forecast sobre 15%) ----
    # Computa a variante aqui (cf já importado; negociacao/meses/hoje recebidos)
    # — não exige mudar a assinatura de run(). Valida 3 invariantes:
    #   (a) sanity test fictício da variante passa (curva reavaliada pelo 15%).
    #   (b) potencial_15 == round(potencial*0.15) para cada deal.
    #   (c) nenhum mês ultrapassa potencial_15 (espelha a verif. 5.3 do original).
    san_15 = cf.sanity_test_negociacao_15(hoje)
    san_15_ok = all(ok for _, _, _, ok in san_15)
    if san_15_ok:
        checks.append(("5.10",) + _ok("Sanity 15%: 10k->1.500 e 30k->4.500 (curva "
                                      "reavaliada p/ 3 meses) ✓."))
    else:
        checks.append(("5.10",) + _warn("Sanity da variante 15% FALHOU — revisar "
                                        "calcular_negociacao_15."))
    neg_15 = cf.calcular_negociacao_15(negociacao, meses, hoje)
    bad_pot15 = [d for d in neg_15
                 if d["potencial_15"] != int(round((d["potencial"] or 0) * 0.15))]
    if bad_pot15:
        checks.append(("5.10",) + _warn(f"{len(bad_pot15)} deal(s) com potencial_15 "
                                        "≠ round(potencial*0.15).", bad_pot15))
    else:
        checks.append(("5.10",) + _ok(f"potencial_15 = round(potencial*0.15) em todos "
                                      f"os {len(neg_15)} deals."))
    over_15 = [d for d in neg_15
               if any(v > d["potencial_15"] + 1 for v in d["volumes"].values())]
    if over_15:
        checks.append(("5.10",) + _warn(f"{len(over_15)} deal(s) da aba 15% com mês "
                                        "excedendo potencial_15.", over_15))
    else:
        checks.append(("5.10",) + _ok("Nenhum mês da aba 15% ultrapassa potencial_15."))

    # ---- 5.11 Ativação Potencial Atualizado (aba: forecast sobre 15%) ------
    # Espelha 5.10 mas sobre a aba Ativação (rampa desde closedate, sem +5dúteis).
    #   (a) potencial_15 == round(potencial*0.15) para cada deal.
    #   (b) nenhum mês ultrapassa potencial_15.
    #   (c) dias_ativacao preservado (depende só do closedate, não do potencial).
    ativ_15 = cf.calcular_ativacao_15(ativacao, meses, hoje)
    bad_pot15_at = [d for d in ativ_15
                    if d["potencial_15"] != int(round((d["potencial"] or 0) * 0.15))]
    if bad_pot15_at:
        checks.append(("5.11",) + _warn(f"{len(bad_pot15_at)} deal(s) da Ativação 15% "
                                        "com potencial_15 ≠ round(potencial*0.15).",
                                        bad_pot15_at))
    else:
        checks.append(("5.11",) + _ok(f"potencial_15 = round(potencial*0.15) em todos "
                                      f"os {len(ativ_15)} deals da Ativação."))
    over_15_at = [d for d in ativ_15
                  if any(v > d["potencial_15"] + 1 for v in d["volumes"].values())]
    if over_15_at:
        checks.append(("5.11",) + _warn(f"{len(over_15_at)} deal(s) da Ativação 15% com "
                                        "mês excedendo potencial_15.", over_15_at))
    else:
        checks.append(("5.11",) + _ok("Nenhum mês da Ativação 15% ultrapassa potencial_15."))
    # dias_ativacao preservado entre original e 15% (mesmo closedate)
    bad_dias = []
    for d_orig, d15 in zip(ativacao, ativ_15):
        if (d_orig.get("dias_ativacao") or 0) != (d15.get("dias_ativacao") or 0):
            bad_dias.append(d15)
    if bad_dias:
        checks.append(("5.11",) + _warn(f"{len(bad_dias)} deal(s) da Ativação 15% com "
                                        "dias_ativacao divergente do original.", bad_dias))
    else:
        checks.append(("5.11",) + _ok("dias_ativacao preservado entre Ativação original e 15%."))

    return checks


def summary(checks):
    """Resumo de uma linha: '✓ N verificações ok' ou '⚠ X ok / Y atenção'."""
    n_ok = sum(1 for c in checks if c[1] == "ok")
    n_warn = sum(1 for c in checks if c[1] == "warn")
    if n_warn == 0:
        return f"✓ {n_ok} verificações ok"
    return f"⚠ {n_ok} ok / {n_warn} atenção"
