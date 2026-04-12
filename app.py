import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
SECRET = os.getenv("WEBHOOK_SECRET", "123456")
BASE_URL = os.getenv("BASE_URL", "")


def send(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
        },
        timeout=30,
    )


def get_mock_matches():
    return [
        {
            "home": "Flamengo",
            "away": "Palmeiras",
            "league": "Brasileirão Série A",
            "time": "16:00",
            "score": 9.4,
            "insight": "grande jogo entre equipes fortes e equilibradas",
        },
        {
            "home": "Manchester City",
            "away": "Arsenal",
            "league": "Premier League",
            "time": "12:30",
            "score": 9.1,
            "insight": "partida de altíssimo nível técnico",
        },
        {
            "home": "Real Madrid",
            "away": "Barcelona",
            "league": "La Liga",
            "time": "17:00",
            "score": 9.8,
            "insight": "clássico enorme com muita relevância",
        },
        {
            "home": "Inter",
            "away": "Juventus",
            "league": "Serie A",
            "time": "15:45",
            "score": 8.7,
            "insight": "jogo forte e competitivo",
        },
        {
            "home": "Botafogo",
            "away": "Atlético Mineiro",
            "league": "Brasileirão Série A",
            "time": "18:30",
            "score": 8.3,
            "insight": "bom confronto para acompanhar",
        },
    ]


def format_top_matches(limit=3):
    matches = get_mock_matches()
    matches = sorted(matches, key=lambda x: x["score"], reverse=True)[:limit]

    lines = ["⚽ Melhores jogos do dia", ""]
    for i, match in enumerate(matches, start=1):
        lines.append(f"{i}. {match['home']} x {match['away']}")
        lines.append(f"🏆 {match['league']}")
        lines.append(f"🕒 {match['time']}")
        lines.append(f"📊 Nota: {match['score']}")
        lines.append(f"💡 {match['insight']}")
        lines.append("")

    lines.append("Use /top para ver uma lista maior.")
    return "\n".join(lines)


def format_full_list():
    matches = get_mock_matches()
    matches = sorted(matches, key=lambda x: x["score"], reverse=True)

    lines = ["📋 Top jogos do dia", ""]
    for i, match in enumerate(matches, start=1):
        lines.append(
            f"{i}. {match['home']} x {match['away']} | {match['league']} | {match['time']} | Nota {match['score']}"
        )

    return "\n".join(lines)


@app.route("/")
def home():
    return jsonify({"ok": True, "service": "aqs2026bot"})


@app.route("/setup-webhook")
def setup():
    url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
    response = requests.post(
        url,
        json={
            "url": f"{BASE_URL}/webhook",
            "secret_token": SECRET,
            "drop_pending_updates": True,
        },
        timeout=30,
    )
    return jsonify(response.json())


@app.route("/webhook", methods=["POST"])
def webhook():
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if secret != SECRET:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    msg = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip().lower()

    if not chat_id:
        return jsonify({"ok": True})

    if text == "/start":
        send(
            chat_id,
            "🤖 Bot online.\n\nComandos disponíveis:\n/today - melhores jogos do dia\n/top - ranking completo",
        )
    elif text == "/today":
        send(chat_id, format_top_matches(limit=3))
    elif text == "/top":
        send(chat_id, format_full_list())
    else:
        send(
            chat_id,
            "Comandos disponíveis:\n/start\n/today\n/top",
        )

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
