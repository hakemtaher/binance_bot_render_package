from flask import Flask, request, jsonify
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from binance.client import Client
from binance.exceptions import BinanceAPIException

import os

# Load sensitive credentials from environment or .env
BINANCE_API_KEY = os.getenv("API_KEY")
BINANCE_API_SECRET = os.getenv("API_SECRET")
GOOGLE_CREDENTIALS = json.loads(os.getenv("GOOGLE_CREDENTIALS"))
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Binance_Logs")

# Binance client
client_binance = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

# Google Sheets setup
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
credentials = ServiceAccountCredentials.from_json_keyfile_dict(GOOGLE_CREDENTIALS, scope)
gc = gspread.authorize(credentials)
sheet = gc.open(GOOGLE_SHEET_NAME).sheet1

app = Flask(__name__)

@app.route('/webhook/<secret>', methods=['POST'])
def webhook(secret):
    print("[DEBUG] POST /webhook/" + secret)
    print("[DEBUG] Headers:", dict(request.headers))
    raw_body = request.data
    print("[DEBUG] Raw Body:", raw_body)

    try:
        data = json.loads(raw_body)
        print("[DEBUG] Parsed JSON:", data)
    except Exception as e:
        print("[ERROR] JSON decode failed:", e)
        return "Invalid JSON", 400

    symbol = data.get("symbol", "").strip().upper()
    action = data.get("action", "").strip().lower()
    testing = data.get("testing", "").strip().lower()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        if action == "buy":
            usdt_amount = float(data["amount"])
            price = float(client_binance.get_symbol_ticker(symbol=symbol)["price"])
            quantity = round(usdt_amount / price, 6)

            row = [now, "BUY", symbol, usdt_amount, round(price, 2), quantity, testing.upper(), "", "", "", "NO"]
            sheet.append_row(row)
            print(f"[SUCCESS] BUY logged for {symbol}")
            return jsonify({"status": "buy logged"}), 200

        elif action == "sell":
            price = float(client_binance.get_symbol_ticker(symbol=symbol)["price"])
            all_records = sheet.get_all_records()

            for i in reversed(range(len(all_records))):
                row = all_records[i]
                if row["Symbol"].strip().upper() == symbol and row["Closed"].strip().upper() == "NO":
                    buy_price = float(row["Price"])
                    quantity = float(row["Quantity"])
                    profit = round((price - buy_price) * quantity, 2)

                    sheet.update_cell(i + 2, 8, now)       # Sell Time
                    sheet.update_cell(i + 2, 9, price)     # Sell Price
                    sheet.update_cell(i + 2, 10, profit)   # Profit
                    sheet.update_cell(i + 2, 11, "YES")    # Closed
                    print(f"[SUCCESS] SELL matched for {symbol}, profit: {profit}")
                    return jsonify({"status": "sell matched"}), 200

            print(f"[WARNING] No open BUY found for {symbol}")
            return jsonify({"error": "No open BUY found"}), 404

        else:
            print("[ERROR] Unknown action:", action)
            return jsonify({"error": "Invalid action"}), 400

    except BinanceAPIException as e:
        print("[ERROR] Binance API error:", e)
        return jsonify({"error": str(e)}), 500

    except Exception as e:
        print("[ERROR] General Exception:", e)
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
