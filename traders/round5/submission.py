"""Round 5 — "The Final Stretch" — submission scaffold.

R4 products (HYDROGEL/VELVETFRUIT/VEV_*) are NO LONGER tradeable. R5 introduces
50 brand-new products, evenly split across 10 categories of 5. Every product
has a hard position limit of 10. Calibration is the next step — this file is
just the inert scaffold that defines the symbol universe and returns no
orders, so the harness can load it without errors.
"""

try:
    from datamodel import Order, OrderDepth, TradingState
except ImportError:
    from backtester.datamodel import Order, OrderDepth, TradingState

from typing import Dict, List


# ---------------------------------------------------------------------------
# 10 categories x 5 products = 50 symbols. Position limit is 10 for every one.
# ---------------------------------------------------------------------------
GALAXY_SOUNDS: tuple = (
    "GALAXY_SOUNDS_DARK_MATTER",
    "GALAXY_SOUNDS_BLACK_HOLES",
    "GALAXY_SOUNDS_PLANETARY_RINGS",
    "GALAXY_SOUNDS_SOLAR_WINDS",
    "GALAXY_SOUNDS_SOLAR_FLAMES",
)

SLEEP_PODS: tuple = (
    "SLEEP_POD_SUEDE",
    "SLEEP_POD_LAMB_WOOL",
    "SLEEP_POD_POLYESTER",
    "SLEEP_POD_NYLON",
    "SLEEP_POD_COTTON",
)

MICROCHIPS: tuple = (
    "MICROCHIP_CIRCLE",
    "MICROCHIP_OVAL",
    "MICROCHIP_SQUARE",
    "MICROCHIP_RECTANGLE",
    "MICROCHIP_TRIANGLE",
)

PEBBLES: tuple = (
    "PEBBLES_XS",
    "PEBBLES_S",
    "PEBBLES_M",
    "PEBBLES_L",
    "PEBBLES_XL",
)

ROBOTS: tuple = (
    "ROBOT_VACUUMING",
    "ROBOT_MOPPING",
    "ROBOT_DISHES",
    "ROBOT_LAUNDRY",
    "ROBOT_IRONING",
)

UV_VISORS: tuple = (
    "UV_VISOR_YELLOW",
    "UV_VISOR_AMBER",
    "UV_VISOR_ORANGE",
    "UV_VISOR_RED",
    "UV_VISOR_MAGENTA",
)

TRANSLATORS: tuple = (
    "TRANSLATOR_SPACE_GRAY",
    "TRANSLATOR_ASTRO_BLACK",
    "TRANSLATOR_ECLIPSE_CHARCOAL",
    "TRANSLATOR_GRAPHITE_MIST",
    "TRANSLATOR_VOID_BLUE",
)

PANELS: tuple = (
    "PANEL_1X2",
    "PANEL_2X2",
    "PANEL_1X4",
    "PANEL_2X4",
    "PANEL_4X4",
)

OXYGEN_SHAKES: tuple = (
    "OXYGEN_SHAKE_MORNING_BREATH",
    "OXYGEN_SHAKE_EVENING_BREATH",
    "OXYGEN_SHAKE_MINT",
    "OXYGEN_SHAKE_CHOCOLATE",
    "OXYGEN_SHAKE_GARLIC",
)

SNACKPACKS: tuple = (
    "SNACKPACK_CHOCOLATE",
    "SNACKPACK_VANILLA",
    "SNACKPACK_PISTACHIO",
    "SNACKPACK_STRAWBERRY",
    "SNACKPACK_RASPBERRY",
)

CATEGORIES: Dict[str, tuple] = {
    "galaxy_sounds": GALAXY_SOUNDS,
    "sleep_pods": SLEEP_PODS,
    "microchips": MICROCHIPS,
    "pebbles": PEBBLES,
    "robots": ROBOTS,
    "uv_visors": UV_VISORS,
    "translators": TRANSLATORS,
    "panels": PANELS,
    "oxygen_shakes": OXYGEN_SHAKES,
    "snackpacks": SNACKPACKS,
}

ALL_PRODUCTS: tuple = tuple(p for group in CATEGORIES.values() for p in group)
assert len(ALL_PRODUCTS) == 50, f"expected 50 products, got {len(ALL_PRODUCTS)}"

POSITION_LIMIT = 10
LIMITS: Dict[str, int] = {p: POSITION_LIMIT for p in ALL_PRODUCTS}


class Trader:
    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {p: [] for p in state.order_depths}
        return result, 0, ""
