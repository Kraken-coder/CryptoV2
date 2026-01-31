import os
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException

def verify_api_permissions():
    # Load environment variables
    load_dotenv()

    # Fetch keys as the bot uses them
    api_key = os.getenv("demo_futures_api")
    secret_key = os.getenv("demo_futures_secret")
    test_net_str = os.getenv("test_net", "False")
    test_net = test_net_str.lower() == "true"

    print("--- Binance API Permission Verification ---")
    print(f"Environment: {'TESTNET' if test_net else 'MAINNET'}")
    
    if not api_key or not secret_key:
        print("❌ Error: API keys not found in .env file (demo_futures_api/demo_futures_secret)")
        return

    print(f"API Key: {api_key[:6]}...{api_key[-4:]}")

    try:
        # Initialize Client
        client = Client(api_key, secret_key, testnet=test_net)
        
        # 1. Check Connectivity & Time (Basic check)
        print("\n1. Pinging Server...")
        client.ping()
        print("   ✅ Server Ping Successful")

        # 2. Check Account Permissions (futures_account)
        # This endpoint returns account config and permission flags
        print("\n2. Checking Account Permissions...")
        account_info = client.futures_account()
        
        can_trade = account_info.get('canTrade', False)
        can_withdraw = account_info.get('canWithdraw', False)
        can_deposit = account_info.get('canDeposit', False)
        
        print(f"   Can Trade:    {'✅ YES' if can_trade else '❌ NO'}")
        print(f"   Can Withdraw: {can_withdraw}")
        print(f"   Can Deposit:  {can_deposit}")

        if not can_trade:
            print("   ⚠️  WARNING: Trading permission appears to be disabled!")

        # 3. Check Account Balance
        print("\n3. Checking Wallet Balance (Futures)...")
        balances = client.futures_account_balance()
        
        usdt_balance = 0.0
        details = []
        
        for asset in balances:
            bal = float(asset['balance'])
            if bal > 0:
                details.append(f"{asset['asset']}: {bal:.4f}")
            if asset['asset'] == 'USDT':
                usdt_balance = bal
                # Fallback for available balance keys
                available = float(asset.get('availableBalance', asset.get('withdrawAvailable', 0)))
                
        if details:
            print("   Assets found: " + ", ".join(details))
            print(f"   👉 Total USDT Balance: {usdt_balance:.4f}")
        else:
            print("   ⚠️  No positive balances found.")

        print("\n-------------------------------------------")
        if can_trade and usdt_balance > 0:
            print("✅ VERIFICATION COMPLETE: Keys look good for trading.")
        elif can_trade and usdt_balance == 0:
            print("⚠️  VERIFICATION WARNING: Keys work, but USDT balance is 0. Please fund account.")
        else:
            print("❌ VERIFICATION FAILED: Check permissions.")

    except BinanceAPIException as e:
        print(f"\n❌ Binance API Error:")
        print(f"   Code: {e.code}")
        print(f"   Msg:  {e.message}")
        print("   Suggestion: Check if IP restrictions are disabled or if keys are correct.")
    except Exception as e:
        print(f"\n❌ Script Error: {e}")

if __name__ == "__main__":
    verify_api_permissions()
