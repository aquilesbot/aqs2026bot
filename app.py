import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
SECRET = os.getenv("WEBHOOK_SECRET", "123456")
BASE_URL = os.getenv("BASE_URL", "")
TIMEZONE = os.getenv("TIMEZONE", "America/Sao_Paulo")

SPORTSDB_KEY = os.getenv("SPORTSDB_KEY", "123")
SPORTSDB_URL = f"https://www.thesportsdb.com/api/v1/json/{SPORTSDB_KEY}"


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


def get_today_date():
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d")


def score_match(event):
    league = (event.get("strLeague") or "").lower()
    home = event.get("strHomeTeam") or "Time A"
    away = event.get("strAwayTeam") or "Time B"

    score = 50

    big_leagues = {
        "uefa champions league": 40,
        "premier league": 32,
        "la liga": 30,
        "serie a": 28,
        "bundesliga": 28,
        "ligue 1": 24,
        "brazilian serie a": 26,
        "brasileirão": 26,
        "libertadores": 30,
        "sudamericana": 20,
    }

    for key, bonus in big_leagues.items():
        if key in league:
            score += bonus
            break

    giant_clubs = {
        "real madrid", "barcelona", "manchester city", "arsenal", "liverpool",
        "manchester united", "chelsea", "bayern munich", "inter", "juventus",
        "milan", "psg", "flamengo", "palmeiras", "corinthians", "são paulo",
        "santos", "botafogo", "atlético mineiro", "grêmio", "internacional"
    }

    if home.lower() in giant_clubs:
        score += 8
    if away.lower() in giant_clubs:
        score += 8

    if score >= 95:
        insight = "jogo enorme do dia"
    elif score >= 85:
        insight = "confronto muito forte"
    elif score >= 75:
        insight = "bom jogo para acompanhar"
    else:
        insight = "jogo interessante do dia"

    return score, insight


def fetch_today_matches():
    date_str = get_today_date()
    url = f"{SPORTSDB_URL}/eventsday.php"
    params = {
        "d": date_str,
        "s": "Soccer",
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    events = data.get("events") or []

    matches = []
    for event in events:
        home = event.get("strHomeTeam")
        away = event.get("strAwayTeam")
        league = event.get("strLeague")
        event_time = event.get("strTime") or "Sem horário"

        if not home or not away or not league:
            continue

        score, insight = score_match(event)

        matches.append(
            {
                "home": home,
                "away": away,
                "league": league,
                "time": event_time[:5] if len(event_time) >= 5 else event_time,
                "score": score,
                "insight": insight,
            }
        )

    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches


def format_top_matches(limit=5):
    matches = fetch_today_matches()[:limit]

    if not matches:
        return "⚠️ Não encontrei jogos de futebol para hoje."

    lines = ["⚽ Melhores jogos reais do dia", ""]
    for i, match in enumerate(matches, start=1):
        lines.append(f"{i}. {match['home']} x {match['away']}")
        lines.append(f"🏆 {match['league']}")
        lines.append(f"🕒 {match['time']}")
        lines.append(f"📊 Nota: {match['score']}")
        lines.append(f"💡 {match['insight']}")
        lines.append("")

    lines.append("Use /top para ver uma lista maior.")
    return "\n".join(lines)


def format_full_list(limit=12):
    matches = fetch_today_matches()[:limit]

    if not matches:
        return "⚠️ Não encontrei jogos de futebol para hoje."

    lines = ["📋 Top jogos reais de hoje", ""]
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
            "🤖 Bot online.\n\nComandos disponíveis:\n/today - melhores jogos reais do dia\n/top - ranking maior",
        )
    elif text == "/today":
        try:
            send(chat_id, format_top_matches(limit=5))
        except Exception:
            send(chat_id, "⚠️ Erro ao buscar jogos reais de hoje.")
    elif text == "/top":
        try:
            send(chat_id, format_full_list(limit=12))
        except Exception:
            send(chat_id, "⚠️ Erro ao montar o ranking de jogos.")
    else:
        send(chat_id, "Comandos disponíveis:\n/start\n/today\n/top")

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
