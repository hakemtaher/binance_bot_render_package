import os
import json
from flask import Flask, request, jsonify
from binance.client import Client
from oauth2client.service_account import ServiceAccountCredentials
import gspread
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# --- Binance Setup ---
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
client = Client(API_KEY, API_SECRET)

# --- Flask Setup ---
app = Flask(__name__)

# --- Google Sheets Setup ---
GOOGLE_CREDENTIALS = os.environ.get("GOOGLE_CREDENTIALS")
if not GOOGLE_CREDENTIALS:
    raise Exception("Missing GOOGLE_CREDENTIALS environment variable")

credentials_dict = json.loads(GOOGLE_CREDENTIALS)
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
gc = gspread.authorize(creds)

SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Binance Trade Log")
sheet = gc.open(SHEET_NAME).sheet1

# --- Helper: Find open row by symbol ---
def find_open_trade(symbol):
    records = sheet.get_all_records()
    for idx, row in enumerate(records, start=2):  # sheet1 starts at row 2 for data
        if row['Symbol'] == symbol and row['Closed (Yes/No)'].strip().lower() != 'yes':
            return idx, row
    return None, None

# --- Flask route ---
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()

    # Secret check
    if request.headers.get("X-Webhook-Secret") != WEBHOOK_SECRET:
        return jsonify({"error": "Invalid secret"}), 403

    try:
        symbol = data['symbol']
        action = data['action']
        amount_usdt = float(data['amount'])
        testing = str(data.get('testing', 'no')).lower() == 'yes'
        now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

        # Get current price
        price = float(client.get_symbol_ticker(symbol=symbol)['price'])

        # Calculate quantity (amount in USDT / price)
        quantity = round(amount_usdt / price, 6)

        if action == 'buy':
            if not testing:
                order = client.order_market_buy(symbol=symbol, quantity=quantity)
            sheet.append_row([
                symbol,
                now,
                price,
                amount_usdt,
                "Yes" if testing else "No",
                "", "", "", "No"
            ])
            return jsonify({"status": "buy logged", "testing": testing})

        elif action == 'sell':
            row_idx, buy_row = find_open_trade(symbol)
            if not buy_row:
                return jsonify({"error": "No open buy found for symbol"}), 400

            profit = price - float(buy_row['Buy Price'])
            profit = round(profit * float(buy_row['Amount']) / float(buy_row['Buy Price']), 2)

            if not testing:
                order = client.order_market_sell(symbol=symbol, quantity=quantity)

            sheet.update(f"F{row_idx}:I{row_idx}", [[now, price, profit, "Yes"]])
            return jsonify({"status": "sell logged", "profit": profit, "testing": testing})

        else:
            return jsonify({"error": "Invalid action"}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- Run app ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
