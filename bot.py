from flask import Flask, request, jsonify
from binance.client import Client
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os
import json
from dotenv import load_dotenv

# ✅ Load environment variables before using them
load_dotenv()
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "mysecret")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Binance_Logs")

print(f"[DEBUG] Loaded WEBHOOK_SECRET: {WEBHOOK_SECRET}")

# ✅ Initialize Flask AFTER loading .env
app = Flask(__name__)

# ✅ Print to confirm correct route registration
print(f"[DEBUG] Registering webhook route at /webhook/{WEBHOOK_SECRET}")

# ✅ Setup Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
google_creds_env = os.getenv("GOOGLE_CREDENTIALS")
if not google_creds_env:
    raise Exception("Missing GOOGLE_CREDENTIALS environment variable")

google_creds_json = google_creds_env.encode().decode('unicode_escape')
with open("google_credentials.json", "w") as f:
    f.write(google_creds_json)

creds = ServiceAccountCredentials.from_json_keyfile_name("google_credentials.json", scope)
gsheet_client = gspread.authorize(creds)
sheet = gsheet_client.open(GOOGLE_SHEET_NAME).sheet1

# Ensure sheet header
if sheet.row_count < 2:
    sheet.append_row(["Time", "Action", "Symbol", "Amount (USDT)", "Price", "Quantity", "Testing"])

# ✅ Binance API
client = Client(API_KEY, API_SECRET)

# ✅ Log all requests
@app.before_request
def log_request():
    print(f"[DEBUG] {request.method} {request.path}")

# ✅ Health check
@app.route("/test", methods=["GET"])
def test():
    return "Webhook server is up and running."

# ✅ Webhook endpoint
@app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    data = request.json
    print(f"[DEBUG] Received webhook data: {data}")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        raw_symbol = data.get("symbol", "BTCUSDT").upper()
        symbol = raw_symbol.split(":")[-1]
        action = data.get("action")
        testing = data.get("testing", "no").lower() == "yes"

        # Get price
        ticker = client.get_symbol_ticker(symbol=symbol)
        price = round(float(ticker["price"]), 2)

        if action == "buy":
            usdt_amount = float(data.get("amount", 20))
            qty = round(usdt_amount / price, 6)

            if testing:
                sheet.append_row([now, "BUY", symbol, usdt_amount, price, qty, "YES"])
                return jsonify({"status": "buy test logged", "symbol": symbol, "price": price, "qty": qty})
            else:
                order = client.create_order(
                    symbol=symbol,
                    side=Client.SIDE_BUY,
                    type=Client.ORDER_TYPE_LIMIT,
                    timeInForce=Client.TIME_IN_FORCE_GTC,
                    quantity=qty,
                    price=str(price)
                )
                sheet.append_row([now, "BUY", symbol, usdt_amount, price, qty, "NO"])
                return jsonify({"status": "buy executed", "symbol": symbol, "price": price, "qty": qty})

        elif action == "sell":
            asset = symbol.replace("USDT", "")
            balance = float(client.get_asset_balance(asset=asset)["free"])
            qty = round(balance, 6)

            if qty <= 0:
                return jsonify({"status": "no balance to sell", "symbol": symbol})

            if testing:
                sheet.append_row([now, "SELL", symbol, "ALL", price, qty, "YES"])
                return jsonify({"status": "sell test logged", "symbol": symbol, "price": price, "qty": qty})
            else:
                order = client.create_order(
                    symbol=symbol,
                    side=Client.SIDE_SELL,
                    type=Client.ORDER_TYPE_LIMIT,
                    timeInForce=Client.TIME_IN_FORCE_GTC,
                    quantity=qty,
                    price=str(price)
                )
                sheet.append_row([now, "SELL", symbol, "ALL", price, qty, "NO"])
                return jsonify({"status": "sell executed", "symbol": symbol, "price": price, "qty": qty})

    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)})

    return jsonify({"status": "no valid action"})

# ✅ 404 fallback
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "404 Not Found", "message": str(e)}), 404

# ✅ Run app
if __name__ == '__main__':
    print(f"[INFO] Flask server running at /webhook/{WEBHOOK_SECRET}")
    app.run(host='0.0.0.0', port=10000)
