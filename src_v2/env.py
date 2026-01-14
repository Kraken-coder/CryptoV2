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

leverage_large_edge = int(os.getenv("leverage_large_edge", 8))
leverage_small_edge = int(os.getenv("leverage_small_edge", 4))
stop_loss_large_edge = float(os.getenv("stop_loss_large_edge", 0.0025))
stop_loss_small_edge = float(os.getenv("stop_loss_small_edge", 0.0015))