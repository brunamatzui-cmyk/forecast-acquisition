# -*- coding: utf-8 -*-
"""Paleta de cores validada pelo skill dataviz (6 checks, CVD-safe).

Cores por PIPELINE (categorical, 3 slots): azul / verde-azulado / laranja.
O usuário pediu azul/verde/laranja, mas verde-floresta puro (#008300) colide
com laranja sob protanopia (ΔE 3.2 = FAIL duro). Snap-to-passing: trocado
por verde-azulado #1baf7a (mesma família verde, slot 5 do default) — assim
passa TODOS os checks (worst adjacent ΔE 9.2 light / 9.4 dark). Identidade
de pipeline também carregada por etiqueta de texto + barra lateral, nunca
só pela cor.

STAGES 4/5/6 (ordinal, rampa de VIOLETA — família de cor DIFERENTE dos
pipelines p/ não confundir, como pede a spec 3.5): 3 passos claros→escuros.

HEATMAP (sequential, rampa azul 100→700 do palette.md): intensidade da
célula proporcional ao volume. Valores zerados = "–" em cinza claro.

ATRASADO (status critical): #d03b3b + etiqueta "Atrasado" + ícone —
nunca cor sozinha (regra de status).

Validação rodada em 2026-10-01 via validate_palette.js (light + dark).
Revalidar se trocar uma cor.
"""
# ---- Pipelines (categorical) ----
PIPELINE_COLORS_LIGHT = {
    "B2B Outbound":       "#2a78d6",   # azul (slot 1)
    "B2B Website Table":  "#1baf7a",   # verde-azulado (slot 5; verde puro colide c/ laranja)
    "B2B CSM Acquisition": "#eb6834",  # laranja (slot 6)
}
PIPELINE_COLORS_DARK = {
    "B2B Outbound":       "#3987e5",
    "B2B Website Table":  "#199e70",
    "B2B CSM Acquisition": "#d95926",
}

# Etiqueta curta de pipeline (dentro da coluna do nome do negócio, spec 3.1/3.4)
PIPELINE_SHORT = {
    "B2B Outbound": "OUT",
    "B2B Website Table": "WEB",
    "B2B CSM Acquisition": "CSM",
}

# ---- Stages 4/5/6 (ordinal, violeta — diferente dos pipelines) ----
# step -> (light, dark); mais escuro quanto mais avançado.
STAGE_COLORS_LIGHT = {4: "#9085e9", 5: "#4a3aa7", 6: "#312a7a"}
STAGE_COLORS_DARK  = {4: "#b3aaef", 5: "#9085e9", 6: "#6a5cd6"}

# ---- Heatmap (sequential azul 100->700, do palette.md) ----
# step 100 (quase zero/superfície) ... 700 (máximo). Zerado => "–".
HEATMAP_RAMP = [
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec",
    "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab",
    "#184f95", "#104281", "#0d366b",
]
HEATMAP_ZERO = "#898781"   # cinza do "–"

# ---- Status (atrasado) ----
ATRASADO_LIGHT = "#d03b3b"
ATRASADO_DARK  = "#e66767"
ATRASADO_BG_LIGHT = "rgba(208,59,59,0.10)"   # fundo avermelhado suave na célula

# ---- Chrome / ink ----
INK = {"light": "#0b0b0b", "dark": "#ffffff"}
INK_SECONDARY = {"light": "#52514e", "dark": "#c3c2b7"}
INK_MUTED = {"light": "#898781", "dark": "#898781"}
SURFACE = {"light": "#fcfcfb", "dark": "#1a1a19"}
PAGE = {"light": "#f9f9f7", "dark": "#0d0d0d"}
GRIDLINE = {"light": "#e1e0d9", "dark": "#2c2c2a"}
TOTAL_BG = {"light": "#e1e0d9", "dark": "#2c2c2a"}   # fundo da linha/coluna TOTAL (leve destaque)


def pipeline_color(label, dark=False):
    tbl = PIPELINE_COLORS_DARK if dark else PIPELINE_COLORS_LIGHT
    return tbl.get(label, INK_MUTED["dark" if dark else "light"])


def stage_color(step, dark=False):
    tbl = STAGE_COLORS_DARK if dark else STAGE_COLORS_LIGHT
    return tbl.get(step, INK_MUTED["dark" if dark else "light"])


def heatmap_color(frac, dark=False):
    """frac in [0,1] -> hex da rampa azul. frac<=0 -> cinza do zero.
    (dark: reusa a mesma rampa; superfície escura faz a luz recuar naturalmente.)"""
    if frac is None or frac <= 0:
        return HEATMAP_ZERO
    idx = min(len(HEATMAP_RAMP) - 1, max(0, int(round(frac * (len(HEATMAP_RAMP) - 1)))))
    return HEATMAP_RAMP[idx]


def owner_display_name(full_name):
    """'Maria Aparecida da Silva Souza' -> 'Maria Souza'.
    Primeiro nome + último sobrenome. Ignora partículas da/de/dos/do/das."""
    if not full_name or full_name == "(sem proprietário)":
        return full_name or "–"
    parts = [p for p in str(full_name).split() if p]
    if not parts:
        return "–"
    if len(parts) == 1:
        return parts[0]
    primeiro = parts[0]
    # último sobrenome = última palavra que não é partícula minúscula
    particulas = {"da", "de", "do", "das", "dos", "e"}
    ultimo = parts[-1]
    i = len(parts) - 1
    while i > 1 and parts[i].lower() in particulas:
        i -= 1
        ultimo = parts[i]
    return f"{primeiro} {ultimo}"
