import os
import json
from flask import Flask, request, jsonify
from binance.client import Client
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Load API keys
api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')
google_credentials = os.getenv('GOOGLE_CREDENTIALS')

if not google_credentials:
    raise Exception("Missing GOOGLE_CREDENTIALS environment variable")

client = Client(api_key, api_secret)

# Setup Google Sheets
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name(google_credentials, scope)
gs_client = gspread.authorize(creds)
sheet = gs_client.open("Binance Bot Logs").sheet1

# Round quantity based on symbol precision
def round_step_size(quantity, step_size):
    precision = int(round(-1 * (len(str(step_size).split(".")[1]))))
    return round(quantity, precision)

# Get step size for a symbol
def get_step_size(symbol):
    info = client.get_symbol_info(symbol)
    for f in info['filters']:
        if f['filterType'] == 'LOT_SIZE':
            return float(f['stepSize'])
    return 0.000001  # fallback

# Log buy action
def log_buy_trade(symbol, price, qty, usdt_amount, testing):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([
        symbol, timestamp, price, qty, usdt_amount, testing, '', '', '', 'No'
    ])

# Log sell and calculate profit
def log_sell_trade(symbol, sell_price):
    sell_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    records = sheet.get_all_values()

    for i in range(len(records) - 1, 0, -1):
        row = records[i]
        if row[0] == symbol and row[9] != 'Yes' and row[6] == 'No':
            try:
                buy_price = float(row[2])
                qty = float(row[3])
                usdt_amount = float(row[4])
                profit = round((sell_price - buy_price) * qty, 2)

                sheet.update(f'G{i+1}:J{i+1}', [[
                    sell_timestamp, sell_price, profit, 'Yes'
                ]])
            except Exception as e:
                print("Logging sell failed:", e)
            break

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    symbol = data.get("symbol")
    action = data.get("action")
    usdt_amount = float(data.get("amount", 0))
    testing = str(data.get("testing", "no")).lower() == "yes"

    if not symbol or not action or not usdt_amount:
        return jsonify({"error": "Missing data"}), 400

    try:
        price = float(client.get_symbol_ticker(symbol=symbol)["price"])
    except Exception as e:
        return jsonify({"error": f"Price fetch failed: {e}"}), 500

    # Convert USDT to coin quantity
    qty = usdt_amount / price
    step = get_step_size(symbol)
    qty = round_step_size(qty, step)

    if action == "buy":
        if not testing:
            try:
                client.order_market_buy(symbol=symbol, quantity=qty)
                print(f"[LIVE BUY] {symbol} for {usdt_amount} USDT = {qty}")
            except Exception as e:
                return jsonify({"error": f"Buy failed: {e}"}), 500
        else:
            print(f"[TEST BUY] {symbol} for {usdt_amount} USDT = {qty}")

        log_buy_trade(symbol, price, qty, usdt_amount, "Yes" if testing else "No")

    elif action == "sell":
        if not testing:
            try:
                client.order_market_sell(symbol=symbol, quantity=qty)
                print(f"[LIVE SELL] {symbol} {qty}")
            except Exception as e:
                return jsonify({"error": f"Sell failed: {e}"}), 500
        else:
            print(f"[TEST SELL] {symbol} {qty}")

        log_sell_trade(symbol, price)

    else:
        return jsonify({"error": "Invalid action"}), 400

    return jsonify({"message": f"{'Test' if testing else 'Live'} {action} executed for {symbol}"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
