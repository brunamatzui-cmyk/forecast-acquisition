# -*- coding: utf-8 -*-
"""Cálculo do forecast de corridas por mês.

Regras (ver spec em CLAUDE.md do usuário):
  - Ativação = fechamento + 5 dias úteis (ignora sáb/dom e feriados nacionais BR).
  - Mês 1 da rampa = mês calendário da ativação, com volume proporcional aos
    dias ativos: fator = (dias corridos a partir da ativação, inclusive) /
    (total de dias do mês). Volume M1 = potencial × 25% × fator.
  - Meses seguintes são meses calendário completos, seguindo a curva:
      potencial < 20.000:  [25%, 50%, 100%]   (100% a partir do mês 3)
      potencial >= 20.000: [25%, 50%, 75%, 100%] (100% a partir do mês 4)
  - Janela: 6 meses a partir do mês atual (inclusive). Meses anteriores ao
    Mês 1 ficam zerados; ativação fora da janela -> todos zerados.
  - Probabilidade: 100% (não ponderar por etapa).
"""
import calendar
import datetime as dt

import config

# Feriados nacionais brasileiros (fixos + móveis) para os anos relevantes.
# Feriados fixos: 01/01, 21/04, 01/05, 07/09, 12/10, 02/11, 15/11, 25/12.
# Feriados móveis: Carnaval (seg/ter), Sexta-feira Santa, Corpus Christi.
def _carnaval(ano):
    """Terça de Carnaval (e segunda) via Páscoa (Meeus/Jones/Butcher)."""
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
    # Carnaval = 47 dias antes da Páscoa (terça); segunda = 48 antes
    terca = pascoa - dt.timedelta(days=47)
    segunda = pascoa - dt.timedelta(days=48)
    sexta_santa = pascoa - dt.timedelta(days=2)
    corpus = pascoa + dt.timedelta(days=60)
    return [segunda, terca, sexta_santa, corpus]


def _feriados_nacionais(ano):
    fixos = [
        dt.date(ano, 1, 1),    # Confraternização Universal
        dt.date(ano, 4, 21),   # Tiradentes
        dt.date(ano, 5, 1),    # Dia do Trabalho
        dt.date(ano, 9, 7),    # Independência
        dt.date(ano, 10, 12),  # Nossa Senhora Aparecida
        dt.date(ano, 11, 2),   # Finados
        dt.date(ano, 11, 15),  # Proclamação da República
        dt.date(ano, 12, 25),  # Natal
    ]
    return set(fixos + _carnaval(ano))


def _feriados_para_periodo(start, end):
    """Conjunto de feriados nacionais cobrindo [start, end] (inclusive)."""
    feriados = set()
    for ano in range(start.year, end.year + 1):
        feriados |= _feriados_nacionais(ano)
    return feriados


def _add_dias_uteis(data, n, feriados):
    """Soma n dias úteis a `data` (date). Conta a partir do dia seguinte."""
    cur = data
    added = 0
    while added < n:
        cur = cur + dt.timedelta(days=1)
        if cur.weekday() < 5 and cur not in feriados:  # seg-sex e não feriado
            added += 1
    return cur


def data_ativacao(closedate, hoje, feriados=None):
    """Data de ativação = closedate + 5 dias úteis. Se closedate no passado
    (deal atrasado), usa `hoje` como base (regra de exceção da spec)."""
    base = closedate
    if closedate < hoje:
        base = hoje
    if feriados is None:
        feriados = _feriados_para_periodo(base, base + dt.timedelta(days=20))
    return _add_dias_uteis(base, config.DIAS_UTEIS_POS_FECHAMENTO, feriados)


def _curva(potencial):
    """Lista de frações do potencial por mês da rampa (Mês 1 em diante)."""
    if potencial >= config.LIMITE_POTENCIAL_ALTO:
        return config.CURVA_RAMPAGEM["high"]
    return config.CURVA_RAMPAGEM["low"]


def _fator_proporcional(ativacao):
    """Fator do Mês 1 = dias ativos (da ativação inclusive até fim do mês) /
    total de dias do mês. Ex: ativação 16/10 (31 dias) -> 16/31."""
    dias_no_mes = calendar.monthrange(ativacao.year, ativacao.month)[1]
    dias_ativos = dias_no_mes - ativacao.day + 1
    return dias_ativos / dias_no_mes


def meses_janela(hoje):
    """Lista dos 6 meses (date do 1º dia) a partir do mês atual inclusive."""
    meses = []
    y, m = hoje.year, hoje.month
    for _ in range(config.MESES_JANELA):
        meses.append(dt.date(y, m, 1))
        m += 1
        if m > 12:
            m = 1; y += 1
    return meses


def volume_por_mes(deal, meses, hoje):
    """Calcula volume previsto por mês da janela para um deal.

    Retorna dict {primeiro_dia_do_mes: volume_int} e a data de ativação.
    Deal sem potencial/closedate não deveria chegar aqui (filtrado antes).
    """
    potencial = deal["potencial"]
    if not potencial or potencial <= 0:
        return {m: 0 for m in meses}, None
    closedate = deal["closedate"]
    if not closedate:
        return {m: 0 for m in meses}, None

    feriados = _feriados_para_periodo(
        min(closedate, hoje),
        max(closedate, hoje) + dt.timedelta(days=30),
    )
    ativacao = data_ativacao(closedate, hoje, feriados)

    curva = _curva(potencial)
    fator_m1 = _fator_proporcional(ativacao)

    # Mês calendário da ativação = Mês 1 da rampa.
    mes_m1 = dt.date(ativacao.year, ativacao.month, 1)

    volumes = {m: 0 for m in meses}
    if mes_m1 not in volumes:
        # Ativação cai fora da janela -> todos zerados (deal aparece zerado).
        return volumes, ativacao

    # Preenche todos os meses da janela a partir de M1:
    #  - meses dentro da curva: potencial × fração da curva (M1 com fator)
    #  - meses após o fim da curva (100% atingido): potencial × 100%
    idx_m1 = meses.index(mes_m1)
    for i in range(idx_m1, len(meses)):
        offset = i - idx_m1
        if offset < len(curva):
            frac = curva[offset]
            vol = potencial * frac * (fator_m1 if offset == 0 else 1.0)
        else:
            vol = potencial * 1.0  # permanece em 100% após atingir o teto
        volumes[meses[i]] += vol
    return volumes, ativacao


def calcular_todos(deals, hoje=None):
    """Para cada deal, computa ativação e volumes mensais.

    Retorna:
      completos:   deals com closedate E potencial, com volumes calculados.
      incompletos: deals sem closedate ou potencial (lista separada).
      meses:       lista de dates (1º dia) da janela de 6 meses.
    """
    if hoje is None:
        hoje = dt.date.today()
    meses = meses_janela(hoje)

    completos, incompletos = [], []
    for d in deals:
        tem_pot = d["potencial"] is not None and d["potencial"] > 0
        tem_close = d["closedate"] is not None
        if not (tem_pot and tem_close):
            incompletos.append({**d, "ativacao": None, "volumes": {m: 0 for m in meses},
                                "motivo_incompleto": _motivo_incompleto(d)})
            continue
        vols, ativ = volume_por_mes(d, meses, hoje)
        total_linha = sum(vols.values())
        completos.append({**d, "ativacao": ativ, "volumes": vols,
                          "total_linha": total_linha})
    return completos, incompletos, meses


def _motivo_incompleto(d):
    faltam = []
    if not d.get("closedate"):
        faltam.append("previsão de fechamento")
    if not (d.get("potencial") and d["potencial"] > 0):
        faltam.append("potencial mês")
    return "Faltando: " + " e ".join(faltam)
