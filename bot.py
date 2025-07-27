import os
import json
import time
from flask import Flask, request, jsonify
from binance.client import Client
from binance.exceptions import BinanceAPIException
from oauth2client.service_account import ServiceAccountCredentials
import gspread
from datetime import datetime

app = Flask(__name__)

# Load environment variables
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME")
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS")  # path to JSON file

# Setup Binance client
client = Client(API_KEY, API_SECRET)

# Setup Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
gc = gspread.authorize(creds)
sheet = gc.open(GOOGLE_SHEET_NAME).sheet1

# Helper to log to sheet
def log_trade(data):
    sheet.append_row(data)

# Store buy orders to match with sells
open_trades = []

@app.route('/webhook/<secret>', methods=['POST'])
def webhook(secret):
    if secret != WEBHOOK_SECRET:
        return jsonify({"error": "Unauthorized"}), 403

    try:
        data = request.get_json(force=True)
        print(f"[DEBUG] Webhook Received: {data}")

        symbol = data["symbol"].strip().upper()
        action = data["action"].lower()
        amount = float(data.get("amount", 100))
        testing = data.get("testing", "yes").upper()

        price = float(client.get_symbol_ticker(symbol=symbol)['price'])
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if action == "buy":
            quantity = round(amount / price, 8)
            open_trades.append({
                "symbol": symbol,
                "amount": amount,
                "price": price,
                "quantity": quantity,
                "timestamp": timestamp,
                "testing": testing
            })
            log_trade([timestamp, "BUY", symbol, amount, price, quantity, testing, "", "", "", "NO"])

        elif action == "sell":
            for i, trade in enumerate(open_trades):
                if trade["symbol"] == symbol and trade["testing"] == testing:
                    buy_price = trade["price"]
                    quantity = trade["quantity"]
                    profit = round((price - buy_price) * quantity, 2)
                    sell_time = timestamp

                    log_trade([
                        trade["timestamp"], "BUY", trade["symbol"], trade["amount"],
                        trade["price"], trade["quantity"], trade["testing"],
                        sell_time, price, profit, "YES"
                    ])

                    del open_trades[i]
                    break

        return jsonify({"status": "success"}), 200

    except BinanceAPIException as e:
        print(f"[ERROR] Binance API Error: {e}")
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        print(f"[ERROR] General Exception: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=10000)
