from flask import Flask, request, jsonify
from binance.client import Client
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "mysecret")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Binance_Logs")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE")

print(f"[DEBUG] WEBHOOK_SECRET = {WEBHOOK_SECRET}")
print(f"[DEBUG] Using credentials from {GOOGLE_CREDENTIALS_FILE}")

# Setup Google Sheets & Binance client
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDENTIALS_FILE, scope)
gsheet_client = gspread.authorize(creds)
sheet = gsheet_client.open(GOOGLE_SHEET_NAME).sheet1

# Ensure header
expected_header = [
    "Time", "Action", "Symbol", "Amount (USDT)", "Price", "Quantity", "Testing",
    "Sell Time", "Sell Price", "Profit", "Closed"
]
header = sheet.row_values(1)
if header != expected_header:
    sheet.delete_rows(1)
    sheet.insert_row(expected_header, 1)

client = Client(API_KEY, API_SECRET)
app = Flask(__name__)

@app.before_request
def log_request():
    print(f"[DEBUG] {request.method} {request.path}")

@app.route("/test", methods=["GET"])
def test():
    return "Bot is alive."

@app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Debug raw request
    print("[DEBUG] Headers:", dict(request.headers))
    print("[DEBUG] Raw Body:", request.data)

    # Log raw alerts to file
    with open("raw_alerts.log", "a") as log_file:
        log_file.write(f"{now} - {request.data.decode(errors='ignore')}\n")

    try:
        data = request.get_json(force=True)
    except Exception as e:
        print("[ERROR] Failed to parse JSON:", str(e))
        return jsonify({"status": "error", "message": "Invalid JSON"}), 400

    print("[DEBUG] Parsed JSON:", data)

    if not data:
        return jsonify({"status": "error", "message": "No JSON data"}), 400

    try:
        raw_symbol = data.get("symbol", "BTCUSDT").upper()
        symbol = raw_symbol.split(":")[-1].strip()
        action = data.get("action")
        testing = data.get("testing", "no").lower() == "yes"

        # Get current price
        ticker = client.get_symbol_ticker(symbol=symbol)
        price = round(float(ticker["price"]), 6)

        if action == "buy":
            usdt_amount = float(data.get("amount", 20))
            qty = round(usdt_amount / price, 6)

            row = [now, "BUY", symbol, usdt_amount, price, qty, "YES" if testing else "NO", "", "", "", ""]
            sheet.append_row(row)
            return jsonify({"status": "buy logged", "symbol": symbol, "price": price, "qty": qty})

        elif action == "sell":
            # Find matching open BUY
            records = sheet.get_all_records()
            matched_row_index = None
            buy_price = 0
            buy_qty = 0

            for i, row in enumerate(records, start=2):  # start=2 (header is row 1)
                if (
                    row["Symbol"] == symbol and
                    row["Action"] == "BUY" and
                    str(row.get("Closed", "")).strip().upper() != "YES"
                ):
                    matched_row_index = i
                    buy_price = float(row["Price"])
                    buy_qty = float(row["Quantity"])
                    break

            if matched_row_index is None:
                return jsonify({"status": "no matching buy found", "symbol": symbol})

            if testing:
                qty = buy_qty
            else:
                asset = symbol.replace("USDT", "")
                balance = float(client.get_asset_balance(asset=asset)["free"])
                qty = round(balance, 6)
                if qty <= 0:
                    return jsonify({"status": "no balance to sell", "symbol": symbol})

                # Execute real trade
                client.create_order(
                    symbol=symbol,
                    side=Client.SIDE_SELL,
                    type=Client.ORDER_TYPE_LIMIT,
                    timeInForce=Client.TIME_IN_FORCE_GTC,
                    quantity=qty,
                    price=str(price)
                )

            profit = round((price - buy_price) * qty, 2)

            # Update matched buy row
            sheet.update(f"H{matched_row_index}", [[now]])     # Sell Time
            sheet.update(f"I{matched_row_index}", [[price]])   # Sell Price
            sheet.update(f"J{matched_row_index}", [[profit]])  # Profit
            sheet.update(f"K{matched_row_index}", [["YES"]])   # Closed

            return jsonify({
                "status": "sell executed" if not testing else "sell test logged",
                "symbol": symbol,
                "profit": profit,
                "sell_price": price,
                "qty": qty
            })

        else:
            return jsonify({"status": "ignored", "message": "No valid action"})

    except Exception as e:
        print("[ERROR]", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "404 Not Found", "message": str(e)}), 404

if __name__ == '__main__':
    print(f"[INFO] Running Flask app at /webhook/{WEBHOOK_SECRET}")
    app.run(host='0.0.0.0', port=10000)
