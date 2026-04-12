import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
SECRET = os.getenv("WEBHOOK_SECRET", "123456")
BASE_URL = os.getenv("BASE_URL", "")
TIMEZONE = os.getenv("TIMEZONE", "America/Sao_Paulo")
SPORTSDB_KEY = os.getenv("SPORTSDB_KEY", "123")
ALERT_HOUR = int(os.getenv("ALERT_HOUR", "9"))

SPORTSDB_URL = f"https://www.thesportsdb.com/api/v1/json/{SPORTSDB_KEY}"
STATE_FILE = Path("/tmp/aqs2026bot_state.json")

BIG_LEAGUES = {
    "english premier league",
    "premier league",
    "uefa champions league",
    "spanish la liga",
    "la liga",
    "italian serie a",
    "serie a",
    "german bundesliga",
    "bundesliga",
    "french ligue 1",
    "ligue 1",
    "brazilian serie a",
    "brasileirão",
    "campeonato brasileiro série a",
    "copa libertadores",
    "libertadores",
    "copa sudamericana",
    "sudamericana",
}

TEAM_STRENGTH = {
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
    "gremio": 81,
    "grêmio": 81,
    "internacional": 80,
    "roma": 83,
    "lazio": 82,
    "atalanta": 84,
    "borussia dortmund": 85,
    "atlético madrid": 88,
    "atletico madrid": 88,
    "sevilla": 80,
    "newcastle": 82,
    "tottenham": 84,
    "aston villa": 81,
}

started_scheduler = False


def load_state():
    if not STATE_FILE.exists():
        return {
            "chat_id": None,
            "alerts_enabled": False,
            "last_alert_date": None,
        }
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {
            "chat_id": None,
            "alerts_enabled": False,
            "last_alert_date": None,
        }


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


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


def now_local():
    return datetime.now(ZoneInfo(TIMEZONE))


def get_today_date():
    return now_local().strftime("%Y-%m-%d")


def normalize(text):
    return (text or "").strip().lower()


def is_big_league(league_name):
    league = normalize(league_name)
    return any(key in league for key in BIG_LEAGUES)


def get_team_strength(team_name):
    return TEAM_STRENGTH.get(normalize(team_name), 74)


def league_bonus(league_name):
    league = normalize(league_name)

    mapping = {
        "uefa champions league": 32,
        "english premier league": 27,
        "premier league": 27,
        "spanish la liga": 25,
        "la liga": 25,
        "italian serie a": 23,
        "serie a": 23,
        "german bundesliga": 22,
        "bundesliga": 22,
        "french ligue 1": 18,
        "ligue 1": 18,
        "brazilian serie a": 21,
        "brasileirão": 21,
        "copa libertadores": 25,
        "libertadores": 25,
        "copa sudamericana": 16,
        "sudamericana": 16,
    }

    for key, value in mapping.items():
        if key in league:
            return value
    return 10


def predict_match(home, away, league):
    home_strength = get_team_strength(home) + 3
    away_strength = get_team_strength(away)
    bonus = league_bonus(league)

    diff = home_strength - away_strength
    raw_score = 50 + bonus + min((home_strength + away_strength) / 4, 25)
    game_score = int(round(min(raw_score, 99)))

    if abs(diff) <= 2:
        prediction = "jogo muito equilibrado"
        suggestion = "mercado mais seguro: evitar vencedor seco"
        tip = "equilíbrio alto, tendência de jogo duro"
        risk = "alto"
    elif diff > 2 and diff <= 6:
        prediction = f"leve favoritismo de {home}"
        suggestion = f"{home} ou empate"
        tip = f"{home} chega ligeiramente melhor"
        risk = "médio"
    elif diff > 6:
        prediction = f"favoritismo claro de {home}"
        suggestion = f"vitória de {home}"
        tip = f"{home} tem vantagem técnica no confronto"
        risk = "médio"
    elif diff < -2 and diff >= -6:
        prediction = f"leve favoritismo de {away}"
        suggestion = f"{away} ou empate"
        tip = f"{away} parece mais forte no confronto"
        risk = "médio"
    else:
        prediction = f"favoritismo claro de {away}"
        suggestion = f"vitória de {away}"
        tip = f"{away} tem vantagem técnica no confronto"
        risk = "médio"

    if game_score >= 95:
        insight = "jogo enorme do dia"
    elif game_score >= 88:
        insight = "confronto muito forte"
    elif game_score >= 78:
        insight = "bom jogo para acompanhar"
    else:
        insight = "jogo interessante do dia"

    return {
        "score": game_score,
        "prediction": prediction,
        "suggestion": suggestion,
        "tip": tip,
        "risk": risk,
        "insight": insight,
        "home_strength": round(home_strength, 1),
        "away_strength": round(away_strength, 1),
    }


def fetch_today_matches():
    url = f"{SPORTSDB_URL}/eventsday.php"
    params = {
        "d": get_today_date(),
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
        if not is_big_league(league):
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
                "tip": analysis["tip"],
                "risk": analysis["risk"],
                "insight": analysis["insight"],
            }
        )

    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches


def format_best_match():
    matches = fetch_today_matches()
    if not matches:
        return "⚠️ Não encontrei jogos grandes para hoje."

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
        f"{best['prediction']}. {best['tip']}.",
        "",
        f"💡 Leitura rápida: {best['insight']}.",
        "",
        f"🎯 Sugestão: {best['suggestion']}",
        f"⚠️ Risco: {best['risk']}",
    ]
    return "\n".join(lines)


def format_tip():
    matches = fetch_today_matches()
    if not matches:
        return "⚠️ Não encontrei jogos grandes para hoje."

    best = matches[0]
    lines = [
        "💰 Sugestão do dia",
        "",
        f"{best['home']} x {best['away']}",
        f"🏆 {best['league']}",
        f"🕒 {best['time']}",
        "",
        f"📌 Entrada sugerida: {best['suggestion']}",
        f"🧠 Justificativa: {best['prediction']}. {best['tip']}.",
        f"⚠️ Risco: {best['risk']}",
    ]
    return "\n".join(lines)


def format_top_matches(limit=5):
    matches = fetch_today_matches()[:limit]
    if not matches:
        return "⚠️ Não encontrei jogos grandes para hoje."

    lines = ["⚽ Melhores jogos grandes do dia", ""]
    for i, match in enumerate(matches, start=1):
        lines.append(f"{i}. {match['home']} x {match['away']}")
        lines.append(f"🏆 {match['league']}")
        lines.append(f"🕒 {match['time']}")
        lines.append(f"📊 Nota: {match['score']}")
        lines.append(f"🔮 Previsão: {match['prediction']}")
        lines.append(f"🎯 Sugestão: {match['suggestion']}")
        lines.append("")

    lines.append("Use /best para o destaque e /tip para a sugestão do dia.")
    return "\n".join(lines)


def format_full_list(limit=12):
    matches = fetch_today_matches()[:limit]
    if not matches:
        return "⚠️ Não encontrei jogos grandes para hoje."

    lines = ["📋 Top jogos grandes de hoje", ""]
    for i, match in enumerate(matches, start=1):
        lines.append(
            f"{i}. {match['home']} x {match['away']} | {match['league']} | {match['time']} | Nota {match['score']}"
        )
        lines.append(f"   🔮 {match['prediction']}")
        lines.append(f"   🎯 {match['suggestion']}")

    return "\n".join(lines)


def send_daily_alert_if_needed():
    state = load_state()
    chat_id = state.get("chat_id")
    alerts_enabled = state.get("alerts_enabled", False)
    last_alert_date = state.get("last_alert_date")

    if not chat_id or not alerts_enabled:
        return

    now = now_local()
    today = now.strftime("%Y-%m-%d")

    if now.hour != ALERT_HOUR:
        return

    if last_alert_date == today:
        return

    try:
        text = format_best_match()
        send(chat_id, text)
        state["last_alert_date"] = today
        save_state(state)
    except Exception:
        pass


def scheduler_loop():
    while True:
        try:
            send_daily_alert_if_needed()
        except Exception:
            pass
        time.sleep(60)


def start_scheduler_once():
    global started_scheduler
    if started_scheduler:
        return
    started_scheduler = True
    thread = threading.Thread(target=scheduler_loop, daemon=True)
    thread.start()


@app.before_request
def ensure_scheduler():
    start_scheduler_once()


@app.route("/")
def home():
    return jsonify({"ok": True, "service": "aqs2026bot-pro-max"})


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

    state = load_state()
    state["chat_id"] = chat_id
    save_state(state)

    if text == "/start":
        send(
            chat_id,
            "🤖 Bot analista PRO online.\n\n"
            "Comandos disponíveis:\n"
            "/today - melhores jogos do dia\n"
            "/top - ranking maior\n"
            "/best - melhor jogo do dia\n"
            "/tip - sugestão do dia\n"
            "/alert_on - ativar alerta automático\n"
            "/alert_off - desativar alerta automático\n"
            "/status - ver status do alerta",
        )
    elif text == "/today":
        try:
            send(chat_id, format_top_matches(limit=5))
        except Exception:
            send(chat_id, "⚠️ Erro ao buscar jogos de hoje.")
    elif text == "/top":
        try:
            send(chat_id, format_full_list(limit=12))
        except Exception:
            send(chat_id, "⚠️ Erro ao montar o ranking.")
    elif text == "/best":
        try:
            send(chat_id, format_best_match())
        except Exception:
            send(chat_id, "⚠️ Erro ao gerar o destaque do dia.")
    elif text == "/tip":
        try:
            send(chat_id, format_tip())
        except Exception:
            send(chat_id, "⚠️ Erro ao gerar a sugestão do dia.")
    elif text == "/alert_on":
        state["alerts_enabled"] = True
        save_state(state)
        send(chat_id, f"✅ Alerta automático ativado para {ALERT_HOUR}:00.")
    elif text == "/alert_off":
        state["alerts_enabled"] = False
        save_state(state)
        send(chat_id, "⛔ Alerta automático desativado.")
    elif text == "/status":
        send(
            chat_id,
            "📌 Status do bot\n\n"
            f"Alertas: {'ativados' if state.get('alerts_enabled') else 'desativados'}\n"
            f"Hora do alerta: {ALERT_HOUR}:00\n"
            f"Timezone: {TIMEZONE}",
        )
    else:
        send(
            chat_id,
            "Comandos disponíveis:\n/start\n/today\n/top\n/best\n/tip\n/alert_on\n/alert_off\n/status",
        )

    return jsonify({"ok": True})


if __name__ == "__main__":
    start_scheduler_once()
    app.run(host="0.0.0.0", port=10000)
