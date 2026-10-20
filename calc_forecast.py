# -*- coding: utf-8 -*-
"""Cálculo do forecast de corridas por mês (v2 — spec 2026-10-01).

Regras:
  - Ativação (2.1):
      * fechamento futuro ou hoje  -> fechamento + 5 dias úteis.
      * fechamento ATRASADO (< hoje): nova data de fechamento = fechamento + 1 mês;
        se ainda no passado, base = hoje + 1 mês. Depois + 5 dias úteis.
      Mostra-se a previsão ORIGINAL (evidencia atraso) + a ativação recalculada.
  - Mês 1 (2.2): mês calendário da ativação, volume = potencial × 25% ×
    (dias_ativos / dias_no_mês). Ex: ativação 16/10 (31 dias) -> 16/31.
  - Curva (2.3):
      potencial < 20.000: [25%, 50%, 100%]   (100% a partir do mês 3)
      potencial >= 20.000: [25%, 50%, 75%, 100%] (100% a partir do mês 4)
      Após atingir 100%, permanece 100% nos meses seguintes da janela.
  - Janela (2.4): 6 meses a partir do mês atual (inclusive). Ativação fora da
    janela ou meses anteriores ao M1 -> zerados.
  - Probabilidade (2.5): 100% (não pondera por etapa).

Determinístico: feriados como constante, dias úteis por função (spec 4.5).
"""
import calendar
import datetime as dt

import config

# ---- Feriados nacionais BR (constante, spec 4.5) ------------------------
# Fixos + móveis (Carnaval seg/ter, Sexta-feira Santa, Corpus Christi).
def _carnaval(ano):
    a = ano % 19
    b = ano // 100
    c = ano % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    pascoa = dt.date(ano, mes, dia)
    return [
        pascoa - dt.timedelta(days=48),   # segunda de Carnaval
        pascoa - dt.timedelta(days=47),   # terça
        pascoa - dt.timedelta(days=2),    # Sexta-feira Santa
        pascoa + dt.timedelta(days=60),   # Corpus Christi
    ]


def _feriados_nacionais(ano):
    fixos = [
        dt.date(ano, 1, 1), dt.date(ano, 4, 21), dt.date(ano, 5, 1),
        dt.date(ano, 9, 7), dt.date(ano, 10, 12), dt.date(ano, 11, 2),
        dt.date(ano, 11, 15), dt.date(ano, 12, 25),
    ]
    return set(fixos + _carnaval(ano))


def _feriados_para_periodo(start, end):
    feriados = set()
    for ano in range(start.year, end.year + 1):
        feriados |= _feriados_nacionais(ano)
    return feriados


def _add_dias_uteis(data, n, feriados):
    """Soma n dias úteis a `data`, contando a partir do dia seguinte."""
    cur = data
    added = 0
    while added < n:
        cur = cur + dt.timedelta(days=1)
        if cur.weekday() < 5 and cur not in feriados:
            added += 1
    return cur


def _is_dia_util(data, feriados):
    return data.weekday() < 5 and data not in feriados


def _add_meses(data, n):
    """Soma n meses calendário (mesmo dia; ajusta se o dia não existir)."""
    m = data.month - 1 + n
    y = data.year + m // 12
    m = m % 12 + 1
    dia = min(data.day, calendar.monthrange(y, m)[1])
    return dt.date(y, m, dia)


# ---- Ativação (spec 2.1) -------------------------------------------------
def data_ativacao(closedate, hoje, feriados=None):
    """Retorna (ativacao, base_fechamento_usada, atrasado).

    atrasado: closedate < hoje.
    base_fechamento_usada: closedate se não atrasado; senão closedate+1m
      (ou hoje+1m se isso ainda estiver no passado).
    ativacao: base + 5 dias úteis.
    """
    atrasado = closedate < hoje
    if atrasado:
        nova = _add_meses(closedate, 1)
        if nova < hoje:
            nova = _add_meses(hoje, 1)
        base = nova
    else:
        base = closedate
    if feriados is None:
        feriados = _feriados_para_periodo(base, base + dt.timedelta(days=20))
    ativacao = _add_dias_uteis(base, config.DIAS_UTEIS_POS_FECHAMENTO, feriados)
    return ativacao, base, atrasado


def dias_atraso(closedate, hoje):
    """Dias de atraso = hoje - closedate (>=0 só faz sentido se atrasado)."""
    if closedate >= hoje:
        return 0
    return (hoje - closedate).days


# ---- Curva e proporcionalidade ------------------------------------------
def _curva(potencial):
    if potencial >= config.LIMITE_POTENCIAL_ALTO:
        return config.CURVA_RAMPAGEM["high"]
    return config.CURVA_RAMPAGEM["low"]


def _fator_proporcional(ativacao):
    dias_no_mes = calendar.monthrange(ativacao.year, ativacao.month)[1]
    dias_ativos = dias_no_mes - ativacao.day + 1
    return dias_ativos / dias_no_mes, dias_ativos, dias_no_mes


def meses_janela(hoje):
    meses = []
    y, m = hoje.year, hoje.month
    for _ in range(config.MESES_JANELA):
        meses.append(dt.date(y, m, 1))
        m += 1
        if m > 12:
            m = 1; y += 1
    return meses


def volume_por_mes(deal, meses, hoje):
    """Calcula volumes + metadados por mês da janela p/ um deal.

    Retorna (volumes, ativacao, base_fechamento, atrasado, detalhes).
      volumes:   {primeiro_dia_do_mes: float}
      detalhes:  {primeiro_dia_do_mes: {texto, rampa_idx, frac, fator}} p/ tooltip.
    """
    detalhes = {m: {"texto": "–", "rampa_idx": None, "frac": 0.0, "fator": None}
                for m in meses}
    volumes = {m: 0.0 for m in meses}

    potencial = deal["potencial"]
    closedate = deal["previsao_fechamento"]
    if not potencial or potencial <= 0 or not closedate:
        return volumes, None, None, False, detalhes

    feriados = _feriados_para_periodo(
        min(closedate, hoje), max(closedate, hoje) + dt.timedelta(days=45))
    ativacao, base, atrasado = data_ativacao(closedate, hoje, feriados)

    curva = _curva(potencial)
    fator_m1, dias_ativos, dias_no_mes = _fator_proporcional(ativacao)
    mes_m1 = dt.date(ativacao.year, ativacao.month, 1)

    if mes_m1 not in volumes:
        # ativação fora da janela -> zerado, mas registra a ativação p/ exibir.
        return volumes, ativacao, base, atrasado, detalhes

    idx_m1 = meses.index(mes_m1)
    for i in range(idx_m1, len(meses)):
        offset = i - idx_m1
        mes = meses[i]
        if offset < len(curva):
            frac = curva[offset]
            if offset == 0:
                vol = potencial * frac * fator_m1
                texto = (f"Mês 1 · 25% de {potencial:,} × {dias_ativos}/{dias_no_mes} "
                         f"(fator {fator_m1:.3f}) = {int(round(vol)):,}")
            else:
                vol = potencial * frac
                nome_mes = {1: "Mês 1", 2: "Mês 2", 3: "Mês 3", 4: "Mês 4"}[offset + 1]
                texto = f"{nome_mes} · {int(frac*100)}% de {potencial:,} = {int(round(vol)):,}"
            volumes[mes] += vol
            detalhes[mes] = {"texto": texto, "rampa_idx": offset, "frac": frac,
                             "fator": fator_m1 if offset == 0 else None}
        else:
            vol = potencial * 1.0
            nome_mes = f"Mês {len(curva)+1}+ (100%)"
            texto = f"{nome_mes} · 100% de {potencial:,} = {int(round(vol)):,}"
            volumes[mes] += vol
            detalhes[mes] = {"texto": texto, "rampa_idx": len(curva), "frac": 1.0,
                             "fator": None}
    return volumes, ativacao, base, atrasado, detalhes


# ---- Ativação (spec D.2) ------------------------------------------------
# Rampa a partir da entrada na Ativação. O deal JÁ está em ativação, então:
#   - início da rampa = closedate (data real de fechamento; proxy da entrada
#     na Ativação, já que hs_date_entered_<id> não é retornável pela API —
#     ver memória forecast-ativacao-stage-discovery).
#   - SEM somar os 5 dias úteis (spec D.2 explicita: "o deal já está em
#     ativação").
# M1 = mês calendário do closedate, volume = potencial × 25% × (dias_ativos/
# dias_no_mês). Mesma curva por potencial total (25/50/[75]/100 + carry).
# Calcula-se a rampa DESDE o closedate, mas só se exibem os 6 meses da janela
# atual (mês atual + 5). Deal que entrou há 3 meses já aparece em 100% hoje.
def volume_por_mes_ativacao(deal, meses, hoje):
    """Calcula volumes + metadados por mês da janela p/ um deal em Ativação.

    Retorna (volumes, entrada, detalhes). entrada = closedate (início da rampa).
    """
    detalhes = {m: {"texto": "–", "rampa_idx": None, "frac": 0.0, "fator": None}
                for m in meses}
    volumes = {m: 0.0 for m in meses}

    potencial = deal["potencial"]
    entrada = deal.get("closedate")   # data real de fechamento
    if not potencial or potencial <= 0 or not entrada:
        return volumes, None, detalhes

    curva = _curva(potencial)
    fator_m1, dias_ativos, dias_no_mes = _fator_proporcional(entrada)
    mes_m1 = dt.date(entrada.year, entrada.month, 1)

    # Se o M1 (mês do closedate) está ANTES da janela, a rampa já começou no
    # passado: descobrir qual offset da curva cai no primeiro mês da janela.
    if mes_m1 not in volumes:
        # calcular quantos meses separam o M1 do início da janela
        delta_meses = (meses[0].year - mes_m1.year) * 12 + (meses[0].month - mes_m1.month)
        if delta_meses < 0:
            # closedate futuro além da janela -> nada a exibir ainda
            return volumes, entrada, detalhes
        idx_m1 = 0
        offset_inicial = delta_meses   # já estamos offset meses adentro da rampa
    else:
        idx_m1 = meses.index(mes_m1)
        offset_inicial = 0

    for i in range(idx_m1, len(meses)):
        offset = offset_inicial + (i - idx_m1)
        mes = meses[i]
        if offset < len(curva):
            frac = curva[offset]
            if offset == 0:
                # M1 cai DENTRO da janela -> proporcional por dia
                vol = potencial * frac * fator_m1
                texto = (f"Mês 1 (entrada) · 25% de {potencial:,} × "
                         f"{dias_ativos}/{dias_no_mes} (fator {fator_m1:.3f}) "
                         f"= {int(round(vol)):,}")
            else:
                vol = potencial * frac
                nome_mes = {1: "Mês 1", 2: "Mês 2", 3: "Mês 3",
                            4: "Mês 4"}.get(offset + 1, f"Mês {offset+1}")
                texto = f"{nome_mes} · {int(frac*100)}% de {potencial:,} = {int(round(vol)):,}"
            volumes[mes] += vol
            detalhes[mes] = {"texto": texto, "rampa_idx": offset, "frac": frac,
                             "fator": fator_m1 if offset == 0 else None}
        else:
            vol = potencial * 1.0
            texto = f"Mês {len(curva)+1}+ (100%) · 100% de {potencial:,} = {int(round(vol)):,}"
            volumes[mes] += vol
            detalhes[mes] = {"texto": texto, "rampa_idx": len(curva),
                             "frac": 1.0, "fator": None}
    return volumes, entrada, detalhes


def dias_em_ativacao(closedate, hoje):
    """Dias decorridos desde a entrada na Ativação (closedate). >=0."""
    if not closedate:
        return None
    return max(0, (hoje - closedate).days)


def calcular_todos(deals, hoje=None):
    """Particiona deals em (negociacao, ativacao, incompletos) e calcula volumes.

    - negociacao: deals nas etapas 4/5/6 (rampa desde a ativação = fechamento+5dúteis).
    - ativacao:   deals na etapa 7 Ativação (rampa desde o closedate, sem +5dúteis).
    - incompletos: faltando potencial ou a data base da sua aba.

    Camada 2 (cálculo) — independente da renderização (spec 4.1).
    Retorna (negociacao, ativacao, incompletos, meses).
    """
    if hoje is None:
        hoje = dt.date.today()
    meses = meses_janela(hoje)

    negociacao, ativacao, incompletos = [], [], []
    for d in deals:
        step = d.get("step")
        eh_ativacao = step == 7
        tem_pot = d["potencial"] is not None and d["potencial"] > 0
        # data base de cada aba: closedate p/ Ativação, previsao p/ Negociação
        tem_data_base = (d.get("closedate") is not None) if eh_ativacao \
            else (d.get("previsao_fechamento") is not None)
        if not (tem_pot and tem_data_base):
            incompletos.append({**d, "ativacao": None, "base_fechamento": None,
                                "atrasado": False, "volumes": {m: 0.0 for m in meses},
                                "detalhes": {}, "total_linha": 0,
                                "origem": "ativacao" if eh_ativacao else "negociacao",
                                "motivo_incompleto": _motivo_incompleto(d, eh_ativacao)})
            continue
        if eh_ativacao:
            vols, entrada, det = volume_por_mes_ativacao(d, meses, hoje)
            total_linha = sum(vols.values())
            ativacao.append({**d, "entrada_ativacao": entrada,
                             "ativacao": None, "base_fechamento": None,
                             "atrasado": False, "volumes": vols, "detalhes": det,
                             "total_linha": total_linha, "origem": "ativacao",
                             "dias_ativacao": dias_em_ativacao(entrada, hoje)})
        else:
            vols, ativ, base, atrasado, det = volume_por_mes(d, meses, hoje)
            total_linha = sum(vols.values())
            negociacao.append({**d, "ativacao": ativ, "base_fechamento": base,
                               "atrasado": atrasado, "volumes": vols, "detalhes": det,
                               "total_linha": total_linha, "origem": "negociacao",
                               "dias_atraso": dias_atraso(d["previsao_fechamento"], hoje) if atrasado else 0})
    return negociacao, ativacao, incompletos, meses


def _motivo_incompleto(d, eh_ativacao=False):
    faltam = []
    if eh_ativacao:
        if not d.get("closedate"):
            faltam.append("data de fechamento (entrada na Ativação)")
    else:
        if not d.get("previsao_fechamento"):
            faltam.append("previsão de fechamento")
    if not (d.get("potencial") and d["potencial"] > 0):
        faltam.append("potencial mês")
    return "Faltando: " + " e ".join(faltam)


# ---- Negociação Potencial atualizado (aba: forecast sobre 15% do potencial) -
# Mesma janela, mesma ativação (fechamento + 5dúteis), mesma proporcionalidade
# de M1 por dia — só a BASE de volume muda: potencial_15 = round(potencial*0.15).
# A curva (corte 20k) é REAVALIADA por potencial_15 (decisão de negócio): um
# deal de 28k (curva 4 meses no original) vira 4.200 (curva 3 meses no 15%).
# O potencial ORIGINAL é preservado em d["potencial"] p/ a coluna "Potencial";
# o valor de 15% fica em d["potencial_15"]; volumes/total_linha são 15%-based.
def calcular_negociacao_15(negociacao, meses, hoje):
    """Variante de Negociação com forecast baseado em 15% do potencial.

    Recebe a lista de negociacao já calculada (camada 2) e devolve uma lista
    paralela, mesmo comprimento e mesma ordem, onde cada deal tem:
      - potencial       = ORIGINAL (p/ coluna "Potencial")
      - potencial_15    = round(potencial * 0.15) (p/ coluna "15% potencial")
      - volumes          = forecast sobre potencial_15
      - total_linha      = soma dos volumes 15%
      - ativacao/base_fechamento/atrasado = recalculados (idênticos ao original,
        pois dependem só de previsao_fechamento + feriados, não do potencial)
    """
    out = []
    for d in negociacao:
        pot_original = d["potencial"] or 0
        pot15 = int(round(pot_original * 0.15))
        # volume_por_mes lê deal["potencial"] + deal["previsao_fechamento"];
        # sobrescrever potencial força a curva/_curva a usar pot15.
        deal_15 = {**d, "potencial": pot15}
        vols, ativ, base, atrasado, det = volume_por_mes(deal_15, meses, hoje)
        total_linha = sum(vols.values())
        out.append({**d,                      # preserva potencial ORIGINAL
                    "potencial_15": pot15,
                    "ativacao": ativ,
                    "base_fechamento": base,
                    "atrasado": atrasado,
                    "volumes": vols,
                    "detalhes": det,
                    "total_linha": total_linha})
    return out


# ---- Teste de sanidade (spec 5.5) ---------------------------------------
def sanity_test_deals(hoje=None):
    """Deals fictícios p/ validar a lógica (não entram nos totais).
    Retorna lista de (descricao, esperado_por_offset, volumes_calculados)."""
    if hoje is None:
        hoje = dt.date.today()
    meses = meses_janela(hoje)

    def calc(potencial, ativacao_dia, ano, mes):
        d = {"potencial": potencial, "closedate": None}
        # forçar ativação direto: construir via data_ativacao não serve; emulo
        # criando um closedate cuja ativação = data alvo. Mais simples: chamar
        # volume_por_mes com closedate = ativacao_alvo e hoje no futuro p/ não
        # ser atrasado. Mas a ativação vira closedate+5dúteis. Em vez disso,
        # teste direto da curva/fator:
        curva = _curva(potencial)
        fator, da, dm = _fator_proporcional(dt.date(ano, mes, ativacao_dia))
        out = []
        for i, frac in enumerate(curva):
            out.append(potencial * frac * (fator if i == 0 else 1.0))
        # carry-forward
        while len(out) < len(meses):
            out.append(potencial * 1.0)
        return curva, fator, out

    results = []
    # Deal 1: 10.000, ativação 16/10/2026 -> out≈1290, nov=5000, dez+=10000
    curva, fator, out = calc(10000, 16, 2026, 10)
    results.append(("10.000 ativação 16/10/2026",
                    {"curva": [0.25, 0.5, 1.0], "fator": 16/31,
                     "m1": 10000*0.25*16/31, "m2": 5000, "m3+": 10000},
                    curva, fator, out))
    # Deal 2: 30.000 -> curva 4 meses 25/50/75/100
    curva2, fator2, out2 = calc(30000, 16, 2026, 10)
    results.append(("30.000 ativação 16/10/2026",
                    {"curva": [0.25, 0.5, 0.75, 1.0], "fator": 16/31,
                     "m1": 30000*0.25*16/31, "m2": 15000, "m3": 22500, "m4+": 30000},
                    curva2, fator2, out2))
    return results


def sanity_test_ativacao(hoje=None):
    """Teste fictício da rampa de Ativação (spec D / verificação 5.9).

    Constrói deals sintéticos e roda volume_por_mes_ativacao sobre a janela
    real (mês atual + 5), validando:
      - Deal que ENTROU agora (closedate = hoje): M1 proporcional por dia.
      - Deal que entrou há 3 meses: já em 100% no mês atual (carry-forward).
      - curva <20k vs ≥20k (3 vs 4 meses até 100%).

    Retorna lista de (descricao, esperado, volumes_calculados_por_mes, ok).
    """
    if hoje is None:
        hoje = dt.date.today()
    meses = meses_janela(hoje)

    def run(potencial, closedate):
        d = {"potencial": potencial, "closedate": closedate, "step": 7,
             "dealname": "fictício"}
        vols, entrada, det = volume_por_mes_ativacao(d, meses, hoje)
        return [vols[m] for m in meses], entrada

    # dias no mês atual p/ o fator do M1
    import calendar
    dm_atual = calendar.monthrange(hoje.year, hoje.month)[1]
    dias_ativos = dm_atual - hoje.day + 1
    fator = dias_ativos / dm_atual

    out = []
    # 1) 10k entrando HOJE (no mês atual) -> M1 = 10000*0.25*fator, M2=5000, M3+=10000
    v, _ = run(10000, hoje)
    esp_m1 = 10000 * 0.25 * fator
    out.append(("10k entrada hoje (mês atual)",
                {"m1": esp_m1, "m2": 5000, "m3": 10000},
                v, abs(v[0] - esp_m1) < 1 and abs(v[1] - 5000) < 1))
    # 2) 10k entrou há 3 meses -> mês atual já em 100% (offset >= 2 => 100%)
    tres_meses_atras = _add_meses(hoje, -3)
    v2, _ = run(10000, tres_meses_atras)
    # no mês atual (offset 3 desde a entrada) curva low=[25,50,100] => 100%
    out.append(("10k entrada há 3 meses (100% hoje)",
                {"m0": 10000}, v2, abs(v2[0] - 10000) < 1))
    # 3) 30k entrando hoje -> curva 4 meses: M1=25%*fator, M2=15000, M3=22500, M4=30000
    v3, _ = run(30000, hoje)
    esp_m1b = 30000 * 0.25 * fator
    out.append(("30k entrada hoje (curva 4 meses)",
                {"m1": esp_m1b, "m2": 15000, "m3": 22500, "m4": 30000},
                v3, abs(v3[0] - esp_m1b) < 1 and abs(v3[1] - 15000) < 1))
    return out


def sanity_test_negociacao_15(hoje=None):
    """Valida a variante Negociação Potencial atualizado (forecast sobre 15%).

    Cenários (deal fictício em Negociação, ativação = hoje + regra 2.1):
      1) 10k original -> pot15=1.500 (<20k, curva 3 meses).
         M1 = 1500*0.25*fator; M2 = 750; M3+ = 1500.
      2) 30k original -> pot15=4.500 (<20k, curva REAVALIADA p/ 3 meses —
         no original seria 4 meses). M1 = 4500*0.25*fator; M2 = 2250; M3+ = 4500.
         Verifica que NÃO há 4ª fração 0.75 (confirmaria a reavaliação).

    Retorna lista de (descricao, esperado, volumes, ok).
    """
    if hoje is None:
        hoje = dt.date.today()
    meses = meses_janela(hoje)
    out = []
    for pot_orig, esp_m2, esp_m3, label in [
        (10000, 750, 1500, "10k -> 1.500 (curva 3m)"),
        (30000, 2250, 4500, "30k -> 4.500 (curva REAVALIADA p/ 3m)"),
    ]:
        pot15 = int(round(pot_orig * 0.15))
        # deal em Negociação: ativação = previsao_fechamento + 5dúteis.
        # Forçamos previsao_fechamento = hoje (não atrasado) p/ ativação cair
        # no mês atual e o M1 ser proporcional.
        d = {"potencial": pot15, "previsao_fechamento": hoje,
             "closedate": None, "dealname": "fictício"}
        vols, ativ, base, atrasado, det = volume_por_mes(d, meses, hoje)
        v = [vols[m] for m in meses]
        # M1 esperado = pot15 * 0.25 * fator_do_dia_da_ativacao. A ativação é
        # hoje+5dúteis; em vez de reproduzir o feriado, comparamos M2 e M3+ que
        # não dependem do fator.
        dm = calendar.monthrange(ativ.year, ativ.month)[1]
        fator = (dm - ativ.day + 1) / dm
        esp_m1 = pot15 * 0.25 * fator
        ok = (abs(v[0] - esp_m1) < 2 and abs(v[1] - esp_m2) < 1
              and abs(v[2] - esp_m3) < 1)
        out.append((label, {"m1": esp_m1, "m2": esp_m2, "m3": esp_m3},
                    v, ok))
    return out
