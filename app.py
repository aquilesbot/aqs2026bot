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
    "arsenal": 91,
    "liverpool": 92,
    "chelsea": 85,
    "manchester united": 83,
    "newcastle": 82,
    "tottenham": 84,
    "aston villa": 81,
    "bayern munich": 95,
    "borussia dortmund": 85,
    "inter": 90,
    "inter milan": 90,
    "juventus": 87,
    "milan": 86,
    "napoli": 86,
    "roma": 83,
    "lazio": 82,
    "atalanta": 84,
    "psg": 93,
    "atletico madrid": 88,
    "atlético madrid": 88,
    "sevilla": 80,
    "flamengo": 88,
    "palmeiras": 89,
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


def menu_keyboard():
    return {
        "keyboard": [
            [{"text": "/today"}, {"text": "/best"}],
            [{"text": "/top"}, {"text": "/tip"}],
            [{"text": "/alert_on"}, {"text": "/status"}],
        ],
        "resize_keyboard": True,
        "persistent": True,
    }


def send(chat_id, text, with_menu=False):
    payload = {"chat_id": chat_id, "text": text}
    if with_menu:
        payload["reply_markup"] = menu_keyboard()
    telegram_post("sendMessage", payload)


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
        "uefa champions league": 34,
        "english premier league": 28,
        "premier league": 28,
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
    return "alta"


def balance_label(diff):
    adiff = abs(diff)
    if adiff <= 2:
        return "muito equilibrado"
    if adiff <= 5:
        return "relativamente equilibrado"
    return "desequilibrado"


def predict_match(home, away, league):
    home_strength = get_team_strength(home) + 3
    away_strength = get_team_strength(away)
    bonus = league_bonus(league)

    diff = home_strength - away_strength
    raw_score = 48 + bonus + min((home_strength + away_strength) / 4, 25)
    game_score = int(round(min(raw_score, 99)))

    if diff >= 7:
        prediction = f"favoritismo claro de {home}"
        suggestion = f"vitória de {home}"
        tip = f"{home} tem vantagem técnica e mando a favor"
        risk = "médio"
    elif diff >= 3:
        prediction = f"leve favoritismo de {home}"
        suggestion = f"{home} ou empate"
        tip = f"{home} chega um pouco acima no confronto"
        risk = "médio"
    elif diff <= -7:
        prediction = f"favoritismo claro de {away}"
        suggestion = f"vitória de {away}"
        tip = f"{away} tem elenco mais forte no confronto"
        risk = "médio"
    elif diff <= -3:
        prediction = f"leve favoritismo de {away}"
        suggestion = f"{away} ou empate"
        tip = f"{away} parece ligeiramente superior tecnicamente"
        risk = "médio"
    else:
        prediction = "jogo muito equilibrado"
        suggestion = "evitar vencedor seco"
        tip = "equilíbrio alto, melhor tratar como duelo aberto"
        risk = "alto"

    confidence = confidence_label(diff)
    balance = balance_label(diff)

    if game_score >= 95:
        insight = "jogo enorme do dia"
    elif game_score >= 88:
        insight = "confronto muito forte"
    elif game_score >= 78:
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
    url = f"{SPORTSDB_URL}/eventsday.php"
    params = {"d": get_today_date(), "s": "Soccer"}

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
        lines.append(f"   📌 confiança {match['confidence']}")

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
        send(chat_id, format_best_match(), with_menu=True)
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


@app.before_request
def ensure_scheduler():
    start_scheduler_once()


@app.route("/")
def home():
    return jsonify({"ok": True, "service": "aqs2026bot-pro-plus"})


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
            "Toque nos botões abaixo ou use os comandos.\n\n"
            "/today - melhores jogos do dia\n"
            "/top - ranking maior\n"
            "/best - melhor jogo do dia\n"
            "/tip - sugestão do dia\n"
            "/alert_on - ativar alerta automático\n"
            "/alert_off - desativar alerta automático\n"
            "/status - ver status do alerta",
            with_menu=True,
        )
    elif text == "/today":
        try:
            send(chat_id, format_top_matches(limit=5), with_menu=True)
        except Exception:
            send(chat_id, "⚠️ Erro ao buscar jogos de hoje.", with_menu=True)
    elif text == "/top":
        try:
            send(chat_id, format_full_list(limit=12), with_menu=True)
        except Exception:
            send(chat_id, "⚠️ Erro ao montar o ranking.", with_menu=True)
    elif text == "/best":
        try:
            send(chat_id, format_best_match(), with_menu=True)
        except Exception:
            send(chat_id, "⚠️ Erro ao gerar o destaque do dia.", with_menu=True)
    elif text == "/tip":
        try:
            send(chat_id, format_tip(), with_menu=True)
        except Exception:
            send(chat_id, "⚠️ Erro ao gerar a sugestão do dia.", with_menu=True)
    elif text == "/alert_on":
        state["alerts_enabled"] = True
        save_state(state)
        send(chat_id, f"✅ Alerta automático ativado para {ALERT_HOUR}:00.", with_menu=True)
    elif text == "/alert_off":
        state["alerts_enabled"] = False
        save_state(state)
        send(chat_id, "⛔ Alerta automático desativado.", with_menu=True)
    elif text == "/status":
        send(
            chat_id,
            "📌 Status do bot\n\n"
            f"Alertas: {'ativados' if state.get('alerts_enabled') else 'desativados'}\n"
            f"Hora do alerta: {ALERT_HOUR}:00\n"
            f"Timezone: {TIMEZONE}",
            with_menu=True,
        )
    else:
        send(
            chat_id,
            "Use os botões abaixo ou os comandos:\n"
            "/today\n/top\n/best\n/tip\n/alert_on\n/alert_off\n/status",
            with_menu=True,
        )

    return jsonify({"ok": True})


if __name__ == "__main__":
    start_scheduler_once()
    app.run(host="0.0.0.0", port=10000)
