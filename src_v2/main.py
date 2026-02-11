import time
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from trading_functions import TradingFunctions
from data_ingestion import DataIngestion
from model import Classifier
from trading_utils import TradingPrice
from binance.client import Client
from env import demo_futures_api, demo_futures_secret, test_net, max_funding_rate_threshold, edge_threshold_small, max_open_positions

# Configuration - Full List
TRADING_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", 
    "SOLUSDT", "DOGEUSDT", "MATICUSDT", "DOTUSDT", "AVAXUSDT",
    "LTCUSDT", "LINKUSDT", "ATOMUSDT", "UNIUSDT"
]

def get_next_candle_time():
    """Calculates the next 4H candle close time."""
    now = datetime.utcnow()
    # 4H candles close at 0, 4, 8, 12, 16, 20
    next_hour = ((now.hour // 4) + 1) * 4
    if next_hour >= 24:
        target = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    else:
        target = now.replace(hour=next_hour, minute=0, second=0, microsecond=0)
    return target

def wait_for_next_candle(trading):
    """
    Sleeps until the next 4H candle close (with buffer), 
    while periodically checking positions to move SL if TP1 is hit.
    """
    target = get_next_candle_time()
    buffer_seconds = 120
    target_time_buffered = target + timedelta(seconds=buffer_seconds)
    
    print(f"Next 4H candle closes at {target} UTC. Entering monitoring loop until {target_time_buffered} UTC.")
    
    while datetime.utcnow() < target_time_buffered:
        # Sleep interval (e.g., 60s)
        time.sleep(60)
        
        # MONITORING TASK
        try:
            # 1. Get all active positions efficiently
            all_positions = trading.client.futures_position_information()
            active_symbols = [
                p['symbol'] for p in all_positions 
                if float(p['positionAmt']) != 0 and p['symbol'] in TRADING_SYMBOLS
            ]
            
            if active_symbols:
                # print(f"Monitoring {len(active_symbols)} active positions...")
                for sym in active_symbols:
                    trading.check_and_move_sl_to_be(sym)
                    
        except Exception as e:
            print(f"Error in monitoring loop: {e}")

def is_within_trading_window(minutes_tolerance=30):
    now = datetime.utcnow()
    # Check if we are in the first X minutes of a 4-hour block
    if now.hour % 4 == 0 and now.minute < minutes_tolerance:
        return True
    return False

def get_total_usdt_capital(trading):
    try:
        balance_info = trading.get_balance()
        for asset in balance_info:
            if asset['asset'] == 'USDT':
                return float(asset['balance'])
    except Exception as e:
        print(f"Error fetching balance: {e}")
    return 1000.0 

def analyze_symbol(symbol, data_ingestion, model, trading_price, trading, max_funding_rate_threshold):
    """Run analysis for a single symbol. Returns dict or None."""
    try:
        # 1. Get Data
        df = data_ingestion.get_data(symbol)
        if df.empty: 
            return None

        # 2. Engineer Features
        df_features = data_ingestion.__engineer_features__(df)
        if df_features.empty:
            return None

        # 3. Predict
        probs = model.predict(df_features)
        
        # 4. Edge & Decision
        edge = trading_price.calculate_edge(probs)
        print(f"Symbol: {symbol}, Edge: {edge:.4f}")
        side, leverage, desc = trading_price.get_trade_decision(edge)
        # Funding rate Check
        funding_rate = trading.get_funding_rate(symbol)
        limit_val = max_funding_rate_threshold / 100.0
        
        if side == "BUY" and funding_rate > limit_val:
            side = "NEUTRAL"
            desc = "Filtered (High Funding)"
        elif side == "SELL" and funding_rate < -limit_val:
            side = "NEUTRAL"
            desc = "Filtered (Low Funding)"
        
        volatility = df_features.iloc[-1]['vol_20']
        atr = df_features.iloc[-1]['atr_14']
        
        return {
            'symbol': symbol,
            'side': side,
            'leverage': leverage,
            'desc': desc,
            'volatility': volatility,
            'edge': edge,
            'atr': atr,
            'funding': funding_rate
        }
    except Exception as e:
        # print(f"Error analyzing {symbol}: {e}") # Reduce noise
        return None

def main():
    print("Starting CryptoV2 Bot with Portfolio Trading (200 Symbol Scan)...")
    
    # Log active environment
    if test_net:
        print(f"ENVIRONMENT: TESTNET (Key: {demo_futures_api[:5]}...)")
    else:
        print(f"ENVIRONMENT: MAINNET (Key: {demo_futures_api[:5]}...)")

    client = Client(demo_futures_api, demo_futures_secret, testnet=test_net)
    trading = TradingFunctions(client)
    data_ingestion = DataIngestion()
    model = Classifier()
    trading_price = TradingPrice()

    while True:
        try:
            print(f"\n--- Analysis cycle check at {datetime.utcnow()} ---")
            
            # 0. Routine Cleanup
            trading.cleanup_orphan_orders()
            
            if not is_within_trading_window(minutes_tolerance=45): # Increased for 200 items scan
                print("Outside of 45-minute post-close trading window.")
                wait_for_next_candle(trading)
                continue 
            
            print("Fetching current positions...")
            try:
                # Efficiently get all positions once
                all_positions_raw = trading.client.futures_position_information()
                current_positions = {p['symbol']: float(p['positionAmt']) for p in all_positions_raw if float(p['positionAmt']) != 0}
                print(f"Open Positions: {list(current_positions.keys())}")
            except Exception as e:
                print(f"Error fetching open positions: {e}")
                current_positions = {}

            current_capital = get_total_usdt_capital(trading)
            print(f"Total USDT Capital: {current_capital}")
            
            # Using 90% capital, distributed among active trades
            deployable_capital = current_capital * 0.90 

            print(f"Analyzing {len(TRADING_SYMBOLS)} symbols...")
            candidates = []
            
            # Use ThreadPool for Analysis (I/O bound)
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {
                    executor.submit(analyze_symbol, s, data_ingestion, model, trading_price, trading, max_funding_rate_threshold): s 
                    for s in TRADING_SYMBOLS
                }
                
                count = 0
                for future in as_completed(futures):
                    count += 1
                    if count % 20 == 0:
                        print(f"Processed {count}/{len(TRADING_SYMBOLS)}")
                        
                    res = future.result()
                    if res:
                        candidates.append(res)
            
            # --- HYSTERESIS LOGIC (Stop the Bleeding) ---
            # If we hold a position and the edge has decayed but is still weakly in our favor, 
            # upgradethe status to BUY/SELL to prevent closing (Hold).
            # Threshold: 50% of the normal entry threshold.
            
            # Uses edge_threshold_small from env.py (default 0.05)
            # weak_threshold becomes 0.025
            weak_threshold = edge_threshold_small * 0.5 
            
            for c in candidates:
                sym = c['symbol']
                current_qty = current_positions.get(sym, 0)
                
                # If we are Long and signal is Neutral (but edge still positive > weak_threshold)
                if current_qty > 0 and c['side'] == 'NEUTRAL' and c['edge'] > weak_threshold:
                    c['side'] = 'BUY'
                    c['desc'] = f"Hold (Weak Edge {c['edge']:.3f})"
                    print(f"  >> HYSTERESIS: Keeping {sym} LONG (Edge {c['edge']:.3f} > {weak_threshold})")
                
                # If we are Short and signal is Neutral (but edge still negative < -weak_threshold)
                elif current_qty < 0 and c['side'] == 'NEUTRAL' and c['edge'] < -weak_threshold:
                    c['side'] = 'SELL'
                    c['desc'] = f"Hold (Weak Edge {c['edge']:.3f})"
                    print(f"  >> HYSTERESIS: Keeping {sym} SHORT (Edge {c['edge']:.3f} < {-weak_threshold})")

            # Filtering and Selection
            long_candidates = [c for c in candidates if c['side'] == 'BUY']
            short_candidates = [c for c in candidates if c['side'] == 'SELL']
            
            # Sort by absolute Edge strength (for logging purposes)
            long_candidates.sort(key=lambda x: x['edge'], reverse=True)
            short_candidates.sort(key=lambda x: x['edge'])
            
            # Select top N candidates based on absolute edge strength
            eligible = [c for c in candidates if c['side'] in ('BUY', 'SELL')]
            
            # Sort all eligible trades by conviction (absolute edge)
            eligible.sort(key=lambda x: abs(x['edge']), reverse=True)
            
            # Take the top N
            if eligible:
                selected_portfolio = eligible[:max_open_positions]
            else:
                selected_portfolio = []

            selected_symbols = set(c['symbol'] for c in selected_portfolio)
            
            print(f"\nSelected Portfolio ({len(selected_portfolio)} assets, Limit: {max_open_positions}):")
            for c in selected_portfolio:
                print(f"  {c['symbol']} ({c['side']}): Edge {c['edge']:.4f}")
            if not selected_portfolio:
                print("  (No tradable candidate found this cycle)")

            # Prepare Execution Plan
            final_execution_list = []
            
            # 1. Close unselected positions (Strictly those with NO valid edge/Neutral)
            for symbol in current_positions:
                if symbol not in selected_symbols:
                    final_execution_list.append({
                        'symbol': symbol,
                        'side': 'NEUTRAL',
                        'action': 'CLOSE',
                        'desc': 'Rebalancing (No Edge)'
                    })
            
            # 2. Open/Update selected positions
            total_inverse_volilaty = 0
            for c in selected_portfolio:
                if c['volatility'] > 0:
                    total_inverse_volilaty += (1.0 / c['volatility'])
            
            if total_inverse_volilaty == 0: total_inverse_volilaty = 1

            for c in selected_portfolio:
                # Calculate Weight
                if total_inverse_volilaty > 1 and c['volatility'] > 0:
                    weight = (1.0 / c['volatility']) / total_inverse_volilaty
                else:
                    weight = 1.0 / len(selected_portfolio) if selected_portfolio else 0
                
                # Apply leverage to the capital allocation
                allocated_margin = deployable_capital * weight
                size_usdt = max(6, allocated_margin * c['leverage'])
                
                final_execution_list.append({
                    'symbol': c['symbol'],
                    'side': c['side'],
                    'leverage': c['leverage'],
                    'amount': size_usdt ,
                    'atr': c['atr'],
                    'edge': c['edge'],
                    'action': 'OPEN',
                    'desc': f"Edge {c['edge']:.2f}"
                })

            print("\nExecuting Trades...")
            
            def execute_single_task(task):
                sym = task['symbol']
                try:
                    if task['action'] == 'CLOSE':
                        print(f"--> CLOSING {sym} (No Edge)")
                        trading.close_position(sym)
                    elif task['action'] == 'OPEN':
                        # Check current pos
                        curr = current_positions.get(sym, 0)
                        side = task['side']
                        target_size = task['amount']
                        leverage = task['leverage']
                        atr = task['atr']
                        curr_edge = task['edge']
                        
                        # SMART EXECUTION LOGIC to minimize fees
                        
                        # 1. If Position matches Side -> HOLD
                        # Optimization: We check if strict direction matches.
                        # Even if edge strength changed (e.g. Small Edge -> Large Edge), we do NOT close & reopen 
                        # just to change leverage. We hold the existing position to strictly minimize fees.
                        if (side == 'BUY' and curr > 0) or (side == 'SELL' and curr < 0):
                            print(f"--> HOLDING {sym} (Existing {side} position matches signal). Ignoring leverage/size updates.")
                            return

                        # 2. If Position Flip -> Close and Open
                        if (side == 'BUY' and curr < 0) or (side == 'SELL' and curr > 0):
                            print(f"--> FLIPPING {sym} (Close existing)")
                            trading.close_position(sym)
                            curr = 0
                            
                        # 3. If Rebalancing (only if we didn't return above)
                        # The code above returns if side matches, so we only reach here if curr == 0
                        # (because if curr != 0 and side matched, we returned. If side diff, we closed so curr=0)
                        
                        # Double check if any dust remains? 
                        # Assuming close_position worked or curr was 0.

                        print(f"--> OPENING {side} {sym} Size ${target_size:.2f}")
                        trading.place_strategic_order(
                            symbol=sym,
                            side=side,
                            amount=target_size,
                            leverage=leverage,
                            atr=atr,
                            edge=curr_edge # Pass Edge for TP Banding
                        )
                except Exception as e:
                    print(f"Error executing {sym}: {e}")

            # Execute in parallel (limit workers)
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(execute_single_task, task) for task in final_execution_list]
                for f in as_completed(futures):
                    try: 
                        f.result() 
                    except Exception as e: 
                        print(f"Exec Error: {e}")

            print("Cycle complete.")
            wait_for_next_candle(trading)
            
        except Exception as e:
            print(f"CRITICAL ERROR in main loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
