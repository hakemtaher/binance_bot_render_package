from flask import Flask, request, jsonify
from binance.client import Client
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os
from dotenv import load_dotenv

# ✅ Load .env
load_dotenv()

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "mysecret")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Binance_Logs")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE")

print(f"[DEBUG] WEBHOOK_SECRET = {WEBHOOK_SECRET}")
print(f"[DEBUG] Using credentials from {GOOGLE_CREDENTIALS_FILE}")

# ✅ Initialize Flask
app = Flask(__name__)

# ✅ Register webhook route after loading secret
@app.before_request
def log_request():
    print(f"[DEBUG] {request.method} {request.path}")

@app.route("/test", methods=["GET"])
def test():
    return "Bot is alive."

@app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    data = request.json
    print(f"[DEBUG] Received webhook: {data}")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        raw_symbol = data.get("symbol", "BTCUSDT").upper()
        symbol = raw_symbol.split(":")[-1]
        action = data.get("action")
        testing = data.get("testing", "no").lower() == "yes"

        # Get current price
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

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "404 Not Found", "message": str(e)}), 404

# ✅ Google Sheets & Binance setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDENTIALS_FILE, scope)
gsheet_client = gspread.authorize(creds)
sheet = gsheet_client.open(GOOGLE_SHEET_NAME).sheet1
if sheet.row_count < 2:
    sheet.append_row(["Time", "Action", "Symbol", "Amount (USDT)", "Price", "Quantity", "Testing"])

client = Client(API_KEY, API_SECRET)

# ✅ Start the server
if __name__ == '__main__':
    print(f"[INFO] Running Flask app at /webhook/{WEBHOOK_SECRET}")
    app.run(host='0.0.0.0', port=10000)
