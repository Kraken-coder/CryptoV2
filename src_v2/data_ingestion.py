from binance import Client
import pandas as pd 
import numpy as np
import pickle as pkl
from env import api_key , secret_key
import json
from dateutil.relativedelta import relativedelta
import time
import requests
from datetime import datetime
BASE_URL = "https://api.binance.com"

def fetch_historical_klines(symbol, interval, start_str, end_str=None):
    pass 
def fetch_funding_history(symbol, start_ts, end_ts):
    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    all_funding = []
    current_start = int(start_ts)
    end_ts = int(end_ts)
    
    while current_start < end_ts:
        params = {
            "symbol": symbol,
            "startTime": current_start,
            "endTime": end_ts,
            "limit": 1000
        }
        try:
            r = requests.get(url, params=params)
            data = r.json()
            
            if not data:
                break
                
            all_funding.extend(data)
            
            # Update loop
            last_timestamp = data[-1]['fundingTime']
            if last_timestamp == current_start:
                break
            current_start = last_timestamp + 1
            
            time.sleep(0.1) # Respect rate limits
            
        except Exception as e:
            print(f"Error fetching {symbol}: {e}")
            break
            
    return all_funding


class DataIngestion:
    def __init__(self):
        self.client = Client(api_key=api_key, api_secret=secret_key)  # Initialize with your API key and secret if needed
    def get_data(self , symbol):
        forma = "1 Jan, 2018"
        start_str = (datetime.now() - relativedelta(months=2)).strftime("%d %b, %Y")
        interval = Client.KLINE_INTERVAL_4HOUR
        klines = self.client.get_historical_klines(symbol, interval, start_str)
        all_dfs = []
        # Process data into DataFrame
        df_temp = pd.DataFrame(klines, columns=[
            "Open time", "Open", "High", "Low", "Close", "Volume",
            "Close time", "Quote asset volume", "Number of trades",
            "Taker buy base asset volume", "Taker buy quote asset volume", "Ignore"
        ])
        # Convert types
        df_temp["Open time"] = pd.to_datetime(df_temp["Open time"], unit="ms")
        numeric_cols = ["Open", "High", "Low", "Close", "Volume"]
        df_temp[numeric_cols] = df_temp[numeric_cols].apply(pd.to_numeric, axis=1)
        
        # Add symbol identifier
        df_temp['symbol'] = symbol
        
        all_dfs.append(df_temp)
        df_wrapper = pd.concat(all_dfs, ignore_index=True)
        df = df_wrapper
        start_ms = df['Open time'].min().timestamp() * 1000
        end_ms = df['Open time'].max().timestamp() * 1000
        rates = fetch_funding_history(symbol, start_ms, end_ms)
        funding_records = [ ]
        for r in rates:
            funding_records.append({
                'symbol': r['symbol'],
                'Open time': r['fundingTime'], # We map fundingTime -> Open time for the join
                'funding_rate': r['fundingRate']
            })
        df_funding = pd.DataFrame(funding_records)
# Only try to process if we actually got data
        if not df_funding.empty:
            df_funding['Open time'] = pd.to_datetime(df_funding['Open time'], unit='ms')
            df_funding['funding_rate'] = pd.to_numeric(df_funding['funding_rate'])

            # 6. Merge with main DataFrame
            # Left join ensures we keep all your original candles
            df = df.merge(df_funding, on=['symbol', 'Open time'], how='left')

            # 7. Fill gaps
            # We forward fill only. Initial NaNs (before first funding rate) will remain NaN.
            # The invalid .fillna() is removed.
            df['funding_rate'] = df.groupby('symbol')['funding_rate'].ffill()
        return df
    def __engineer_features__(self , df : pd.DataFrame) -> pd.DataFrame:
        feature_list = ['log_average',
                        'vol_10',
                        'vol_20',
                        'vol_40',
                        'vol_ratio',
                        'true_range',
                        'norm_range',
                        'atr_14',
                        'range_ratio',
                        'vol_rel',
                        'vol_z',
                        'abs_r_x_vol',
                        'sum_r_6',
                        'ema_diff',
                        'hour_sin',
                        'hour_cos',
                        'day_sin',
                        'day_cos',
                        'ret_lag_1',
                        'vol_lag_1',
                        'ret_lag_2',
                        'vol_lag_2',
                        'ret_lag_3',
                        'vol_lag_3',
                        'ret_lag_5',
                        'vol_lag_5',
                        'ret_skew_20',
                        'ret_kurt_20',
                        'ret_autocorr_20',
                        'funding_z',
                        'funding_x_ret',
                        'funding_delta',
                        'trend_regime_code',
                        'vol_regime_code']
        df['funding_z'] = df.groupby('symbol')['funding_rate'].transform(
                                                                           lambda x: (x - x.rolling(200).mean()) / x.rolling(200).std()
                                                                        )
        df['log_average'] = df.groupby('symbol')['Close'].transform(lambda x: np.log(x / x.shift(1)))
        # Calculate volatility metrics per symbol
        df['vol_10'] = df.groupby('symbol')['log_average'].transform(lambda x: x.rolling(window=10).std())
        df['vol_20'] = df.groupby('symbol')['log_average'].transform(lambda x: x.rolling(window=20).std())
        df['vol_40'] = df.groupby('symbol')['log_average'].transform(lambda x: x.rolling(window=40).std())

        df['vol_ratio'] = df['vol_10'] / df['vol_40']

        # Display the new columns
        df['true_range'] = df['High'] - df['Low']
        df['norm_range'] = df['true_range'] / df['Close']

        # Apply rolling calculations per symbol using groupby().transform()
        df['atr_14'] = df.groupby('symbol')['true_range'].transform(lambda x: x.rolling(window=14).mean())

        # Calculate 20-period mean of true_range per symbol for the ratio
        df['true_range_mean_20'] = df.groupby('symbol')['true_range'].transform(lambda x: x.rolling(window=20).mean())
        df['range_ratio'] = df['true_range'] / df['true_range_mean_20']

        # Calculate Volume metrics per symbol
        df['vol_mean_20'] = df.groupby('symbol')['Volume'].transform(lambda x: x.rolling(window=20).mean())
        df['vol_std_20'] = df.groupby('symbol')['Volume'].transform(lambda x: x.rolling(window=20).std())

        df['vol_rel'] = df['Volume'] / df['vol_mean_20']
        df['vol_z'] = (df['Volume'] - df['vol_mean_20']) / df['vol_std_20']
        df['abs_r_x_vol'] = df['log_average'].abs() * df['vol_rel']

        # Calculate Regime Labels
        # Trend regime: based on 6-period return sign consistency, calculated per symbol
        df['sum_r_6'] = df.groupby('symbol')['log_average'].transform(lambda x: x.rolling(window=6).sum())
        df['trend_regime'] = df['sum_r_6'].apply(lambda x: 'trend' if abs(x) > 0.01 else 'range')

        # Volume regime: based on vol_20 quantiles (calculated globally across all symbols since returns are normalized)
        vol_20_q33 = df['vol_20'].quantile(0.33)
        vol_20_q67 = df['vol_20'].quantile(0.67)
        df['vol_regime'] = df['vol_20'].apply(
            lambda x: 'low' if x <= vol_20_q33 else ('high' if x >= vol_20_q67 else 'medium')
        )
        df['funding_x_ret'] = df['funding_z'] * df['log_average']
        df['funding_delta'] = df.groupby('symbol')['funding_z'].diff()
        df['ema_20'] = df.groupby('symbol')['Close'].transform(lambda x: x.ewm(span=20, adjust=False).mean())
        df['ema_50'] = df.groupby('symbol')['Close'].transform(lambda x: x.ewm(span=50, adjust=False).mean())

        # Calculate the difference
        df['ema_diff'] = df['ema_20'] - df['ema_50']
        df['Open time'] = pd.to_datetime(df['Open time'])

        # 1. Basic Integer Features
        df['hour'] = df['Open time'].dt.hour
        df['day_of_week'] = df['Open time'].dt.dayofweek  # 0=Monday, 6=Sunday

        # 2. Cyclical Encodings (Critical for ML/Deep Learning)
        # Since time is circular (23:00 is close to 00:00), raw integers can confuse models.
        # We map them onto a unit circle using sin/cos.

        # Hour (Period = 24)
        df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
        df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)

        # Day of Week (Period = 7)
        df['day_sin'] = np.sin(2 * np.pi * df['day_of_week'] / 7)
        df['day_cos'] = np.cos(2 * np.pi * df['day_of_week'] / 7)
        lags = [1, 2, 3, 5]

        for lag in lags:
            # Lagged Log Returns
            df[f'ret_lag_{lag}'] = df.groupby('symbol')['log_average'].shift(lag)
            # Lagged Relative Volume
            df[f'vol_lag_{lag}'] = df.groupby('symbol')['vol_rel'].shift(lag)

        # --- 2. Rolling Higher Moments (Distribution Shape) ---
        # Skewness: Is the distribution leaning left or right? (Crash risk)
        # Kurtosis: Are there fat tails? (Extreme event probability)
        df['ret_skew_20'] = df.groupby('symbol')['log_average'].transform(lambda x: x.rolling(window=20).skew())
        df['ret_kurt_20'] = df.groupby('symbol')['log_average'].transform(lambda x: x.rolling(window=20).kurt())

        # --- 3. Rolling Autocorrelation (Mean Reversion vs Trend) ---
        # Measures if today's return is correlated with yesterday's return over a window
        # Positive = Trend, Negative = Mean Reversion
        df['ret_autocorr_20'] = df.groupby('symbol')['log_average'].transform(
            lambda x: x.rolling(window=20).corr(x.shift(1))
        )
        df_model = df.dropna().copy()
        df_model['trend_regime_code'] = df_model['trend_regime'].astype('category').cat.codes
        df_model['vol_regime_code'] = df_model['vol_regime'].astype('category').cat.codes

        return df_model[feature_list]

if __name__ == '__main__':
    print("Hello")
    from datetime import datetime
    now = datetime.now()
    tes = DataIngestion()
    data = tes.get_data('BTCUSDT')
    print(data.columns)
    print(len(data))
    print(data['funding_rate'].describe())
    engineerd_f = tes.__engineer_features__(data)
    print(engineerd_f)