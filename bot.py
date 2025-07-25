import os
import json
from flask import Flask, request, abort
from binance.client import Client
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Binance credentials
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
client = Client(API_KEY, API_SECRET)

# Webhook secret
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

# Google Sheets setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
credentials_path = os.getenv("GOOGLE_CREDENTIALS")
if not credentials_path:
    raise Exception("Missing GOOGLE_CREDENTIALS environment variable")
creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_path, scope)
gs_client = gspread.authorize(creds)
sheet = gs_client.open("Binance Trades").sheet1

# Helper: insert row
def insert_buy_row(data):
    row = [
        data["symbol"],
        data["timestamp"],
        data["buy_price"],
        data["usdt_amount"],
        data["testing"],
        "", "", "", "No"
    ]
    sheet.append_row(row)
    return sheet.row_count  # Return the row number

def update_sell(row_number, sell_price, sell_timestamp):
    buy_price = float(sheet.cell(row_number, 3).value)
    usdt_amount = float(sheet.cell(row_number, 4).value)
    amount = usdt_amount / buy_price
    sell_total = amount * float(sell_price)
    profit = sell_total - usdt_amount
    sheet.update(f"F{row_number}", sell_timestamp)
    sheet.update(f"G{row_number}", sell_price)
    sheet.update(f"H{row_number}", round(profit, 2))
    sheet.update(f"I{row_number}", "Yes")

# Webhook endpoint
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get("X-Webhook-Secret") != WEBHOOK_SECRET:
        abort(403)

    data = request.get_json()
    symbol = data.get("symbol")
    action = data.get("action")
    usdt_amount = float(data.get("amount", 0))
    testing = str(data.get("testing", "no")).lower()
    testing_flag = "Yes" if testing == "yes" else "No"
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    try:
        price_data = client.get_symbol_ticker(symbol=symbol)
        price = float(price_data["price"])
    except Exception as e:
        return {"error": f"Price fetch error: {str(e)}"}, 500

    if action == "buy":
        row_data = {
            "symbol": symbol,
            "timestamp": timestamp,
            "buy_price": price,
            "usdt_amount": usdt_amount,
            "testing": testing_flag
        }

        row_number = insert_buy_row(row_data)

        if testing_flag == "No":
            quantity = round(usdt_amount / price, 5)
            try:
                client.order_market_buy(symbol=symbol, quantity=quantity)
            except Exception as e:
                return {"error": f"Buy failed: {str(e)}"}, 500

        return {"status": "Buy recorded", "row": row_number}, 200

    elif action == "sell":
        records = sheet.get_all_values()
        for idx, row in reversed(list(enumerate(records[1:], start=2))):
            if row[0] == symbol and row[8] != "Yes" and row[4] == testing_flag:
                update_sell(idx, price, timestamp)
                if testing_flag == "No":
                    try:
                        amount = float(row[3]) / float(row[2])
                        quantity = round(amount, 5)
                        client.order_market_sell(symbol=symbol, quantity=quantity)
                    except Exception as e:
                        return {"error": f"Sell failed: {str(e)}"}, 500
                return {"status": "Sell recorded", "row": idx}, 200

        return {"error": "No matching open buy found"}, 404

    return {"error": "Invalid action"}, 400

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)
