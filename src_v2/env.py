import os
from pathlib import Path
from dotenv import load_dotenv

# Calculate path to the .env file (one level up from this file)
env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

api_key = os.getenv("api_key")
secret_key = os.getenv("secret_key")
demo_futures_api = os.getenv("demo_futures_api")
demo_futures_secret = os.getenv("demo_futures_secret")

test_net = os.getenv("test_net", "True").lower() == "true"

max_open_positions = int(os.getenv("MAX_OPEN_POSITIONS", 1))

# Band Config
# TP Mode
tp_mode = os.getenv("TP_MODE", "ATR").upper()

band1_lower = float(os.getenv("BAND1_LOWER", 0.3))
band1_upper = float(os.getenv("BAND1_UPPER", 0.4))
leverage_band1 = int(os.getenv("LEVERAGE_BAND1", 5))
tp_band1_atr = float(os.getenv("TP_BAND1_ATR", 0.3))
tp_band1_pnl = float(os.getenv("TP_BAND1_PNL", 0.15))

band2_lower = float(os.getenv("BAND2_LOWER", 0.4))
band2_upper = float(os.getenv("BAND2_UPPER", 0.6))
leverage_band2 = int(os.getenv("LEVERAGE_BAND2", 7))
tp_band2_atr = float(os.getenv("TP_BAND2_ATR", 0.5))
tp_band2_pnl = float(os.getenv("TP_BAND2_PNL", 0.25))

band3_lower = float(os.getenv("BAND3_LOWER", 0.6))
band3_upper = float(os.getenv("BAND3_UPPER", 1.0))
leverage_band3 = int(os.getenv("LEVERAGE_BAND3", 10))
tp_band3_ladder = (
    float(os.getenv("TP_BAND3_LADDER_1", 0.6)),
    float(os.getenv("TP_BAND3_LADDER_2", 1.2)),
    float(os.getenv("TP_BAND3_LADDER_3", 2.4))
)
tp_band3_pnl_ladder = (
    float(os.getenv("TP_BAND3_PNL_LADDER_1", 0.30)),
    float(os.getenv("TP_BAND3_PNL_LADDER_2", 0.60)),
    float(os.getenv("TP_BAND3_PNL_LADDER_3", 1.00))
)

band4_lower = float(os.getenv("BAND4_LOWER", 1.0))
leverage_band4 = int(os.getenv("LEVERAGE_BAND4", 12))
tp_band4_ladder = (
    float(os.getenv("TP_BAND4_LADDER_1", 0.8)),
    float(os.getenv("TP_BAND4_LADDER_2", 1.5)),
    float(os.getenv("TP_BAND4_LADDER_3", 3.0))
)
tp_band4_pnl_ladder = (
    float(os.getenv("TP_BAND4_PNL_LADDER_1", 0.40)),
    float(os.getenv("TP_BAND4_PNL_LADDER_2", 0.80)),
    float(os.getenv("TP_BAND4_PNL_LADDER_3", 1.50))
)

# Penalties
positive_edge_penalty = float(os.getenv("POSITIVE_EDGE_PENALTY", 0.0))
negative_edge_penalty = float(os.getenv("NEGATIVE_EDGE_PENALTY", 0.0))

# Legacy variables (kept for compatibility)
edge_threshold_small = band1_lower
sl_atr_multiplier = float(os.getenv("sl_atr_multiplier", 0.5))

# Funding Rate Threshold
max_funding_rate_threshold = float(os.getenv("max_funding_rate_threshold", 0.04))
