import os
import json
from flask import Flask, request
from binance.client import Client
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# Load Binance API keys from env
BINANCE_API_KEY = os.getenv("API_KEY")
BINANCE_API_SECRET = os.getenv("API_SECRET")
client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

# Load Google Sheet name and credentials
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME")
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS")

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
gc = gspread.authorize(creds)
sheet = gc.open(GOOGLE_SHEET_NAME).sheet1

@app.route('/webhook/<secret>', methods=['POST'])
def webhook(secret):
    try:
        expected_secret = os.getenv("WEBHOOK_SECRET")
        if secret != expected_secret:
            return {"error": "Unauthorized"}, 401

        data = request.json
        print(f"[DEBUG] Incoming Data: {data}")

        symbol = data["symbol"].strip().upper()
        action = data["action"].lower()
        amount = float(data.get("amount", 0))
        testing = data.get("testing", "").upper()

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if action == "buy":
            price = float(client.get_symbol_ticker(symbol=symbol)["price"])
            quantity = round(amount / price, 8)
            sheet.append_row([now, "BUY", symbol, amount, price, quantity, testing, "", "", "", "NO"])
            return {"status": "Buy logged"}, 200

        elif action == "sell":
            row_idx = find_open_buy_row(symbol, testing)
            if not row_idx:
                return {"error": "No open BUY found"}, 404

            buy_row = sheet.row_values(row_idx)
            buy_price = float(buy_row[4])
            buy_amount = float(buy_row[3])
            sell_price = float(client.get_symbol_ticker(symbol=symbol)["price"])
            profit = round(((sell_price - buy_price) * (buy_amount / buy_price)), 2)

            sheet.update(f'H{row_idx}', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            sheet.update(f'I{row_idx}', sell_price)
            sheet.update(f'J{row_idx}', profit)
            sheet.update(f'K{row_idx}', "YES")

            return {"status": "Sell logged", "profit": profit}, 200

        else:
            return {"error": "Unknown action"}, 400

    except Exception as e:
        print("[ERROR]", e)
        return {"error": str(e)}, 500

def find_open_buy_row(symbol, testing):
    records = sheet.get_all_records()
    for idx, row in enumerate(records, start=2):  # data starts from row 2
        if (
            row.get("Symbol") == symbol and
            row.get("Action") == "BUY" and
            row.get("Closed") != "YES" and
            row.get("Testing", "").upper() == testing
        ):
            return idx
    return None

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=10000)
