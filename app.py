import json
import os
import threading
import time
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
SECRET = os.getenv("WEBHOOK_SECRET", "123456")
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")
TIMEZONE = os.getenv("TIMEZONE", "America/Sao_Paulo")

ODDSPAPI_KEY = os.getenv("ODDSPAPI_KEY", "")
BOOKMAKER = "bet365"

ODDSPAPI_BASE = "https://api.oddspapi.io/v4"
STATE_FILE = Path("/tmp/state.json")

# ------------------ UTIL ------------------

def send(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": chat_id,
        "text": text,
        "reply_markup": reply_markup
    })


def inline_menu():
    return {
        "inline_keyboard": [
            [{"text": "🔥 Jogo do dia", "callback_data": "best"},
             {"text": "💰 Sugestão", "callback_data": "tip"}],
            [{"text": "📈 Odds", "callback_data": "odds"},
             {"text": "📊 Mercados", "callback_data": "markets"}],
            [{"text": "🛡️ Jogos seguros", "callback_data": "safe"},
             {"text": "📋 Ranking", "callback_data": "top"}],
        ]
    }


# ------------------ TEMPO ------------------

def parse_time(utc_str):
    try:
        if utc_str.endswith("Z"):
            dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(utc_str)

        return dt.astimezone(ZoneInfo(TIMEZONE)).strftime("%H:%M")
    except:
        return "??:??"


# ------------------ ODDS API ------------------

def get_odds():
    try:
        url = f"{ODDSPAPI_BASE}/events"
        params = {
            "apiKey": ODDSPAPI_KEY,
            "sport": "soccer",
        }
        r = requests.get(url, params=params, timeout=15)
        data = r.json()

        matches = []

        for e in data[:10]:
            try:
                home = e.get("homeTeam")
                away = e.get("awayTeam")
                league = e.get("competitionName")
                time_str = parse_time(e.get("startTime"))

                odds = e.get("odds", {}).get(BOOKMAKER, {})

                h = odds.get("home")
                d = odds.get("draw")
                a = odds.get("away")

                if not h or not a:
                    continue

                confidence = int(100 / h)

                matches.append({
                    "home": home,
                    "away": away,
                    "league": league,
                    "time": time_str,
                    "odds": (h, d, a),
                    "confidence": confidence,
                    "suggestion": f"Vitória de {home}",
                    "risk": "baixo" if confidence > 70 else "médio"
                })

            except:
                continue

        matches.sort(key=lambda x: x["confidence"], reverse=True)
        return matches

    except Exception as e:
        return []


# ------------------ FORMAT ------------------

def format_best():
    matches = get_odds()
    if not matches:
        return "⚠️ Nenhum jogo encontrado", inline_menu()

    m = matches[0]

    return f"""
🔥 Jogo do dia

{m['home']} x {m['away']}
🏆 {m['league']}
🕒 {m['time']}

🎯 {m['suggestion']}
📌 Assertividade: {m['confidence']}%
⚠️ Risco: {m['risk']}

📈 Odds:
1: {m['odds'][0]} | X: {m['odds'][1]} | 2: {m['odds'][2]}
""", inline_menu()


def format_top():
    matches = get_odds()

    if not matches:
        return "⚠️ Nenhum jogo encontrado", inline_menu()

    txt = "📋 Ranking do dia\n\n"

    for i, m in enumerate(matches[:5], 1):
        txt += f"{i}. {m['home']} x {m['away']}\n"
        txt += f"{m['confidence']}%\n\n"

    return txt, inline_menu()


def format_safe():
    matches = [m for m in get_odds() if m["confidence"] >= 70]

    if not matches:
        return "⚠️ Nenhum jogo seguro", inline_menu()

    txt = "🛡️ Jogos seguros\n\n"

    for m in matches[:5]:
        txt += f"{m['home']} x {m['away']}\n"
        txt += f"{m['confidence']}%\n\n"

    return txt, inline_menu()


def handle(cmd):
    if cmd == "best":
        return format_best()
    if cmd == "top":
        return format_top()
    if cmd == "safe":
        return format_safe()
    if cmd == "odds":
        return format_best()
    if cmd == "markets":
        return "📊 Mercados em breve", inline_menu()

    return "Use /start", inline_menu()


# ------------------ WEBHOOK ------------------

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    if "callback_query" in data:
        cb = data["callback_query"]
        chat_id = cb["message"]["chat"]["id"]
        cmd = cb["data"]

        text, markup = handle(cmd)

        requests.post(f"https://api.telegram.org/bot{TOKEN}/editMessageText", json={
            "chat_id": chat_id,
            "message_id": cb["message"]["message_id"],
            "text": text,
            "reply_markup": markup
        })

        return {"ok": True}

    msg = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "").replace("/", "")

    if text == "start":
        send(chat_id, "🤖 Bot online!", inline_menu())
    else:
        t, m = handle(text)
        send(chat_id, t, m)

    return {"ok": True}


@app.route("/setup-webhook")
def setup():
    url = f"{BASE_URL}/webhook"

    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/setWebhook", json={
        "url": url
    })

    return r.json()


@app.route("/")
def home():
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
