from flask import Flask, request, jsonify
from binance.client import Client
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os
import json

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "mysecret")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Binance_Logs")
GOOGLE_CREDENTIALS_JSON = json.loads(os.getenv("GOOGLE_CREDENTIALS"))

client = Client(API_KEY, API_SECRET)

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
with open("google_credentials.json", "w") as f:
    json.dump(GOOGLE_CREDENTIALS_JSON, f)
creds = ServiceAccountCredentials.from_json_keyfile_name('google_credentials.json', scope)
gsheet_client = gspread.authorize(creds)
sheet = gsheet_client.open(GOOGLE_SHEET_NAME).sheet1
if sheet.row_count < 2:
    sheet.append_row(["Time", "Action", "Symbol", "Amount (USDT)", "Price", "Quantity"])

app = Flask(__name__)

@app.route(f'/webhook/{WEBHOOK_SECRET}', methods=['POST'])
def webhook():
    data = request.json
    print(f"Received Alert: {data}")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        raw_symbol = data.get("symbol", "BTCUSDT").upper()
        symbol = raw_symbol.split(":")[-1]
        action = data.get("action")

        if action == "buy":
            usdt_amount = float(data.get("amount", 20))
            order = client.create_order(
                symbol=symbol,
                side=Client.SIDE_BUY,
                type=Client.ORDER_TYPE_MARKET,
                quoteOrderQty=usdt_amount
            )
            price = order['fills'][0]['price']
            qty = order['executedQty']
            sheet.append_row([now, "BUY", symbol, usdt_amount, price, qty])
            return jsonify({"status": "buy executed", "symbol": symbol, "price": price, "qty": qty})

        elif action == "sell":
            asset = symbol.replace("USDT", "")
            balance = float(client.get_asset_balance(asset=asset)["free"])
            if balance > 0:
                order = client.create_order(
                    symbol=symbol,
                    side=Client.SIDE_SELL,
                    type=Client.ORDER_TYPE_MARKET,
                    quantity=balance
                )
                price = order['fills'][0]['price']
                qty = order['executedQty']
                sheet.append_row([now, "SELL", symbol, "ALL", price, qty])
                return jsonify({"status": "sell executed", "symbol": symbol, "price": price, "qty": qty})
            else:
                return jsonify({"status": "no balance to sell", "symbol": symbol})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

    return jsonify({"status": "no valid action"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
