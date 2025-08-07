import time
import hmac
import hashlib
import requests
import logging
import os
import json
from dotenv import load_dotenv

# === LOAD .env CONFIG ===
load_dotenv()

API_KEY = os.getenv('API_KEY')
API_SECRET = os.getenv('API_SECRET')
SYMBOL = os.getenv('SYMBOL')
TARGET_PRICE = float(os.getenv('TARGET_PRICE'))
SPREAD_PERCENT = float(os.getenv('SPREAD_PERCENT'))
ORDER_SIZE = float(os.getenv('ORDER_SIZE'))
PRICE_FLOOR = float(os.getenv('PRICE_FLOOR'))
PRICE_CEIL = float(os.getenv('PRICE_CEIL'))
INCREMENT_STEP = float(os.getenv('INCREMENT_STEP', '0.0001'))
API_BASE = os.getenv('API_BASE')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_USER_IDS = os.getenv('TELEGRAM_USER_IDS').split(',')

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')

def sign(timestamp, method, request_path, body_json=""):
    message = f"{timestamp}{method.upper()}{request_path}{body_json}"
    return hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()

def send_telegram_alert(message):
    for user_id in TELEGRAM_USER_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": user_id.strip(),
                    "text": message,
                    "parse_mode": "Markdown"
                }
            )
        except Exception as e:
            logging.error(f"Telegram error: {e}")

def get_price():
    url = f"{API_BASE}/sapi/v2/ticker"
    try:
        resp = requests.get(url, params={"symbol": SYMBOL})
        data = resp.json()
        if 'last' in data:
            price = float(data['last'])
            send_telegram_alert(f"📊 *{SYMBOL} Price Update:* {price}")
            return price
        logging.warning(f"Unexpected price response: {data}")
    except Exception as e:
        logging.error(f"Price fetch error: {e}")
    return TARGET_PRICE

def get_balance(asset):
    timestamp = str(int(time.time() * 1000))
    signature = sign(timestamp, "GET", "/sapi/v1/account")
    headers = {
        "X-CH-APIKEY": API_KEY,
        "X-CH-TS": timestamp,
        "X-CH-SIGN": signature
    }
    try:
        resp = requests.get(f"{API_BASE}/sapi/v1/account", headers=headers)
        balances = resp.json().get("balances", [])
        for item in balances:
            if item["asset"] == asset:
                return float(item["free"])
    except Exception as e:
        logging.error(f"Balance fetch failed: {e}")
    return 0.0

def place_order(side, price):
    timestamp = str(int(time.time() * 1000))
    body = {
        "symbol": SYMBOL,
        "side": side,
        "type": "LIMIT",
        "timeInForce": "GTC",
        "quantity": ORDER_SIZE,
        "price": f"{price:.6f}"
    }
    body_json = json.dumps(body, separators=(',', ':'))
    signature = sign(timestamp, "POST", "/sapi/v2/order", body_json)
    headers = {
        "X-CH-APIKEY": API_KEY,
        "X-CH-TS": timestamp,
        "X-CH-SIGN": signature,
        "Content-Type": "application/json"
    }
    try:
        resp = requests.post(f"{API_BASE}/sapi/v2/order", headers=headers, data=body_json)
        data = resp.json()
        if "orderId" in data:
            logging.info(f"✅ Placed {side} order at {price}")
        else:
            logging.warning(f"⚠️ Order error: {data}")
    except Exception as e:
        logging.error(f"Error placing {side} order: {e}")

def cancel_all_orders():
    try:
        timestamp = str(int(time.time() * 1000))
        query = f"symbol={SYMBOL}"
        path = f"/sapi/v2/openOrders?{query}"
        signature = sign(timestamp, "GET", path)
        headers = {
            "X-CH-APIKEY": API_KEY,
            "X-CH-TS": timestamp,
            "X-CH-SIGN": signature
        }
        resp = requests.get(f"{API_BASE}/sapi/v2/openOrders", params={"symbol": SYMBOL}, headers=headers)
        orders = resp.json().get("list", [])

        for order in orders:
            cancel_timestamp = str(int(time.time() * 1000))
            cancel_body = {
                "symbol": SYMBOL,
                "orderId": order["orderId"]
            }
            cancel_json = json.dumps(cancel_body, separators=(',', ':'))
            cancel_signature = sign(cancel_timestamp, "POST", "/sapi/v2/cancel", cancel_json)
            cancel_headers = {
                "X-CH-APIKEY": API_KEY,
                "X-CH-TS": cancel_timestamp,
                "X-CH-SIGN": cancel_signature,
                "Content-Type": "application/json"
            }
            resp = requests.post(f"{API_BASE}/sapi/v2/cancel", headers=cancel_headers, data=cancel_json)
            result = resp.json()
            if result.get("status") == "CANCELED":
                logging.info(f"✅ Cancelled Order {order['orderId']}")
            else:
                logging.warning(f"⚠️ Failed to cancel {order['orderId']}: {result}")
    except Exception as e:
        logging.error(f"Error canceling orders: {e}")

def market_maker_loop():
    order_price = get_price()
    send_telegram_alert(f"🚀 Market Maker started for *{SYMBOL}*\nTarget: {TARGET_PRICE}\nStart Price: {order_price}")
    logging.info(f"🎯 Market Maker Started | Target: {TARGET_PRICE} | Start: {order_price}")

    base_asset = SYMBOL[:-4]
    quote_asset = SYMBOL[-4:]

    while True:
        try:
            bid_price = round(order_price * (1 - SPREAD_PERCENT), 6)
            ask_price = round(order_price * (1 + SPREAD_PERCENT), 6)

            cancel_all_orders()
            time.sleep(2)

            base_balance = get_balance(base_asset)
            quote_balance = get_balance(quote_asset)

            required_quote = bid_price * ORDER_SIZE
            required_base = ORDER_SIZE

            if quote_balance >= required_quote:
                place_order("BUY", bid_price)
            else:
                msg = f"❗ Not enough {quote_asset} to BUY: Have {quote_balance:.2f}, need {required_quote:.2f}"
                logging.warning(msg)
                send_telegram_alert(msg)

            time.sleep(2)

            if base_balance >= required_base:
                place_order("SELL", ask_price)
            else:
                msg = f"❗ Not enough {base_asset} to SELL: Have {base_balance:.2f}, need {required_base:.2f}"
                logging.warning(msg)
                send_telegram_alert(msg)

            order_price = round(order_price + INCREMENT_STEP, 6)
            time.sleep(3)

        except Exception as e:
            logging.error(f"Loop error: {e}")
            send_telegram_alert(f"❌ Bot Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    market_maker_loop()
