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
    closedate = deal["closedate"]
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


def calcular_todos(deals, hoje=None):
    """Particiona completos/incompletos e calcula volumes + metadados.

    Camada 2 (cálculo) — independente da renderização (spec 4.1).
    """
    if hoje is None:
        hoje = dt.date.today()
    meses = meses_janela(hoje)

    completos, incompletos = [], []
    for d in deals:
        tem_pot = d["potencial"] is not None and d["potencial"] > 0
        tem_close = d["closedate"] is not None
        if not (tem_pot and tem_close):
            incompletos.append({**d, "ativacao": None, "base_fechamento": None,
                                "atrasado": False, "volumes": {m: 0.0 for m in meses},
                                "detalhes": {}, "total_linha": 0,
                                "motivo_incompleto": _motivo_incompleto(d)})
            continue
        vols, ativ, base, atrasado, det = volume_por_mes(d, meses, hoje)
        total_linha = sum(vols.values())
        completos.append({**d, "ativacao": ativ, "base_fechamento": base,
                          "atrasado": atrasado, "volumes": vols, "detalhes": det,
                          "total_linha": total_linha,
                          "dias_atraso": dias_atraso(d["closedate"], hoje) if atrasado else 0})
    return completos, incompletos, meses


def _motivo_incompleto(d):
    faltam = []
    if not d.get("closedate"):
        faltam.append("previsão de fechamento")
    if not (d.get("potencial") and d["potencial"] > 0):
        faltam.append("potencial mês")
    return "Faltando: " + " e ".join(faltam)


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
