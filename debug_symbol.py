from binance.client import Client
from env import demo_futures_api, demo_futures_secret, test_net
import json

client = Client(demo_futures_api, demo_futures_secret, testnet=test_net)

info = client.futures_exchange_info()
for s in info['symbols']:
    if s['symbol'] == 'AXLUSDT':
        print(json.dumps(s, indent=2))
        break
