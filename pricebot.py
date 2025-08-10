import time
import requests
import logging
import os
from dotenv import load_dotenv

# Load env config
load_dotenv()

API_BASE = os.getenv('API_BASE')
SYMBOL = os.getenv('SYMBOL')
ALERT_PRICE = float(os.getenv('ALERT_PRICE'))  # The price threshold to alert you
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN_PRICE')
TELEGRAM_USER_IDS = os.getenv('TELEGRAM_USER_IDS').split(',')

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')

def send_telegram_alert(message):
    for user_id in TELEGRAM_USER_IDS:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": user_id.strip(),
            "text": message,
            "parse_mode": "Markdown"
        }
        try:
            requests.post(url, json=payload)
        except Exception as e:
            logging.error(f"Telegram error: {e}")

def get_price():
    try:
        url = f"{API_BASE}/sapi/v2/ticker"
        params = {"symbol": SYMBOL}
        resp = requests.get(url, params=params)
        data = resp.json()
        if 'last' in data:
            return float(data['last'])
        else:
            logging.warning(f"Unexpected price response: {data}")
            return None
    except Exception as e:
        logging.error(f"Price fetch error: {e}")
        return None

def price_alert_loop():
    alerted = False
    while True:
        price = get_price()
        if price is None:
            logging.warning("Price fetch returned None, retrying...")
        else:
            logging.info(f"Current price for {SYMBOL}: {price}")
            if price < ALERT_PRICE and not alerted:
                message = f"⚠️ Price alert! {SYMBOL} dropped below {ALERT_PRICE}. Current price: {price}"
                logging.info(message)
                send_telegram_alert(message)
                alerted = True
            elif price >= ALERT_PRICE and alerted:
                # Reset alert if price goes back above alert price
                alerted = False
        time.sleep(60)

if __name__ == "__main__":
    try:
        price_alert_loop()
    except KeyboardInterrupt:
        logging.info("Price alert bot stopped manually.")