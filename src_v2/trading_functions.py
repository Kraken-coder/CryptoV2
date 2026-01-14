from env import demo_futures_api , demo_futures_secret , test_net
from binance.client import Client
from env import leverage_large_edge , leverage_small_edge , stop_loss_large_edge , stop_loss_small_edge
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
        """Gets step size and price precision for a symbol."""
        try:
            info = self.client.futures_exchange_info()
            for s in info['symbols']:
                if s['symbol'] == symbol:
                    qty_step = float([f['stepSize'] for f in s['filters'] if f['filterType'] == 'LOT_SIZE'][0])
                    price_tick = float([f['tickSize'] for f in s['filters'] if f['filterType'] == 'PRICE_FILTER'][0])
                    return qty_step, price_tick
        except Exception as e:
            print(f"Error fetching symbol info for {symbol}: {e}")
            return 0.001, 0.01 # Fallback

    def cancel_all_open_orders(self, symbol):
        try:
            self.client.futures_cancel_all_open_orders(symbol=symbol)
            print(f"Cancelled all open orders for {symbol}")
        except Exception as e:
            print(f"Error cancelling orders for {symbol}: {e}")

    def place_strategic_order(self, symbol, side, amount, leverage, atr):
        """
        Places an entry order followed by SL and 3 partial TP orders.
        TP1 = Entry + 0.7 ATR (30%)
        TP2 = Entry + 1.5 ATR (30%)
        TP3 = Entry + 2.5 ATR (20%)
        Rest (20%) holds.
        SL = Entry - 1.5 ATR (100%)
        """
        import math
        
        # 1. Setup & Clean
        self.cancel_all_open_orders(symbol)
        
        try:
            self.client.futures_change_margin_type(symbol=symbol, marginType='ISOLATED')
        except: pass
        
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
        except: pass

        # 2. Get Precision
        qty_step, price_tick = self.get_symbol_info(symbol)
        price_precision = int(round(-math.log(price_tick, 10), 0))
        qty_precision = int(round(-math.log(qty_step, 10), 0))

        # 3. Place Entry Order (Market)
        current_price = float(self.client.futures_mark_price(symbol=symbol)["markPrice"])
        quantity = amount / current_price
        quantity = round(quantity, qty_precision)
        
        if quantity == 0:
            print(f"Quantity too small for {symbol}. Skipping.")
            return

        print(f"Placing ENTRY for {symbol}: {side} {quantity} @ ~{current_price}")
        entry_order = self.client.futures_create_order(
            symbol=symbol,
            side=side,
            type='MARKET',
            quantity=quantity
        )
        self.db.log_order(entry_order, leverage)

        # 4. Calculate Levels using Fill Price (or fallback to Mark)
        # Usually Market order response doesn't have avgPrice immediately unless we query order
        # We will use current_price (Mark Price) which is safer for immediate SL placement
        entry_price = current_price 
        
        print(f"Entry {symbol} @ {entry_price}. ATR: {atr}. Setting Brackets...")

        # Directions
        if side == 'BUY':
            tp_side = 'SELL'
            sl_price = entry_price - (1.5 * atr)
            tp1_price = entry_price + (0.7 * atr)
            tp2_price = entry_price + (1.5 * atr)
            tp3_price = entry_price + (2.5 * atr)
        else: # SELL
            tp_side = 'BUY'
            sl_price = entry_price + (1.5 * atr)
            tp1_price = entry_price - (0.7 * atr)
            tp2_price = entry_price - (1.5 * atr)
            tp3_price = entry_price - (2.5 * atr)

        # Round Prices
        sl_price = round(sl_price, price_precision)
        tp1_price = round(tp1_price, price_precision)
        tp2_price = round(tp2_price, price_precision)
        tp3_price = round(tp3_price, price_precision)

        # Quantities
        q_30 = round(quantity * 0.30, qty_precision)
        q_20 = round(quantity * 0.20, qty_precision)
        
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
        tps = [(tp1_price, q_30, "TP1"), (tp2_price, q_30, "TP2"), (tp3_price, q_20, "TP3")]
        
        for price, qty, label in tps:
            if qty > 0:
                try:
                    self.client.futures_create_order(
                        symbol=symbol,
                        side=tp_side,
                        type='TAKE_PROFIT_MARKET',
                        stopPrice=price,
                        quantity=qty,
                        reduceOnly=True
                    )
                    print(f"  {label} set at {price} (Qty: {qty})")
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

if __name__ == "__main__":
    client = Client(demo_futures_api , demo_futures_secret , testnet=test_net)
    print(client.futures_account_balance())