import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ODDS_KEY = os.getenv("ODDSPAPI_KEY")

def send(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})


# 🔥 BUSCAR JOGOS (OddsPapi)
def get_games():
    url = "https://api.oddspapi.io/v4/odds"
    params = {
        "apiKey": ODDS_KEY,
        "sport": "football"
    }

    r = requests.get(url, params=params)
    data = r.json()

    games = []

    for game in data.get("data", [])[:5]:
        home = game.get("homeTeam")
        away = game.get("awayTeam")
        league = game.get("league", "Liga")
        odds = game.get("odds", {})

        home_odd = odds.get("home", "-")
        draw_odd = odds.get("draw", "-")
        away_odd = odds.get("away", "-")

        games.append(
            f"{home} x {away}\n"
            f"🏆 {league}\n"
            f"1: {home_odd} | X: {draw_odd} | 2: {away_odd}\n"
        )

    return games


# 🔥 COMANDOS
def handle(msg):
    text = msg.lower()

    if text == "/start":
        return "🤖 Bot com odds reais online!\n\nUse /odds"

    if text == "/odds":
        games = get_games()

        if not games:
            return "⚠️ Nenhum jogo encontrado"

        return "📊 Jogos com odds:\n\n" + "\n".join(games)

    return "Use /odds"


# 🔥 WEBHOOK
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    if chat_id:
        response = handle(text)
        send(chat_id, response)

    return jsonify({"ok": True})


@app.route("/")
def home():
    return "Bot online"
