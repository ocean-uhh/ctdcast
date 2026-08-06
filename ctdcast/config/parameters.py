"""Static plotting parameters: colour palettes, colormaps, slot widths.

Compile-time constants only — the runtime-mutable display globals (GEBCO_PATH,
CLEAN_SPINES, figsizes, map bounds) stay in :mod:`ctdcast.plotters.plots`.
"""

from __future__ import annotations

# Central color registry.
# Physics (CT/SA/σ₀/U/V/N²/Turner): Okabe-Ito palette — Bang Wong, Nature Methods 8:441 (2011).
# Biogeochemistry (O₂/fluorescence/turbidity): Paul Tol palette — https://jrnold.github.io/ggthemes/reference/ptol_pal.html
VAR_COLORS: dict[str, str] = {
    "CT": "#56B4E9",  # sky blue       — Okabe-Ito
    "SA": "#E69F00",  # orange         — Okabe-Ito
    "sigma0": "#009E73",  # bluish green   — Okabe-Ito
    "U": "#D55E00",  # vermillion     — Okabe-Ito
    "V": "#0072B2",  # blue           — Okabe-Ito
    "oxygen_1": "#332288",  # indigo         — Paul Tol
    "fluorescence": "#117733",  # forest green   — Paul Tol
    "turbidity": "#661100",  # dark red       — Paul Tol
    "N2": "#000000",  # black
    "Turner": "#000000",  # black
}
# ColorBrewer colormaps per variable (for pcolormesh / scatter).
_VAR_CMAPS: dict[str, str] = {
    "CT": "RdYlBu_r",
    "temperature_1": "RdYlBu_r",
    "SA": "YlGnBu_r",
    "salinity_1": "YlGnBu_r",
    "oxygen_1": "RdYlGn",
    "AOU": "RdBu_r",  # blue = near saturation, red = depleted
    "fluorescence": "YlGn",
    "turbidity": "YlOrBr",
    "sigma0": "Purples",
}
# Slot widths in inches at savefig.dpi=150 (body usable width = 1086px).
# PNGs are intentionally wider than the slot (1350px vs 1086px at full width) so that
# at 10pt labels, displayed font size (~17px) matches the pre-refactor appearance.
# The browser downscales by ~0.80, giving crisp subpixel rendering.
_W_FULL: float = 9.0  # 1350px PNG → 1086px display
_W_TWOTHIRDS: float = 6.0  # 900px PNG  → 719px display
_W_THREE_FIFTHS: float = 5.4  # 810px PNG  → 652px display (60% slot)
_W_HALF: float = 4.5  # 675px PNG  → 543px display
_W_TWO_FIFTHS: float = 3.6  # 540px PNG  → 434px display (40% slot)
_W_THIRD: float = 3.0  # 450px PNG  → 361px display
# Section aspect-ratio scaling.
# Calibrated so KTout (416 dbar, 94 km) renders at 2.5 in tall at _W_FULL = 9.0 in.
# (Equivalent to Eleanor's stretch=12.8 at 7.2 in width; scaled proportionally.)
_SECTION_STRETCH: float = 16.0
_MAX_SECTION_H: float = 5.2  # height cap; tall/narrow sections get narrower fig_w
