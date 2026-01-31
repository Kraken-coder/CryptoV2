import sqlite3
import json
from datetime import datetime
import threading

class Database:
    def __init__(self, db_name="crypto_trading.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.lock = threading.Lock()
        self.init_db()

    def init_db(self):
        """Initialize the database tables."""
        with self.lock:
            # Create a local cursor
            cursor = self.conn.cursor()
            try:
                # Orders table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS orders (
                        order_id INTEGER PRIMARY KEY,
                        symbol TEXT,
                        side TEXT,
                        order_type TEXT,
                        quantity REAL,
                        price REAL,
                        leverage INTEGER,
                        status TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        client_order_id TEXT
                    )
                ''')
                
                # Balance history table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS balance_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        asset TEXT,
                        wallet_balance REAL,
                        unrealized_pnl REAL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                self.conn.commit()
            finally:
                cursor.close()

    def log_order(self, order_response, leverage):
        """Log an order to the database."""
        try:
            with self.lock:
                cursor = self.conn.cursor()
                try:
                    cursor.execute('''
                        INSERT OR REPLACE INTO orders (
                            order_id, symbol, side, order_type, quantity, price, leverage, status, client_order_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        order_response['orderId'],
                        order_response['symbol'],
                        order_response['side'],
                        order_response['type'],
                        float(order_response['origQty']),
                        float(order_response.get('price', 0) or 0),
                        leverage,
                        order_response['status'],
                        order_response.get('clientOrderId', '')
                    ))
                    self.conn.commit()
                    print(f"DB: Logged order {order_response['orderId']} for {order_response['symbol']}.")
                finally:
                    cursor.close()
        except Exception as e:
            print(f"DB Error logging order: {e}")

    def update_order_status(self, order_id, status):
        """Update the status of an order."""
        try:
            with self.lock:
                cursor = self.conn.cursor()
                try:
                    cursor.execute("UPDATE orders SET status = ? WHERE order_id = ?", (status, order_id))
                    self.conn.commit()
                finally:
                    cursor.close()
        except Exception as e:
            print(f"DB Error updating order status: {e}")

    def get_open_orders_local(self):
        """Get orders that are locally marked as NEW or PARTIALLY_FILLED."""
        with self.lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute("SELECT order_id, symbol FROM orders WHERE status IN ('NEW', 'PARTIALLY_FILLED')")
                return cursor.fetchall()
            finally:
                cursor.close()

    def log_balance(self, asset, wallet_balance, unrealized_pnl):
        """Log account balance."""
        try:
            with self.lock:
                cursor = self.conn.cursor()
                try:
                    cursor.execute('''
                        INSERT INTO balance_history (asset, wallet_balance, unrealized_pnl)
                        VALUES (?, ?, ?)
                    ''', (asset, float(wallet_balance), float(unrealized_pnl)))
                    self.conn.commit()
                finally:
                    cursor.close()
        except Exception as e:
            print(f"DB Error logging balance: {e}")

    def close(self):
        self.conn.close()
