import os
import json
import time
from datetime import datetime
from flask import Flask, request, jsonify
from binance.client import Client
from oauth2client.service_account import ServiceAccountCredentials
import gspread

# Load environment variables
API_KEY = os.environ.get("BINANCE_API_KEY")
API_SECRET = os.environ.get("BINANCE_API_SECRET")
GOOGLE_CREDENTIALS = os.environ.get("GOOGLE_CREDENTIALS")
SHEET_NAME = os.environ.get("SHEET_NAME", "Binance Bot Log")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "secret123")

if not GOOGLE_CREDENTIALS:
    raise Exception("Missing GOOGLE_CREDENTIALS environment variable")

# Prepare Google Sheets credentials
credentials_dict = json.loads(GOOGLE_CREDENTIALS.replace('\\n', '\n'))
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
gc = gspread.authorize(creds)

# Access the sheet
sh = gc.open(SHEET_NAME)
worksheet = sh.sheet1

# Setup Binance client
client = Client(API_KEY, API_SECRET)

# Create Flask app
app = Flask(__name__)

def log_trade_to_sheet(symbol, action, amount_usdt, price, testing):
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    testing_flag = "Yes" if testing else "No"

    if action == "BUY":
        row = [symbol, timestamp, price, amount_usdt, testing_flag, "", "", "", "No"]
        worksheet.append_row(row)
    elif action == "SELL":
        # Find the latest unmatched BUY
        records = worksheet.get_all_records()
        for i in reversed(range(len(records))):
            row = records[i]
            if row["Symbol"] == symbol and row["Closed (Yes/No)"] != "Yes":
                buy_price = float(row["Buy Price"])
                amount = float(row["Amount"])
                sell_price = float(price)
                profit = round((sell_price - buy_price) * amount / buy_price, 2)

                worksheet.update_cell(i + 2, 6, timestamp)  # Sell Timestamp
                worksheet.update_cell(i + 2, 7, sell_price)  # Sell Price
                worksheet.update_cell(i + 2, 8, profit)  # Profit
                worksheet.update_cell(i + 2, 9, "Yes")  # Closed
                break

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    secret = data.get("secret")
    if secret != WEBHOOK_SECRET:
        return jsonify({"error": "Unauthorized"}), 403

    symbol = data["symbol"]
    side = data["side"].upper()
    amount_usdt = float(data["amount"])
    testing = data.get("testing", False)

    try:
        if side == "BUY":
            order = client.order_market_buy(symbol=symbol, quoteOrderQty=amount_usdt)
            price = float(order["fills"][0]["price"])
            log_trade_to_sheet(symbol, "BUY", amount_usdt, price, testing)

        elif side == "SELL":
            # Get current quantity of the asset
            asset = symbol.replace("USDT", "")
            balance = client.get_asset_balance(asset=asset)
            quantity = float(balance["free"])

            order = client.order_market_sell(symbol=symbol, quantity=quantity)
            price = float(order["fills"][0]["price"])
            log_trade_to_sheet(symbol, "SELL", amount_usdt, price, testing)

        return jsonify({"status": "success", "symbol": symbol, "side": side})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
