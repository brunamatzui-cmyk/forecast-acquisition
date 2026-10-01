---
description: Atualiza o Dashboard de Forecast de Aquisição (busca HubSpot local + push pro Streamlit Cloud)
---

Gatilho: `/forecast` (texto depois é ignorado).

Dashboard: **Forecast de Aquisição** — deals nas etapas 4/5/6 dos
pipelines B2B Outbound, Website Table e CSM Acquisition que ainda NÃO
assinaram contrato. Previsão de volume de corridas por mês (6 meses, com
rampagem).

- **Repo (público):** https://github.com/brunamatzui-cmyk/forecast-acquisition
- **Site (Streamlit Cloud):** https://forecast-acquisition.streamlit.app
- **Código:** `G:/Drives compartilhados/B2B Planning (Sales Ops & Intelligence)/4. Planning/Marina/Rampagem/dash forecast acquisition/`
- **Token:** `HUBSPOT_TOKEN` (Private App do HubSpot). **NUNCA** no
  código-fonte nem neste arquivo de comando — é um drive compartilhado e o
  token ficaria exposto (ver aviso de segurança no `README.md` do dash e em
  `ONBOARDING.md` do funnel automation). Obter de uma destas formas ao
  executar:
  1. já estar na env (`$HUBSPOT_TOKEN`); ou
  2. o usuário informa na hora → setar só na shell desta execução
     (`export HUBSPOT_TOKEN="<token informado>"`), nunca gravar em arquivo.
- **Estrutura:** `app.py` (Streamlit) · `fetch_hubspot.py` (Search API +
  Owners) · `calc_forecast.py` (ativação/rampagem/janela) · `config.py`
  (IDs descobertos + regras) · `README.md` (decisões e porquês).

Importante — como o site se atualiza:
- O app no Cloud já busca dados **frescos do HubSpot ao vivo** a cada 15 min
  (cache) + botão 🔄 na sidebar. Então **o dado em si não precisa de
  comando** — ao abrir o site ele já é o mais recente.
- `/forecast` é pra quando você quer (a) validar localmente antes de
  publicar, ou (b) empurrar uma **mudança de código/lógica** (curva de
  rampagem, novo pipeline, filtro novo) pro Cloud, que redeploya sozinho.

## Rotina (nessa ordem)

1. **`cd` no diretório do dashboard** e garantir `HUBSPOT_TOKEN` no env.
   Se não estiver setado, pedir ao usuário e setar só na shell corrente
   (nunca escrever em arquivo). Confirmar com `echo ${HUBSPOT_TOKEN:+set}`.

2. **Rodar a checagem de cálculo** com deals reais (valida que o fetch +
   cálculo continuam corretos sem precisar subir o browser):
   ```
   PYTHONUTF8=1 python test_calc.py
   ```
   Confirmar: 0 exceções, janela de 6 meses correta (mês atual inclusive),
   totais por mês coerentes, deals incompletos separados. Se houver
   anomalia, NÃO empurrar — reportar ao usuário e resolver primeiro.

3. **Se mudou código** (etapa 2 é só leitura; só prosseguir se editou algo):
   - Varredura anti-vazamento **antes de qualquer commit**:
     ```
     git grep -n "pat-na1" -- . ; git grep -n "eca15f1b" -- .
     ```
     Nenhum match nos arquivos versionados (o token vai só no secret do
     Cloud). Se aparecer, NÃO commitar — remover primeiro.
   - `git add -A && git commit -m "<msg>"` (mensagem descritiva + rodapé
     `Co-Authored-By: Claude <noreply@anthropic.com>`).
   - `git pull --rebase origin main && git push origin main` (rebase porque
     o Cloud às vezes empurra `.devcontainer/` sozinho e gera non-fast-forward).
   - O Streamlit Cloud detecta o push e **redeploya em ~1 min**.

4. **Reportar ao usuário** (não repetir a rotina inteira, só o resultado):
   - Quantos deals no forecast / quantos incompletos (do `test_calc.py`).
   - Se houve push: o que mudou no código + confirmação de que o Cloud vai
     redeployar (e a URL pública https://forecast-acquisition.streamlit.app).
   - Se não houve push: dizer que o site já está com dados frescos ao vivo
     e nada precisava ser empurrado.

## Quando NÃO rodar `/forecast`

- Só quer ver o dado atualizado → **abra o site** direto (ele busca ao
  vivo); ou rode `streamlit run app.py` localmente.
- Mudou só o token do HubSpot → troque no **Secret Manager do Cloud**
  (Manage app → Settings → Secrets), NÃO no código. `/forecast` não faz isso.

## Convenções fixas (não redecidir)

- IDs dos pipelines/stages e a propriedade de potencial
  (`share_vs_potencial_total`) foram **descobertos pelo label** via
  `discover_schema.py` — não assumir. Se um pipeline for recriado/etapa
  renomeada no HubSpot, rodar `discover_schema.py` e atualizar `config.py`.
- Ativação = fechamento + 5 dias úteis (feriados nacionais BR, incluindo
  móveis). Curva: potencial <20k → 25/50/100; ≥20k → 25/50/75/100;
  carry-forward 100% após teto. M1 proporcional por dia. Janela 6 meses
  a partir do mês atual. Probabilidade 100% (não pondera etapa).
- Escopo: SOMENTE etapas 4/5/6 (ainda não assinaram). Clientes que já
  assinaram (etapa 7+) são outro escopo — não incluir aqui.
