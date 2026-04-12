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
    "uefa champions league",
    "english premier league",
    "premier league",
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
    "real madrid": 97,
    "barcelona": 94,
    "manchester city": 98,
    "arsenal": 92,
    "liverpool": 93,
    "chelsea": 85,
    "manchester united": 83,
    "newcastle": 82,
    "tottenham": 84,
    "aston villa": 81,
    "bayern munich": 96,
    "borussia dortmund": 86,
    "inter": 91,
    "inter milan": 91,
    "juventus": 87,
    "milan": 86,
    "napoli": 86,
    "roma": 83,
    "lazio": 82,
    "atalanta": 84,
    "psg": 93,
    "atletico madrid": 89,
    "atlético madrid": 89,
    "sevilla": 80,
    "flamengo": 89,
    "palmeiras": 90,
    "botafogo": 84,
    "atlético mineiro": 84,
    "atletico mineiro": 84,
    "corinthians": 80,
    "são paulo": 82,
    "santos": 78,
    "grêmio": 81,
    "gremio": 81,
    "internacional": 80,
}

started_scheduler = False


def load_state():
    if not STATE_FILE.exists():
        return {"chat_id": None, "alerts_enabled": False, "last_alert_date": None}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"chat_id": None, "alerts_enabled": False, "last_alert_date": None}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def telegram_post(method, payload):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    return requests.post(url, json=payload, timeout=30)


def send(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    telegram_post("sendMessage", payload)


def edit_message(chat_id, message_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    telegram_post("editMessageText", payload)


def answer_callback(callback_id, text=""):
    telegram_post("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def inline_menu():
    return {
        "inline_keyboard": [
            [
                {"text": "🔥 Jogo do dia", "callback_data": "best"},
                {"text": "💰 Sugestão", "callback_data": "tip"},
            ],
            [
                {"text": "⚽ Hoje", "callback_data": "today"},
                {"text": "📋 Ranking", "callback_data": "top"},
            ],
            [
                {"text": "🛡️ Jogos seguros", "callback_data": "safe"},
            ],
            [
                {"text": "🔔 Ativar alerta", "callback_data": "alert_on"},
                {"text": "⛔ Desativar alerta", "callback_data": "alert_off"},
            ],
            [
                {"text": "📌 Status", "callback_data": "status"},
            ],
        ]
    }


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
        "uefa champions league": 36,
        "english premier league": 29,
        "premier league": 29,
        "spanish la liga": 26,
        "la liga": 26,
        "italian serie a": 24,
        "serie a": 24,
        "german bundesliga": 23,
        "bundesliga": 23,
        "french ligue 1": 18,
        "ligue 1": 18,
        "brazilian serie a": 22,
        "brasileirão": 22,
        "copa libertadores": 26,
        "libertadores": 26,
        "copa sudamericana": 16,
        "sudamericana": 16,
    }
    for key, value in mapping.items():
        if key in league:
            return value
    return 10


def confidence_label(diff):
    adiff = abs(diff)
    if adiff <= 2:
        return "baixa"
    if adiff <= 5:
        return "média"
    if adiff <= 8:
        return "alta"
    return "muito alta"


def balance_label(diff):
    adiff = abs(diff)
    if adiff <= 2:
        return "muito equilibrado"
    if adiff <= 5:
        return "relativamente equilibrado"
    return "desequilibrado"


def risk_label(diff):
    adiff = abs(diff)
    if adiff <= 2:
        return "alto"
    if adiff <= 5:
        return "médio"
    return "médio-baixo"


def predict_match(home, away, league):
    home_strength = get_team_strength(home) + 3
    away_strength = get_team_strength(away)
    bonus = league_bonus(league)

    diff = home_strength - away_strength
    quality = min((home_strength + away_strength) / 4, 26)
    game_score = int(round(min(48 + bonus + quality, 99)))

    if diff >= 8:
        prediction = f"favoritismo claro de {home}"
        suggestion = f"vitória de {home}"
        tip = f"{home} tem vantagem técnica clara e joga em casa"
    elif diff >= 3:
        prediction = f"leve favoritismo de {home}"
        suggestion = f"{home} ou empate"
        tip = f"{home} chega um pouco acima no confronto"
    elif diff <= -8:
        prediction = f"favoritismo claro de {away}"
        suggestion = f"vitória de {away}"
        tip = f"{away} tem elenco mais forte no confronto"
    elif diff <= -3:
        prediction = f"leve favoritismo de {away}"
        suggestion = f"{away} ou empate"
        tip = f"{away} parece ligeiramente superior tecnicamente"
    else:
        prediction = "jogo muito equilibrado"
        suggestion = "evitar vencedor seco"
        tip = "equilíbrio alto, melhor tratar como duelo aberto"

    confidence = confidence_label(diff)
    balance = balance_label(diff)
    risk = risk_label(diff)

    if game_score >= 96:
        insight = "jogo enorme do dia"
    elif game_score >= 90:
        insight = "confronto muito forte"
    elif game_score >= 80:
        insight = "bom jogo para acompanhar"
    else:
        insight = "jogo interessante do dia"

    analysis_text = (
        f"{prediction}. "
        f"Confronto {balance}. "
        f"Confiança da leitura: {confidence}. "
        f"{tip}."
    )

    return {
        "score": game_score,
        "prediction": prediction,
        "suggestion": suggestion,
        "tip": tip,
        "risk": risk,
        "insight": insight,
        "confidence": confidence,
        "balance": balance,
        "analysis_text": analysis_text,
    }


def fetch_today_matches():
    response = requests.get(
        f"{SPORTSDB_URL}/eventsday.php",
        params={"d": get_today_date(), "s": "Soccer"},
        timeout=30,
    )
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
                "confidence": analysis["confidence"],
                "balance": analysis["balance"],
                "analysis_text": analysis["analysis_text"],
            }
        )

    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches


def format_best_match():
    matches = fetch_today_matches()
    if not matches:
        return "⚠️ Não encontrei jogos grandes para hoje."

    best = matches[0]
    return "\n".join([
        "🔥 Jogo destaque do dia",
        "",
        f"{best['home']} x {best['away']}",
        f"🏆 {best['league']}",
        f"🕒 {best['time']}",
        f"📊 Nota do jogo: {best['score']}",
        "",
        "🧠 Análise:",
        best["analysis_text"],
        "",
        f"💡 Leitura rápida: {best['insight']}.",
        f"🎯 Sugestão: {best['suggestion']}",
        f"⚠️ Risco: {best['risk']}",
    ])


def format_tip():
    matches = fetch_today_matches()
    if not matches:
        return "⚠️ Não encontrei jogos grandes para hoje."

    best = matches[0]
    return "\n".join([
        "💰 Sugestão do dia",
        "",
        f"{best['home']} x {best['away']}",
        f"🏆 {best['league']}",
        f"🕒 {best['time']}",
        "",
        f"📌 Entrada sugerida: {best['suggestion']}",
        f"🧠 Justificativa: {best['analysis_text']}",
        f"⚠️ Risco: {best['risk']}",
    ])


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
        lines.append(f"📌 Confiança: {match['confidence']}")
        lines.append("")

    lines.append("Toque nos botões abaixo para navegar.")
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
        lines.append(f"   📌 confiança {match['confidence']}")

    return "\n".join(lines)


def format_safe_bets(limit=5):
    matches = fetch_today_matches()

    safe_matches = [
        m for m in matches
        if m["confidence"] in ["alta", "muito alta"] and m["risk"] in ["médio-baixo", "médio"]
    ]

    if not safe_matches:
        return "⚠️ Nenhum jogo seguro encontrado hoje."

    safe_matches = safe_matches[:limit]

    lines = ["🛡️ Jogos mais seguros do dia", ""]
    for i, match in enumerate(safe_matches, start=1):
        lines.append(f"{i}. {match['home']} x {match['away']}")
        lines.append(f"🏆 {match['league']}")
        lines.append(f"🕒 {match['time']}")
        lines.append(f"📊 Nota: {match['score']}")
        lines.append(f"🎯 Entrada: {match['suggestion']}")
        lines.append(f"📌 Confiança: {match['confidence']}")
        lines.append(f"⚠️ Risco: {match['risk']}")
        lines.append("")

    lines.append("Esses são os confrontos com leitura mais segura do dia.")
    return "\n".join(lines)


def format_status():
    state = load_state()
    return (
        "📌 Status do bot\n\n"
        f"Alertas: {'ativados' if state.get('alerts_enabled') else 'desativados'}\n"
        f"Hora do alerta: {ALERT_HOUR}:00\n"
        f"Timezone: {TIMEZONE}"
    )


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
        send(chat_id, format_best_match(), reply_markup=inline_menu())
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
    threading.Thread(target=scheduler_loop, daemon=True).start()


def handle_command(text, state):
    if text == "/today":
        return format_top_matches(limit=5)
    if text == "/top":
        return format_full_list(limit=12)
    if text == "/best":
        return format_best_match()
    if text == "/tip":
        return format_tip()
    if text == "/safe":
        return format_safe_bets(limit=5)
    if text == "/alert_on":
        state["alerts_enabled"] = True
        save_state(state)
        return f"✅ Alerta automático ativado para {ALERT_HOUR}:00."
    if text == "/alert_off":
        state["alerts_enabled"] = False
        save_state(state)
        return "⛔ Alerta automático desativado."
    if text == "/status":
        return format_status()
    return (
        "🤖 Bot analista PREMIUM online.\n\n"
        "Use os botões abaixo ou os comandos:\n"
        "/today\n/top\n/best\n/tip\n/safe\n/alert_on\n/alert_off\n/status"
    )


@app.before_request
def ensure_scheduler():
    start_scheduler_once()


@app.route("/")
def home():
    return jsonify({"ok": True, "service": "aqs2026bot-premium-safe"})


@app.route("/setup-webhook")
def setup():
    response = telegram_post(
        "setWebhook",
        {
            "url": f"{BASE_URL}/webhook",
            "secret_token": SECRET,
            "drop_pending_updates": True,
        },
    )
    return jsonify(response.json())


@app.route("/webhook", methods=["POST"])
def webhook():
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if secret != SECRET:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}

    if "callback_query" in data:
        callback = data["callback_query"]
        callback_id = callback["id"]
        message = callback.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")
        action = callback.get("data", "")

        if not chat_id or not message_id:
            answer_callback(callback_id, "Erro")
            return jsonify({"ok": True})

        state = load_state()
        state["chat_id"] = chat_id
        save_state(state)

        text = handle_command(f"/{action}", state)
        edit_message(chat_id, message_id, text, reply_markup=inline_menu())
        answer_callback(callback_id, "Atualizado")
        return jsonify({"ok": True})

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
            "🤖 Bot analista PREMIUM online.\n\nToque nos botões abaixo.",
            reply_markup=inline_menu(),
        )
    else:
        response_text = handle_command(text, state)
        send(chat_id, response_text, reply_markup=inline_menu())

    return jsonify({"ok": True})


if __name__ == "__main__":
    start_scheduler_once()
    app.run(host="0.0.0.0", port=10000)
