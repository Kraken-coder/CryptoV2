from env import demo_futures_api , demo_futures_secret , test_net
from binance.client import Client
from env import (
    sl_atr_multiplier,
    band1_lower, band1_upper, tp_band1_atr,
    band2_lower, band2_upper, tp_band2_atr,
    band3_lower, band3_upper, tp_band3_ladder,
    band4_lower, tp_band4_ladder
)
from database_orm import Database

class TradingFunctions:
    def __init__(self , client):
        self.client = Client(demo_futures_api , demo_futures_secret , testnet=test_net)
        self.db = Database()
        self.sync_state()

    def sync_state(self):
        """Syncs local database state with Binance."""
        print("Syncing state with Binance...")
        try:
            # Sync orders that we think are open
            local_open_orders = self.db.get_open_orders_local()
            for order_id, symbol in local_open_orders:
                try:
                    status_info = self.client.futures_get_order(symbol=symbol, orderId=order_id)
                    current_status = status_info['status']
                    self.db.update_order_status(order_id, current_status)
                    print(f"Synced order {order_id}: {current_status}")
                except Exception as e:
                    print(f"Error syncing order {order_id}: {e}")
            
            # Sync Balance
            self.get_balance()
            
        except Exception as e:
            print(f"Error in sync_state: {e}")

    def get_balance(self):
        balance = self.client.futures_account_balance()
        # Log significant balances to DB
        for asset_info in balance:
            if float(asset_info['balance']) > 0:
                self.db.log_balance(
                    asset=asset_info['asset'], 
                    wallet_balance=asset_info['balance'], 
                    unrealized_pnl=asset_info['crossUnPnl']
                )
        return balance

    def round_step_size(self, quantity, step_size):
        """Rounds a number to the nearest multiple of step_size."""
        import math
        precision = int(round(-math.log(step_size, 10), 0))
        return float(round(quantity, precision))

    def get_symbol_info(self, symbol):
        """Gets step size, price precision, min qty, and max qty for a symbol."""
        try:
            info = self.client.futures_exchange_info()
            for s in info['symbols']:
                if s['symbol'] == symbol:
                    lot_size = [f for f in s['filters'] if f['filterType'] == 'LOT_SIZE'][0]
                    qty_step = float(lot_size['stepSize'])
                    min_qty = float(lot_size['minQty'])
                    max_qty = float(lot_size['maxQty'])

                    # Check for Market Lot Size limits as we fallback to market
                    market_lot_size = [f for f in s['filters'] if f['filterType'] == 'MARKET_LOT_SIZE']
                    if market_lot_size:
                        m_max = float(market_lot_size[0]['maxQty'])
                        if m_max < max_qty:
                            max_qty = m_max
                    
                    price_tick = float([f for f in s['filters'] if f['filterType'] == 'PRICE_FILTER'][0]['tickSize'])
                    return qty_step, price_tick, min_qty, max_qty
            return None, None, None, None
        except Exception as e:
            print(f"Error fetching symbol info for {symbol}: {e}")
            return None, None, None, None
            return 0.001, 0.01 # Fallback

    def get_funding_rate(self, symbol):
        """Fetches the most recent funding rate for a symbol."""
        try:
            funding_rates = self.client.futures_funding_rate(symbol=symbol, limit=1)
            if funding_rates and len(funding_rates) > 0:
                return float(funding_rates[-1]['fundingRate'])
            return 0.0
        except Exception as e:
            print(f"Error fetching funding rate for {symbol}: {e}")
            # Return 0.0 on error to avoid blocking trade, or should we fail safe?
            # 0.0 means 'neutral', so we don't block.
            return 0.0

    def cancel_all_open_orders(self, symbol):
        try:
            self.client.futures_cancel_all_open_orders(symbol=symbol)
            print(f"Cancelled all open orders for {symbol}")
        except Exception as e:
            print(f"Error cancelling orders for {symbol}: {e}")

            
    def get_smart_entry_price(self, symbol, side, atr):
        """Returns optimal limit price based on volatility and spread."""
        try:
            # Get orderbook ticker
            ticker = self.client.futures_orderbook_ticker(symbol=symbol)
            bid = float(ticker['bidPrice'])
            ask = float(ticker['askPrice'])
            mid = (bid + ask) / 2
            
            # Volatility-scaled limit (0.1 ATR)
            if side == 'BUY':
                limit_price = mid - (0.10 * atr)
                # Ensure we don't place above best ask (which would be market-immediate)
                # and ideally not above best bid (so we are passive)
                # But if volatility is huge, 0.2 ATR might be very deep.
                # If 0.2 ATR is deeper than best bid, use it.
                # If 0.2 ATR is above best bid, cap at best bid - 1 tick (to be passive)
                
                # Simple Logic: Max price we pay is limit_price
                limit_price = min(limit_price, bid)
            else: # SELL
                limit_price = mid + (0.10 * atr)
                limit_price = max(limit_price, ask)
                
            return limit_price
        except Exception as e:
            print(f"Error calculating smart entry price: {e}")
            return None

    def place_strategic_order(self, symbol, side, amount, leverage, atr, edge=0):
        """
        Places an entry order followed by SL and TP orders based on Edge Banding.
        """
        import math
        
        abs_edge = abs(edge)
        print(f"Placing Strategic Order for {symbol}. Edge: {edge} (Abs: {abs_edge})")
        
        # 1. Setup & Clean
        self.cancel_all_open_orders(symbol)
        
        try:
            self.client.futures_change_margin_type(symbol=symbol, marginType='ISOLATED')
        except Exception as e:
            if "No need to change margin type" not in str(e):
                print(f"Warning: Could not change margin type for {symbol}: {e}")
        
        # Retry leverage change with backoff
        import time
        import random
        for attempt in range(3):
            try:
                self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
                break
            except Exception as e:
                # Ignore no change error if helpful, but usually it returns success if same
                if attempt == 2:
                    print(f"Error changing leverage for {symbol} to {leverage}x: {e}")
                else:
                    time.sleep(1 + random.random()) # Random backoff 1-2s

        # 2. Get Precision
        qty_step, price_tick, min_qty, max_qty = self.get_symbol_info(symbol)
        
        if qty_step is None:
             print(f"Could not get symbol info for {symbol}. Skipping.")
             return

        price_precision = int(round(-math.log(price_tick, 10), 0))
        qty_precision = int(round(-math.log(qty_step, 10), 0))

        # 3. Calculate Smart Limit Price
        limit_price_val = self.get_smart_entry_price(symbol, side, atr)
        if limit_price_val:
            limit_price_val = round(limit_price_val, price_precision)
        
        # 4. Place Entry Order (Limit Maker / GTX)
        current_price = float(self.client.futures_mark_price(symbol=symbol)["markPrice"])
        
        # Use limit price for calc if available, else mark
        calc_price = limit_price_val if limit_price_val else current_price
        
        quantity = amount / calc_price
        
        # Apply Limits
        if quantity < min_qty:
            print(f"Quantity {quantity} too small (Min: {min_qty}). Skipping.")
            return
        
        if quantity > max_qty:
            print(f"Quantity {quantity} exceeds limit (Max: {max_qty}). Clamping.")
            quantity = max_qty

        quantity = round(quantity, qty_precision)
        
        if quantity <= 0:
            print(f"Quantity too small for {symbol}. Skipping.")
            return
            
        entry_order = None
        if limit_price_val:
            try:
                print(f"Placing LIMIT (Maker) for {symbol}: {side} {quantity} @ {limit_price_val}")
                entry_order = self.client.futures_create_order(
                    symbol=symbol,
                    side=side,
                    type='LIMIT',
                    timeInForce='GTX', # Post Only - Fails if crosses spread
                    quantity=quantity,
                    price=limit_price_val
                )
                
                # Check for fill logic (Simplified: we won't wait in loop here to avoid blocking Portfolio loop)
                # But wait! If we don't get filled, we have no position, so placing TP/SL attached to this order might fail 
                # or sit there. 
                # STRATEGY: For this bot, we need to know we are IN. 
                # If we use LIMIT, we must wait a bit or track it.
                # To keep it simple but better than Market:
                # Try Limit -> Wait 5s -> if not filled, Cancel & Market.
                # UPDATED: Wait 900s (15 mins) as per user request to capture better entry
                
                import time
                start_wait = time.time()
                timeout = 180
                
                print(f"  -> Waiting up to {timeout}s for Limit fill...")
                
                while (time.time() - start_wait) < timeout: 
                    time.sleep(5) # Check every 5s
                    check = self.client.futures_get_order(symbol=symbol, orderId=entry_order['orderId'])
                    if check['status'] == 'FILLED':
                        entry_order = check
                        print(f"  -> Limit Filled!")
                        break
                    elif check['status'] == 'PARTIALLY_FILLED':
                         # If partial, we can leave it or let it ride. Complex to handle.
                         # For now, treat as 'alive' and keep waiting for full fill
                         pass
                    elif check['status'] in ['CANCELED', 'REJECTED', 'EXPIRED']:
                         print(f"  -> Order {check['status']}. Stopping wait.")
                         break
                
                # Check status again
                check = self.client.futures_get_order(symbol=symbol, orderId=entry_order['orderId'])
                if check['status'] not in ['FILLED', 'PARTIALLY_FILLED']:
                     print(f"  -> Limit not filled ({check['status']}). Cancelling and Market Buying.")
                     self.client.futures_cancel_order(symbol=symbol, orderId=entry_order['orderId'])
                     entry_order = None # Fallback to market
                else:
                    # Filled or Partial
                    entry_order = check
                    entry_price = float(entry_order['avgPrice']) # Actual fill price
                    
            except Exception as e:
                print(f"Limit order failed ({e}). Falling back to Market.")
                entry_order = None

        # Fallback to Market
        if not entry_order:
            print(f"Placing MARKET for {symbol}: {side} {quantity} @ ~{current_price}")
            entry_order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )
            # Market order usually fills immediately, but API might not return avgPrice instantly if we don't query order.
            # But the response usually has it if full fill. 
            # Safest is to use Mark price for bracket calc if we don't have avgPrice
            entry_price = current_price
            
            # Try getting actual fill price
            try:
                 check = self.client.futures_get_order(symbol=symbol, orderId=entry_order['orderId'])
                 if float(check.get('avgPrice', 0)) > 0:
                     entry_price = float(check['avgPrice'])
            except: pass

        self.db.log_order(entry_order, leverage)

        print(f"Entry {symbol} @ {entry_price}. ATR: {atr}. Setting Brackets...")

        # --- BAND CONFIGURATION LOGIC ---
        tps = [] # List of tuples (price, quantity, label)
        
        # Default SL price (can be overridden but logic is standard)
        if side == 'BUY':
             sl_price = entry_price - (sl_atr_multiplier * atr)
             tp_side = 'SELL'
        else:
             sl_price = entry_price + (sl_atr_multiplier * atr)
             tp_side = 'BUY'

        # BAND 4: > 1.0 (Ladder)
        if abs_edge >= band4_lower:
            print(f"  Using BAND 4 (Extreme) Ladder")
            m1, m2, m3 = tp_band4_ladder
            # Ladder Qty: 30%, 30%, 20% (remaining 20% hold)
            q1 = round(quantity * 0.30, qty_precision)
            q2 = round(quantity * 0.30, qty_precision)
            q3 = round(quantity * 0.20, qty_precision)

            if side == 'BUY':
                 tps.append((entry_price + m1*atr, q1, "TP1"))
                 tps.append((entry_price + m2*atr, q2, "TP2"))
                 tps.append((entry_price + m3*atr, q3, "TP3"))
            else:
                 tps.append((entry_price - m1*atr, q1, "TP1"))
                 tps.append((entry_price - m2*atr, q2, "TP2"))
                 tps.append((entry_price - m3*atr, q3, "TP3"))

        # BAND 3: 0.6 - 1.0 (Ladder)
        elif band3_lower <= abs_edge < band3_upper:
            print(f"  Using BAND 3 (Strong) Ladder")
            m1, m2, m3 = tp_band3_ladder
            q1 = round(quantity * 0.30, qty_precision)
            q2 = round(quantity * 0.30, qty_precision)
            q3 = round(quantity * 0.20, qty_precision)

            if side == 'BUY':
                 tps.append((entry_price + m1*atr, q1, "TP1"))
                 tps.append((entry_price + m2*atr, q2, "TP2"))
                 tps.append((entry_price + m3*atr, q3, "TP3"))
            else:
                 tps.append((entry_price - m1*atr, q1, "TP1"))
                 tps.append((entry_price - m2*atr, q2, "TP2"))
                 tps.append((entry_price - m3*atr, q3, "TP3"))
                 
        # BAND 2: 0.4 - 0.6 (Single TP)
        elif band2_lower <= abs_edge < band2_upper:
            print(f"  Using BAND 2 (Medium) Single TP")
            m = tp_band2_atr
            # 100% Exit
            if side == 'BUY':
                tps.append((entry_price + m*atr, quantity, "TP_Full"))
            else:
                tps.append((entry_price - m*atr, quantity, "TP_Full"))

        # BAND 1: 0.3 - 0.4 (Single TP)
        else:
            # Fallback to Band 1 logic even if < 0.3 (shouldn't happen due to entry filter)
            print(f"  Using BAND 1 (Weak) Single TP")
            m = tp_band1_atr
            if side == 'BUY':
                tps.append((entry_price + m*atr, quantity, "TP_Full"))
            else:
                tps.append((entry_price - m*atr, quantity, "TP_Full"))

        # Round Prices
        sl_price = round(sl_price, price_precision)
        tps_cleaned = []
        for p, q, l in tps:
            p = round(p, price_precision)
            tps_cleaned.append((p, q, l))
        tps = tps_cleaned

        # 5. Place Stop Loss (Full Position)
        try:
            self.client.futures_create_order(
                symbol=symbol,
                side=tp_side,
                type='STOP_MARKET',
                stopPrice=sl_price,
                closePosition=True
            )
            print(f"  SL set at {sl_price}")
        except Exception as e:
            print(f"  Failed to set SL: {e}")

        # 6. Place TPs
        # User requested LIMIT orders for TP (Maker), not Market.
        # Binance Futures: 'LIMIT' with 'reduceOnly=True' serves as a standard Take Profit Limit order.
        # Unlike TAKE_PROFIT (which is a trigger order), a LIMIT order sits in the book immediately.
        # This is generally better for fees (Maker rebate).
        
        for price, qty, label in tps:
            if qty > 0:
                try:
                    self.client.futures_create_order(
                        symbol=symbol,
                        side=tp_side,
                        type='LIMIT', # CHANGED from TAKE_PROFIT_MARKET
                        timeInForce='GTC',
                        price=price,  # Uses 'price' instead of 'stopPrice'
                        quantity=qty,
                        reduceOnly=True
                    )
                    print(f"  {label} LIMIT set at {price} (Qty: {qty})")
                except Exception as e:
                    print(f"  Failed to set {label}: {e}")

    def place_order(self, symbol, side, amount, leverage, order_type='MARKET', price=None):
        try:
            self.client.futures_change_margin_type(symbol=symbol, marginType='ISOLATED')
        except Exception as e:
            # Error occurs if already ISOLATED or if there are open positions/orders
            if "No need to change margin type" not in str(e):
                print(f"Note: Could not change margin type for {symbol}: {e}")

        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
        except Exception as e:
            print(f"Error changing leverage: {e}")

        if price:
            calc_price = float(price)
        else:
            calc_price = float(self.client.futures_mark_price(symbol=symbol)["markPrice"])
            
        quantity = amount / calc_price

        if order_type == 'MARKET':
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=quantity
            )
        elif order_type == 'LIMIT':
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type=order_type,
                timeInForce='GTC',
                quantity=quantity,
                price=price
            )
        
        # Log the successful order to the database
        self.db.log_order(order, leverage)
        
        return order

    def get_current_position(self, symbol):
        """Returns the current position amount for a symbol."""
        try:
            positions = self.client.futures_position_information(symbol=symbol)
            for p in positions:
                if p['symbol'] == symbol:
                    return float(p['positionAmt'])
            return 0.0
        except Exception as e:
            print(f"Error getting position for {symbol}: {e}")
            return 0.0

    def close_position(self, symbol):
        """Closes any open position for the symbol."""
        # First Cancel all strategy orders (TPs/SLs)
        self.cancel_all_open_orders(symbol)

        position_amt = self.get_current_position(symbol)
        if position_amt == 0:
            return

        side = 'SELL' if position_amt > 0 else 'BUY'
        quantity = abs(position_amt)
        
        try:
            print(f"Closing position for {symbol}: {side} {quantity}")
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity,
                reduceOnly=True
            )
            self.db.log_order(order, 0) # Log closing order
            return order
        except Exception as e:
            print(f"Error closing position for {symbol}: {e}")

    def get_current_atr(self, symbol):
        """Calculates current ATR(14) for a symbol using recent candles."""
        try:
            # 1. Get klines (last 20 is enough for ATR 14)
            # Interval usually matches the trading timeframe (4h)
            candles = self.client.futures_klines(symbol=symbol, interval='4h', limit=20)
            if not candles:
                return None
            
            # 2. Parse High, Low, Close
            # [open, high, low, close, ...]
            highs = [float(c[2]) for c in candles]
            lows = [float(c[3]) for c in candles]
            closes = [float(c[4]) for c in candles]
            
            # 3. Calculate TR
            tr_list = []
            for i in range(1, len(candles)):
                h = highs[i]
                l = lows[i]
                cp = closes[i-1]
                tr = max(h-l, abs(h-cp), abs(l-cp))
                tr_list.append(tr)
                
            if not tr_list:
                return 0.0
                
            # 4. SMA of TR (ATR)
            atr = sum(tr_list[-14:]) / len(tr_list[-14:])
            return atr
        except Exception as e:
            print(f"Error calculating ATR for {symbol}: {e}")
            return None

    def check_and_move_sl_to_be(self, symbol):
        """
        Checks if TP1 matches the condition (hit) and moves SL to Break-Even (-0.1 ATR).
        """
        try:
            # 1. Get Position Info (Entry Price, Side)
            pos_info = self.client.futures_position_information(symbol=symbol)
            # Filter for the symbol (futures_position_information list)
            target_pos = next((p for p in pos_info if p['symbol'] == symbol), None)
            
            if not target_pos or float(target_pos['positionAmt']) == 0:
                return

            amt = float(target_pos['positionAmt'])
            side = 'BUY' if amt > 0 else 'SELL'
            entry_price = float(target_pos['entryPrice'])
            
            # 2. Get Open Orders
            orders = self.client.futures_get_open_orders(symbol=symbol)
            
            # 3. Analyze TPs
            # Assuming we use TAKE_PROFIT_MARKET
            tp_orders = [o for o in orders if o['type'] == 'TAKE_PROFIT_MARKET']
            
            # Logic: If we started with 3 TPs, and now have < 3, TP1 implies hit.
            # Robustness: What if we have 2, or 1?
            # As long as at least one TP is gone (assuming execution order TP1->TP2->TP3),
            # we should move SL.
            # NOTE: This assumes the user doesn't manually cancel TPs.
            
            if len(tp_orders) < 3: 
                # TP1 likely hit.
                
                # 4. Calculate New SL Target
                atr = self.get_current_atr(symbol)
                if not atr: return
                
                # User Request: "move the sl to -0.1 atr"
                # For Buy: Entry - 0.1*ATR
                # For Sell: Entry + 0.1*ATR
                
                sl_offset = 0.1 * atr
                
                if side == 'BUY':
                    new_sl_price = entry_price - sl_offset
                else:
                    new_sl_price = entry_price + sl_offset
                    
                # 5. Check Current SL
                stop_orders = [o for o in orders if o['type'] == 'STOP_MARKET']
                
                if not stop_orders:
                    # No SL? That's dangerous. Maybe place one?
                    # For now, we only move existing.
                    return
                
                current_sl_order = stop_orders[0] # Assume 1 SL
                current_sl_price = float(current_sl_order['stopPrice'])
                
                # 6. Decide Update
                update_needed = False
                if side == 'BUY':
                    # If current SL is lower than new target (worse), raise it.
                    # Also ensure we don't accidentally move it DOWN if we already trailed higher (unlikely but safe).
                    if current_sl_price < new_sl_price:
                         update_needed = True
                else: # SELL
                     # If current SL is higher than new target (worse), lower it.
                     if current_sl_price > new_sl_price:
                         update_needed = True
                         
                if update_needed:
                    print(f"TP1 Hit detected for {symbol}. Moving SL to BE (-0.1 ATR): {current_sl_price} -> {new_sl_price:.4f}")
                    
                    # Cancel Old
                    self.client.futures_cancel_order(symbol=symbol, orderId=current_sl_order['orderId'])
                    
                    # Place New
                    tp_side = 'SELL' if side == 'BUY' else 'BUY'
                    
                    # Rounding
                    qty_step, price_tick, min_qty, max_qty = self.get_symbol_info(symbol)
                    import math
                    price_precision = int(round(-math.log(price_tick, 10), 0))
                    new_sl_price = round(new_sl_price, price_precision)
                    
                    self.client.futures_create_order(
                        symbol=symbol,
                        side=tp_side,
                        type='STOP_MARKET',
                        stopPrice=new_sl_price,
                        closePosition=True
                    )
                    print(f"  -> SL Updated.")

        except Exception as e:
            print(f"Error in check_and_move_sl_to_be({symbol}): {e}")

    def cleanup_orphan_orders(self):
        """
        Cancels open orders for symbols that have no open position.
        This prevents dangling TP/SL orders after a position is closed by one of them.
        """
        try:
            print("Checking for orphan orders (dangling TP/SL)...")
            # 1. Get all open positions
            positions = self.client.futures_position_information()
            # Map symbol -> amount (Note: futures_position_information returns list of all symbols)
            position_map = {p['symbol']: float(p['positionAmt']) for p in positions}
            
            # 2. Get all open orders (account-wide)
            open_orders = self.client.futures_get_open_orders()
            
            # 3. Identify symbols with orders but no position
            symbols_to_clean = set()
            for order in open_orders:
                sym = order['symbol']
                # If position is 0 or extremely close to 0
                if abs(position_map.get(sym, 0.0)) == 0:
                    symbols_to_clean.add(sym)
            
            # 4. Cancel them
            if symbols_to_clean:
                print(f"Found orphan orders on {len(symbols_to_clean)} symbols. Cleaning up...")
                for sym in symbols_to_clean:
                    print(f"  -> Cancelling orders for {sym} (No open position)")
                    self.cancel_all_open_orders(sym)
            else:
                print("No orphan orders found.")
                
        except Exception as e:
            print(f"Error in cleanup_orphan_orders: {e}")

if __name__ == "__main__":
    client = Client(demo_futures_api , demo_futures_secret , testnet=test_net)
    print(client.futures_account_balance())