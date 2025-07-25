from flask import Flask, request, jsonify
from binance.client import Client
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os

app = Flask(__name__)

# Environment variables
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

# Validate essential variables
if not GOOGLE_CREDENTIALS:
    raise Exception("Missing GOOGLE_CREDENTIALS environment variable")
if not WEBHOOK_SECRET:
    raise Exception("Missing WEBHOOK_SECRET environment variable")

# Google Sheets setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
credentials_path = "/tmp/google_creds.json"
with open(credentials_path, "w") as f:
    f.write(GOOGLE_CREDENTIALS)
creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_path, scope)
client = gspread.authorize(creds)
sheet = client.open("Binance Trades Log").sheet1

# Binance client
binance = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    if not data or data.get("secret") != WEBHOOK_SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    symbol = data.get("symbol")
    action = data.get("action")
    usdt_amount = float(data.get("amount"))
    testing = data.get("testing", "no").lower() == "yes"

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    if action not in ["buy", "sell"]:
        return jsonify({"error": "Invalid action"}), 400

    price = get_price(symbol)
    if price is None:
        return jsonify({"error": "Failed to fetch price"}), 500

    quantity = round(usdt_amount / price, 6)

    if testing:
        log_trade(symbol, now, action, price, usdt_amount, testing=True)
        return jsonify({"message": "Logged test action"}), 200

    try:
        if action == "buy":
            order = binance.create_order(symbol=symbol, side="BUY", type="MARKET", quoteOrderQty=usdt_amount)
            log_trade(symbol, now, "buy", price, usdt_amount, testing=False)
        elif action == "sell":
            order = binance.create_order(symbol=symbol, side="SELL", type="MARKET", quantity=quantity)
            log_trade(symbol, now, "sell", price, usdt_amount, testing=False)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"message": f"{action.upper()} executed"}), 200

def get_price(symbol):
    try:
        ticker = binance.get_symbol_ticker(symbol=symbol)
        return float(ticker["price"])
    except:
        return None

def log_trade(symbol, timestamp, action, price, amount, testing):
    rows = sheet.get_all_values()
    header = rows[0] if rows else []
    matched_row_index = None

    for idx, row in enumerate(rows[1:], start=2):  # Skip header
        if row[0] == symbol and row[8] != "Yes":  # "Closed" column
            matched_row_index = idx
            break

    if action == "buy" or matched_row_index is None:
        sheet.append_row([
            symbol, timestamp, price, amount, "Yes" if testing else "No", "", "", "", "No"
        ])
    else:
        row = sheet.row_values(matched_row_index)
        profit = (float(price) - float(row[2])) * float(row[3])
        sheet.update(f"F{matched_row_index}", timestamp)
        sheet.update(f"G{matched_row_index}", price)
        sheet.update(f"H{matched_row_index}", round(profit, 2))
        sheet.update(f"I{matched_row_index}", "Yes")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
