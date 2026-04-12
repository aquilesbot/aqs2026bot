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


def get_team_strength(team_name):
    team = (team_name or "").lower()

    giants = {
        "real madrid": 96,
        "barcelona": 94,
        "manchester city": 97,
        "arsenal": 90,
        "liverpool": 92,
        "chelsea": 86,
        "manchester united": 84,
        "bayern munich": 95,
        "inter": 90,
        "inter milan": 90,
        "juventus": 87,
        "milan": 86,
        "napoli": 85,
        "psg": 93,
        "flamengo": 88,
        "palmeiras": 89,
        "corinthians": 80,
        "são paulo": 82,
        "santos": 78,
        "botafogo": 83,
        "atlético mineiro": 84,
        "grêmio": 81,
        "internacional": 80,
        "rome": 79,
        "roma": 83,
        "lazio": 82,
        "atalanta": 84,
        "borussia dortmund": 85,
        "atlético madrid": 88,
        "sevilla": 80,
    }

    return giants.get(team, 74)


def league_bonus(league_name):
    league = (league_name or "").lower()

    mapping = {
        "uefa champions league": 30,
        "english premier league": 26,
        "premier league": 26,
        "spanish la liga": 24,
        "la liga": 24,
        "italian serie a": 22,
        "serie a": 22,
        "german bundesliga": 22,
        "bundesliga": 22,
        "french ligue 1": 18,
        "ligue 1": 18,
        "brazilian serie a": 20,
        "brasileirão": 20,
        "copa libertadores": 24,
        "libertadores": 24,
        "copa sudamericana": 16,
        "sudamericana": 16,
    }

    for key, value in mapping.items():
        if key in league:
            return value
    return 10


def predict_match(home, away, league):
    home_strength = get_team_strength(home)
    away_strength = get_team_strength(away)
    bonus = league_bonus(league)

    home_total = home_strength + 3
    away_total = away_strength

    diff = home_total - away_total
    game_score = 50 + bonus + min((home_strength + away_strength) / 4, 25)

    if abs(diff) <= 2:
        prediction = "jogo muito equilibrado"
        suggestion = "duelo aberto, tendência de equilíbrio"
    elif diff > 2:
        prediction = f"leve favoritismo de {home}"
        suggestion = f"{home} tem mais força no confronto"
    else:
        prediction = f"leve favoritismo de {away}"
        suggestion = f"{away} parece mais forte no confronto"

    if game_score >= 95:
        insight = "jogo enorme do dia"
    elif game_score >= 88:
        insight = "confronto muito forte"
    elif game_score >= 78:
        insight = "bom jogo para acompanhar"
    else:
        insight = "jogo interessante do dia"

    return {
        "home_strength": round(home_total, 1),
        "away_strength": round(away_total, 1),
        "score": int(round(game_score)),
        "prediction": prediction,
        "suggestion": suggestion,
        "insight": insight,
    }


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

        analysis = predict_match(home, away, league)

        matches.append(
            {
                "home": home,
                "away": away,
                "league": league,
                "time": event_time[:5] if len(event_time) >= 5 else event_time,
                "score": analysis["score"],
                "prediction": analysis["prediction"],
                "suggestion": analysis["suggestion"],
                "insight": analysis["insight"],
                "home_strength": analysis["home_strength"],
                "away_strength": analysis["away_strength"],
            }
        )

    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches


def format_best_match():
    matches = fetch_today_matches()

    if not matches:
        return "⚠️ Não encontrei jogos de futebol para hoje."

    best = matches[0]

    lines = [
        "🔥 Jogo destaque do dia",
        "",
        f"{best['home']} x {best['away']}",
        f"🏆 {best['league']}",
        f"🕒 {best['time']}",
        f"📊 Nota do jogo: {best['score']}",
        "",
        "🧠 Análise:",
        f"{best['prediction']}. {best['suggestion']}.",
        "",
        f"💡 Leitura rápida: {best['insight']}.",
        "",
        "Use /top para ver mais jogos do dia.",
    ]
    return "\n".join(lines)


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
        lines.append(f"🔮 Previsão: {match['prediction']}")
        lines.append(f"💡 {match['insight']}")
        lines.append("")

    lines.append("Use /best para ver o grande destaque do dia.")
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
        lines.append(f"   🔮 {match['prediction']}")

    return "\n".join(lines)


@app.route("/")
def home():
    return jsonify({"ok": True, "service": "aqs2026bot-pro"})


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
            "🤖 Bot analista online.\n\n"
            "Comandos disponíveis:\n"
            "/today - melhores jogos do dia\n"
            "/top - ranking maior\n"
            "/best - melhor jogo do dia",
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
    elif text == "/best":
        try:
            send(chat_id, format_best_match())
        except Exception:
            send(chat_id, "⚠️ Erro ao gerar o destaque do dia.")
    else:
        send(
            chat_id,
            "Comandos disponíveis:\n/start\n/today\n/top\n/best",
        )

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
