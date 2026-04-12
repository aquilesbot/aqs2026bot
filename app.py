import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SECRET = os.getenv("WEBHOOK_SECRET", "123456")
BASE_URL = os.getenv("BASE_URL")

def send(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})

@app.route("/")
def home():
    return {"ok": True}

@app.route("/setup-webhook")
def setup():
    url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
    requests.post(url, json={
        "url": f"{BASE_URL}/webhook",
        "secret_token": SECRET
    })
    return {"ok": True}

@app.route("/webhook", methods=["POST"])
def webhook():
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")

    if secret != SECRET:
        return "unauthorized", 401

    data = request.json
    msg = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "")

    if text == "/start":
        send(chat_id, "🤖 Bot online! Use /today")
    elif text == "/today":
        send(chat_id, "⚽ Em breve: análise dos melhores jogos")
    else:
        send(chat_id, "Use /start ou /today")

    return {"ok": True}
