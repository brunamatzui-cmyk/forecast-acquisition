# Dashboard de Forecast de Aquisição

Tabela com o forecast de volume de corridas por mês (próximos 6 meses) dos
clientes em negociação que **ainda não assinaram contrato** — deals nas
etapas **4 (Solução), 5 (Negociação) e 6 (Fechamento)** dos pipelines B2B
Outbound, B2B Website Table e B2B CSM Acquisition. Fonte: HubSpot.

## Rodar

```bash
export HUBSPOT_TOKEN="<seu Private App token>"   # env var, nunca no fonte
streamlit run app.py
```

Abre em `http://localhost:8501`. Os dados ficam em cache 15 min; botão
**🔄 Atualizar dados agora** na sidebar força uma busca nova.

## Arquivos

| Arquivo | Papel |
|---|---|
| `app.py` | App Streamlit: tabela, filtros, totais, formatação BR. |
| `fetch_hubspot.py` | Search API (paginação) dos stages 4/5/6 dos 3 pipelines + Owners API. |
| `calc_forecast.py` | Ativação (+5 dias úteis), proporcionalidade M1, curva de rampagem, janela 6 meses. |
| `config.py` | IDs descobertos, propriedade de potencial, regras de cálculo. |
| `discover_schema.py` | Descoberta dinâmica de pipelines/stages/propriedades pelo label (não assume IDs). |
| `probe_potencial.py` | Probe que confirmou qual propriedade é o potencial absoluto de corridas. |
| `test_calc.py` | Validação do cálculo com deals reais. |

## Decisões confirmadas (2026-10-01)

### Propriedade de potencial: `share_vs_potencial_total`
Label exato **"Potencial Mês (Total)"** (casamento com a spec). Apesar do
nome técnico estranho ("share"), o `probe_potencial.py` confirmou que é um
**número absoluto de corridas**, não uma razão: em todos os deals é `>=`
que `potencial_mes_99` (faz sentido: total ≥ mês específico), e é o campo
mais populado. Valores vêm como string e podem ter separador de milhar BR
(`"16.000"` = 16000) — tratado em `_parse_potencial`.

### Pipelines (3 ativos)
- B2B Outbound (`890800903`), B2B Website Table (`917378965`), B2B CSM
  Acquisition (`927024659`). O pipeline `[INATIVO] B2B OUTBOUND` apareceu na
  busca por coincidência de regex mas foi excluído (marcado inativo no nome).

### Regras de cálculo (ver spec do usuário)
- **Ativação** = previsão de fechamento + 5 dias úteis (ignora sáb/dom e
  feriados nacionais BR, incluindo móveis: Carnaval, Sexta-feira Santa,
  Corpus Christi). Deal atrasado (fechamento no passado) → usa a data de
  hoje como base, sinalizado com 🔴.
- **Mês 1** = mês calendário da ativação, volume proporcional aos dias
  ativos: `potencial × 25% × (dias_ativos / dias_no_mês)`.
- **Curva**: potencial < 20.000 → 25%/50%/100% (teto no mês 3); ≥ 20.000 →
  25%/50%/75%/100% (teto no mês 4). Após atingir 100%, permanece em 100% nos
  meses seguintes da janela.
- **Janela**: 6 meses a partir do mês atual (inclusive). Meses anteriores ao
  M1 e ativações fora da janela → zerados (deal aparece na tabela).
- **Probabilidade**: 100% (não pondera por etapa — todos os deals 4/5/6
  considerados como que fecharão).

### Exceções
- Deal sem `closedate` ou sem potencial → seção **"Deals com dados
  incompletos"**, fora dos totais, com motivo.
- Dado ausente → exibido como `–`.

## Segurança
O token do HubSpot está exposto nos `extract_*.py` do escopo Funnel Data
Pipeline (pasta pai do funnel automation) — ver `ONBOARDING.md` lá. Este
dashboard segue o padrão migrado em 2026-09-10: token via **env var
`HUBSPOT_TOKEN`** (ou secret do Streamlit Cloud), **nunca hardcoded**.
Qualquer pessoa com acesso à pasta compartilhada pode ver o token hardcoded
nos scripts antigos — trate como credencial comprometida se houver risco.
