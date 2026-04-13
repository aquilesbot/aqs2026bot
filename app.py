import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
SECRET = os.getenv("WEBHOOK_SECRET", "123456")
BASE_URL = os.getenv("BASE_URL", "")
TIMEZONE = os.getenv("TIMEZONE", "America/Sao_Paulo")
ODDSPAPI_KEY = os.getenv("ODDSPAPI_KEY", "")
BOOKMAKER_SLUG = os.getenv("BOOKMAKER_SLUG", "bet365")
ALERT_HOUR = int(os.getenv("ALERT_HOUR", "9"))

ODDSPAPI_BASE = "https://api.oddspapi.io/v4"
STATE_FILE = Path("/tmp/aqs2026bot_state.json")

TARGET_TOURNAMENT_HINTS = [
    "premier league",
    "laliga",
    "la liga",
    "serie a",
    "bundesliga",
    "ligue 1",
    "brasileirao",
    "brasileirão",
    "campeonato brasileiro",
    "libertadores",
    "champions league",
]

MARKET_NAME_CACHE = {}
CACHE = {
    "tournaments": {"ts": 0, "data": []},
    "matches": {"ts": 0, "data": []},
}


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
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    telegram_post("sendMessage", payload)


def edit_message(chat_id, message_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
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
                {"text": "📈 Odds", "callback_data": "odds"},
                {"text": "📊 Mercados", "callback_data": "markets"},
            ],
            [
                {"text": "🛡️ Jogos seguros", "callback_data": "safe"},
                {"text": "📋 Ranking", "callback_data": "top"},
            ],
            [
                {"text": "🔔 Ativar alerta", "callback_data": "alert_on"},
                {"text": "📌 Status", "callback_data": "status"},
            ],
        ]
    }


def bookmaker_button(url):
    if not url:
        return inline_menu()
    return {
        "inline_keyboard": [
            [{"text": "🌐 Abrir bookmaker", "url": url}],
            *inline_menu()["inline_keyboard"],
        ]
    }


def now_local():
    return datetime.now(ZoneInfo(TIMEZONE))


def normalize(text):
    return (text or "").strip().lower()


def oddspapi_get(path, params=None):
    if not ODDSPAPI_KEY:
        raise RuntimeError("ODDSPAPI_KEY não configurada.")
    p = dict(params or {})
    p["apiKey"] = ODDSPAPI_KEY
    r = requests.get(f"{ODDSPAPI_BASE}{path}", params=p, timeout=30)
    r.raise_for_status()
    return r.json()


def get_market_names():
    global MARKET_NAME_CACHE
    if MARKET_NAME_CACHE:
        return MARKET_NAME_CACHE

    try:
        markets = oddspapi_get("/markets", {"language": "en"})
        MARKET_NAME_CACHE = {
            str(item["marketId"]): item.get("marketName", f"Mercado {item['marketId']}")
            for item in markets
        }
    except Exception:
        MARKET_NAME_CACHE = {}

    return MARKET_NAME_CACHE


def get_target_tournaments():
    age = time.time() - CACHE["tournaments"]["ts"]
    if age < 3600 and CACHE["tournaments"]["data"]:
        return CACHE["tournaments"]["data"]

    tournaments = oddspapi_get("/tournaments", {"sportId": 10})
    selected = []

    for t in tournaments:
        name = normalize(t.get("tournamentName"))
        slug = normalize(t.get("tournamentSlug"))
        combined = f"{name} {slug}"
        if any(hint in combined for hint in TARGET_TOURNAMENT_HINTS):
            selected.append(t)

    CACHE["tournaments"] = {"ts": time.time(), "data": selected}
    return selected


def extract_player_prices(outcomes_obj):
    rows = []
    for outcome_id, outcome in outcomes_obj.items():
        players = outcome.get("players", {})
        for player_id, player_data in players.items():
            rows.append(
                {
                    "outcome_id": str(outcome_id),
                    "player_id": str(player_id),
                    "price": player_data.get("price"),
                    "label": player_data.get("bookmakerOutcomeId", str(outcome_id)),
                }
            )
    return rows


def choose_bookmaker(bookmaker_odds):
    if not bookmaker_odds:
        return None, None

    if BOOKMAKER_SLUG in bookmaker_odds:
        return BOOKMAKER_SLUG, bookmaker_odds[BOOKMAKER_SLUG]

    first_key = next(iter(bookmaker_odds.keys()))
    return first_key, bookmaker_odds[first_key]


def confidence_percent(home_name, away_name):
    strengths = {
        "real madrid": 97, "barcelona": 94, "manchester city": 98, "arsenal": 92,
        "liverpool": 93, "chelsea": 85, "manchester united": 83, "bayern munich": 96,
        "inter": 91, "inter milan": 91, "juventus": 87, "milan": 86, "napoli": 86,
        "psg": 93, "flamengo": 89, "palmeiras": 90, "botafogo": 84, "atlético mineiro": 84,
        "corinthians": 80, "são paulo": 82, "grêmio": 81, "internacional": 80,
    }
    h = strengths.get(normalize(home_name), 74) + 3
    a = strengths.get(normalize(away_name), 74)
    diff = abs(h - a)
    if diff <= 1:
        return 52
    if diff == 2:
        return 57
    if diff == 3:
        return 61
    if diff == 4:
        return 65
    if diff == 5:
        return 69
    if diff == 6:
        return 73
    if diff == 7:
        return 76
    if diff == 8:
        return 80
    if diff == 9:
        return 84
    if diff == 10:
        return 87
    return 90


def build_match(fixture):
    bookmaker_key, bookmaker = choose_bookmaker(fixture.get("bookmakerOdds", {}))
    if not bookmaker:
        return None

    market_names = get_market_names()
    markets = bookmaker.get("markets", {})

    parsed_markets = []
    full_time_lines = []

    for market_id, market_data in markets.items():
        market_name = market_names.get(str(market_id), f"Mercado {market_id}")
        rows = extract_player_prices(market_data.get("outcomes", {}))

        if not rows:
            continue

        pretty_rows = []
        for row in rows:
            label = row["label"]
            price = row["price"]
            pretty_rows.append((label, price))

        parsed_markets.append(
            {
                "id": str(market_id),
                "name": market_name,
                "outcomes": pretty_rows,
            }
        )

        if str(market_id) == "101":
            full_time_lines = pretty_rows

    p1 = fixture.get("participant1Name", "Time 1")
    p2 = fixture.get("participant2Name", "Time 2")
    percent = confidence_percent(p1, p2)

    prediction = "jogo equilibrado"
    suggestion = "evitar vencedor seco"

    if percent >= 84:
        prediction = f"favoritismo claro de {p1 if percent >= 84 else p2}"
        suggestion = f"vitória de {p1}"
    elif percent >= 73:
        prediction = f"leve favoritismo de {p1}"
        suggestion = f"{p1} ou empate"

    if not full_time_lines and parsed_markets:
        full_time_lines = parsed_markets[0]["outcomes"]

    return {
        "fixture_id": fixture.get("fixtureId"),
        "home": p1,
        "away": p2,
        "league": fixture.get("tournamentName", "Campeonato"),
        "time": fixture.get("startTime", "")[11:16] if fixture.get("startTime") else "Sem horário",
        "bookmaker": bookmaker_key,
        "bookmaker_link": bookmaker.get("fixturePath"),
        "markets": parsed_markets,
        "main_odds": full_time_lines,
        "confidence_percent": percent,
        "prediction": prediction,
        "suggestion": suggestion,
        "risk": "médio-baixo" if percent >= 75 else "médio" if percent >= 60 else "alto",
    }


def fetch_today_matches():
    age = time.time() - CACHE["matches"]["ts"]
    if age < 300 and CACHE["matches"]["data"]:
        return CACHE["matches"]["data"]

    tournaments = get_target_tournaments()
    if not tournaments:
        return []

    tournament_ids = ",".join(str(t["tournamentId"]) for t in tournaments[:12])

    odds_rows = oddspapi_get(
        "/odds-by-tournaments",
        {
            "tournamentIds": tournament_ids,
            "bookmaker": BOOKMAKER_SLUG,
            "oddsFormat": "decimal",
            "verbosity": 3,
        },
    )

    matches = []
    for row in odds_rows:
        item = build_match(row)
        if item:
            matches.append(item)

    matches.sort(key=lambda x: x["confidence_percent"], reverse=True)
    CACHE["matches"] = {"ts": time.time(), "data": matches}
    return matches


def format_main_odds(match):
    if not match["main_odds"]:
        return "Odds principais não disponíveis."

    parts = []
    for label, price in match["main_odds"][:3]:
        parts.append(f"{label}: {price}")
    return " | ".join(parts)


def format_best():
    matches = fetch_today_matches()
    if not matches:
        return "⚠️ Nenhum jogo com odds encontrado agora."

    m = matches[0]
    return "\n".join([
        "🔥 Jogo do dia",
        "",
        f"{m['home']} x {m['away']}",
        f"🏆 {m['league']}",
        f"🕒 {m['time']}",
        f"🏦 Casa: {m['bookmaker']}",
        "",
        f"🎯 Sugestão: {m['suggestion']}",
        f"🔮 Leitura: {m['prediction']}",
        f"📌 Assertividade estimada: {m['confidence_percent']}%",
        f"⚠️ Risco: {m['risk']}",
        "",
        f"📈 Odds: {format_main_odds(m)}",
    ]), bookmaker_button(m.get("bookmaker_link"))


def format_odds():
    matches = fetch_today_matches()
    if not matches:
        return "⚠️ Nenhuma odd encontrada agora.", inline_menu()

    m = matches[0]
    return "\n".join([
        "📈 Odds do jogo destaque",
        "",
        f"{m['home']} x {m['away']}",
        f"🏆 {m['league']}",
        f"🏦 Casa: {m['bookmaker']}",
        "",
        format_main_odds(m),
    ]), bookmaker_button(m.get("bookmaker_link"))


def format_markets():
    matches = fetch_today_matches()
    if not matches:
        return "⚠️ Nenhum mercado encontrado agora.", inline_menu()

    m = matches[0]
    lines = [
        "📊 Mercados do jogo destaque",
        "",
        f"{m['home']} x {m['away']}",
        f"🏆 {m['league']}",
        f"🏦 Casa: {m['bookmaker']}",
        "",
    ]

    shown = 0
    for market in m["markets"]:
        if shown >= 6:
            break
        lines.append(f"• {market['name']}")
        for label, price in market["outcomes"][:4]:
            lines.append(f"  - {label}: {price}")
        lines.append("")
        shown += 1

    if shown == 0:
        lines.append("Mercados indisponíveis para este jogo.")

    return "\n".join(lines), bookmaker_button(m.get("bookmaker_link"))


def format_top():
    matches = fetch_today_matches()[:8]
    if not matches:
        return "⚠️ Nenhum jogo encontrado agora.", inline_menu()

    lines = ["📋 Ranking do dia", ""]
    for i, m in enumerate(matches, start=1):
        lines.append(f"{i}. {m['home']} x {m['away']}")
        lines.append(f"🏆 {m['league']} | 🕒 {m['time']}")
        lines.append(f"🎯 {m['suggestion']}")
        lines.append(f"📌 {m['confidence_percent']}%")
        lines.append("")

    return "\n".join(lines), inline_menu()


def format_safe():
    matches = [m for m in fetch_today_matches() if m["confidence_percent"] >= 75][:5]
    if not matches:
        return "⚠️ Nenhum jogo seguro encontrado hoje.", inline_menu()

    lines = ["🛡️ Jogos seguros", ""]
    for i, m in enumerate(matches, start=1):
        lines.append(f"{i}. {m['home']} x {m['away']}")
        lines.append(f"🎯 {m['suggestion']}")
        lines.append(f"📌 Assertividade: {m['confidence_percent']}%")
        lines.append(f"⚠️ Risco: {m['risk']}")
        lines.append("")

    return "\n".join(lines), inline_menu()


def format_tip():
    return format_best()


def format_status():
    state = load_state()
    return (
        "📌 Status do bot\n\n"
        f"Alertas: {'ativados' if state.get('alerts_enabled') else 'desativados'}\n"
        f"Hora do alerta: {ALERT_HOUR}:00\n"
        f"Timezone: {TIMEZONE}\n"
        f"OddsPapi: {'configurada' if ODDSPAPI_KEY else 'não configurada'}\n"
        f"Bookmaker: {BOOKMAKER_SLUG}"
    ), inline_menu()


def send_daily_alert_if_needed():
    state = load_state()
    chat_id = state.get("chat_id")
    alerts_enabled = state.get("alerts_enabled", False)
    last_alert_date = state.get("last_alert_date")

    if not chat_id or not alerts_enabled:
        return

    now = now_local()
    today = now.strftime("%Y-%m-%d")

    if now.hour != ALERT_HOUR or last_alert_date == today:
        return

    try:
        text, markup = format_best()
        send(chat_id, text, reply_markup=markup)
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
    if text == "/best":
        return format_best()
    if text == "/tip":
        return format_tip()
    if text == "/odds":
        return format_odds()
    if text == "/markets":
        return format_markets()
    if text == "/top":
        return format_top()
    if text == "/safe":
        return format_safe()
    if text == "/alert_on":
        state["alerts_enabled"] = True
        save_state(state)
        return f"✅ Alerta automático ativado para {ALERT_HOUR}:00.", inline_menu()
    if text == "/alert_off":
        state["alerts_enabled"] = False
        save_state(state)
        return "⛔ Alerta automático desativado.", inline_menu()
    if text == "/status":
        return format_status()
    return (
        "🤖 Bot analista premium online.\n\n"
        "Comandos:\n"
        "/best\n/tip\n/odds\n/markets\n/top\n/safe\n/alert_on\n/alert_off\n/status",
        inline_menu(),
    )


@app.before_request
def ensure_scheduler():
    start_scheduler_once()


@app.route("/")
def home():
    return jsonify({"ok": True, "service": "aqs2026bot-oddspapi"})


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

        try:
            text, markup = handle_command(f"/{action}", state)
            edit_message(chat_id, message_id, text, reply_markup=markup)
            answer_callback(callback_id, "Atualizado")
        except Exception:
            answer_callback(callback_id, "Erro ao atualizar")
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
            "🤖 Bot analista premium online.\n\nToque nos botões abaixo.",
            reply_markup=inline_menu(),
        )
    else:
        try:
            response_text, markup = handle_command(text, state)
            send(chat_id, response_text, reply_markup=markup)
        except Exception as e:
            send(chat_id, f"⚠️ Erro ao processar dados: {str(e)}", reply_markup=inline_menu())

    return jsonify({"ok": True})


if __name__ == "__main__":
    start_scheduler_once()
    app.run(host="0.0.0.0", port=10000)
