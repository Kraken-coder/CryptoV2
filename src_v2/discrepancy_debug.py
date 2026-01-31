from main import get_total_usdt_capital
from binance.client import Client
from trading_functions import TradingFunctions
from env import demo_futures_api, demo_futures_secret, test_net
client = Client(demo_futures_api, demo_futures_secret, testnet=test_net)
trading = TradingFunctions(client)
print(f"Total USDT Capital: {get_total_usdt_capital(trading)}")
deployable_capital = get_total_usdt_capital(trading) * 0.90 
print(f"Deployable USDT Capital (90%): {deployable_capital}")