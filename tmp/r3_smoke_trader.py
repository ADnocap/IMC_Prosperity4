"""Trivial trader that declares all R3 products so the sim activates them.
   Posts no orders — just confirms the simulator loads each asset cleanly."""
try:
    from datamodel import Order, TradingState
except ImportError:
    from prosperity3bt.datamodel import Order, TradingState

# Each NAME = "..." line is detected by rust_simulator/src/detect.rs.
NAME_HYDROGEL = "HYDROGEL_PACK"
NAME_VELVETFRUIT = "VELVETFRUIT_EXTRACT"
NAME_VEV_4000 = "VEV_4000"
NAME_VEV_4500 = "VEV_4500"
NAME_VEV_5000 = "VEV_5000"
NAME_VEV_5100 = "VEV_5100"
NAME_VEV_5200 = "VEV_5200"
NAME_VEV_5300 = "VEV_5300"
NAME_VEV_5400 = "VEV_5400"
NAME_VEV_5500 = "VEV_5500"
NAME_VEV_6000 = "VEV_6000"
NAME_VEV_6500 = "VEV_6500"

class Trader:
    def run(self, state: TradingState):
        return {}, 0, ""
