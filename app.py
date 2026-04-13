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
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ALERT_HOUR = int(os.getenv("ALERT_HOUR", "9"))

SPORTSDB_URL = f"https://www.thesportsdb.com/api/v1/json/{SPORTSDB_KEY}"
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
STATE_FILE = Path("/tmp/aqs2026bot_state.json")

TARGET_SPORTS = {
    "soccer_uefa_champs_league": "Champions League",
    "soccer_epl": "Premier League",
    "soccer_spain_la_liga": "La Liga",
    "soccer_italy_serie_a": "Serie A",
    "soccer_germany_bundesliga": "Bundesliga",
    "soccer_france_ligue_one": "Ligue 1",
    "soccer_brazil_campeonato": "Brasileirão Série A",
    "soccer_conmebol_libertadores": "Libertadores",
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

LEAGUE_BONUS = {
    "champions league": 36,
    "premier league": 29,
    "la liga": 26,
    "serie a": 24,
    "bundesliga": 23,
    "ligue 1": 18,
    "brasileirão série a": 22,
    "libertadores": 26,
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
            [
                {"text": "🌐 Abrir bookmaker", "url": url},
            ],
            *inline_menu()["inline_keyboard"],
        ]
    }


def now_local():
    return datetime.now(ZoneInfo(TIMEZONE))


def get_today_date():
    return now_local().strftime("%Y-%m-%d")


def normalize(text):
    return (text or "").strip().lower()


def get_team_strength(team_name):
    return TEAM_STRENGTH.get(normalize(team_name), 74)


def confidence_percent(diff):
    adiff = abs(diff)
    if adiff <= 1:
        return 52
    if adiff == 2:
        return 57
    if adiff == 3:
        return 61
    if adiff == 4:
        return 65
    if adiff == 5:
        return 69
    if adiff == 6:
        return 73
    if adiff == 7:
        return 76
    if adiff == 8:
        return 80
    if adiff == 9:
        return 84
    if adiff == 10:
        return 87
    return 90


def confidence_label(percent):
    if percent < 60:
        return "baixa"
    if percent < 72:
        return "média"
    if percent < 84:
        return "alta"
    return "muito alta"


def risk_label(percent):
    if percent < 60:
        return "alto"
    if percent < 75:
        return "médio"
    return "médio-baixo"


def league_bonus(league_name):
    league = normalize(league_name)
    for key, value in LEAGUE_BONUS.items():
        if key in league:
            return value
    return 10


def find_market(bookmaker, key):
    for market in bookmaker.get("markets", []):
        if market.get("key") == key:
            return market
    return None


def outcome_price(market, name):
    if not market:
        return None
    for outcome in market.get("outcomes", []):
        if normalize(outcome.get("name")) == normalize(name):
            return outcome.get("price")
    return None


def totals_price(market, point_value, over=True):
    if not market:
        return None
    target_name = "over" if over else "under"
    for outcome in market.get("outcomes", []):
        if normalize(outcome.get("name")) == target_name and str(outcome.get("point")) == str(point_value):
            return outcome.get("price")
    return None


def best_bookmaker(odds_event):
    bookmakers = odds_event.get("bookmakers", [])
    if not bookmakers:
        return None
    preferred = ["bet365", "pinnacle", "betfair", "williamhill", "bwin"]
    for key in preferred:
        for bookmaker in bookmakers:
            if bookmaker.get("key") == key:
                return bookmaker
    return bookmakers[0]


def get_bookmaker_link(bookmaker):
    if not bookmaker:
        return None
    return bookmaker.get("link") or bookmaker.get("url")


def fetch_odds_events():
    if not ODDS_API_KEY:
        return []

    all_events = []
    for sport_key in TARGET_SPORTS:
        try:
            response = requests.get(
                f"{ODDS_API_BASE}/sports/{sport_key}/odds",
                params={
                    "apiKey": ODDS_API_KEY,
                    "regions": "eu,uk",
                    "markets": "h2h,totals,btts,draw_no_bet",
                    "oddsFormat": "decimal",
                    "dateFormat": "iso",
                    "bookmakers": "bet365,pinnacle,betfair,bwin,williamhill",
                },
                timeout=30,
            )
            if response.status_code != 200:
                continue
            all_events.extend(response.json())
        except Exception:
            continue
    return all_events


def parse_match(event):
    home = event.get("home_team")
    away = event.get("away_team")
    league = TARGET_SPORTS.get(event.get("sport_key"), event.get("sport_title", "Campeonato"))
    commence_time = event.get("commence_time", "")
    event_time = commence_time[11:16] if "T" in commence_time else "Sem horário"

    home_strength = get_team_strength(home) + 3
    away_strength = get_team_strength(away)
    diff = home_strength - away_strength
    score = int(round(min(48 + league_bonus(league) + min((home_strength + away_strength) / 4, 26), 99)))
    percent = confidence_percent(diff)

    if diff >= 8:
        prediction = f"favoritismo claro de {home}"
        suggestion = f"vitória de {home}"
    elif diff >= 3:
        prediction = f"leve favoritismo de {home}"
        suggestion = f"{home} ou empate"
    elif diff <= -8:
        prediction = f"favoritismo claro de {away}"
        suggestion = f"vitória de {away}"
    elif diff <= -3:
        prediction = f"leve favoritismo de {away}"
        suggestion = f"{away} ou empate"
    else:
        prediction = "jogo muito equilibrado"
        suggestion = "evitar vencedor seco"

    bookmaker = best_bookmaker(event)
    link = get_bookmaker_link(bookmaker)

    h2h = find_market(bookmaker, "h2h")
    totals = find_market(bookmaker, "totals")
    btts = find_market(bookmaker, "btts")
    dnb = find_market(bookmaker, "draw_no_bet")

    return {
        "id": event.get("id"),
        "home": home,
        "away": away,
        "league": league,
        "time": event_time,
        "score": score,
        "prediction": prediction,
        "suggestion": suggestion,
        "confidence_percent": percent,
        "confidence": confidence_label(percent),
        "risk": risk_label(percent),
        "bookmaker_title": bookmaker.get("title") if bookmaker else "Casa não disponível",
        "bookmaker_link": link,
        "odds_home": outcome_price(h2h, home),
        "odds_draw": outcome_price(h2h, "Draw"),
        "odds_away": outcome_price(h2h, away),
        "odds_over_25": totals_price(totals, 2.5, over=True),
        "odds_under_25": totals_price(totals, 2.5, over=False),
        "odds_btts_yes": outcome_price(btts, "Yes"),
        "odds_btts_no": outcome_price(btts, "No"),
        "odds_dnb_home": outcome_price(dnb, home),
        "odds_dnb_away": outcome_price(dnb, away),
    }


def fetch_today_matches():
    events = fetch_odds_events()
    matches = [parse_match(event) for event in events if event.get("home_team") and event.get("away_team")]
    matches.sort(key=lambda x: (x["confidence_percent"], x["score"]), reverse=True)
    return matches


def fmt(value):
    return f"{value:.2f}" if isinstance(value, (int, float)) else "-"


def format_best_match():
    matches = fetch_today_matches()
    if not matches:
        return "⚠️ Não encontrei jogos com odds para hoje."

    best = matches[0]
    return "\n".join([
        "🔥 Jogo destaque do dia",
        "",
        f"{best['home']} x {best['away']}",
        f"🏆 {best['league']}",
        f"🕒 {best['time']}",
        f"🏦 Casa: {best['bookmaker_title']}",
        f"📊 Nota do jogo: {best['score']}",
        "",
        f"🔮 Leitura: {best['prediction']}",
        f"🎯 Sugestão: {best['suggestion']}",
        f"📌 Assertividade estimada: {best['confidence_percent']}%",
        f"⚠️ Risco: {best['risk']}",
        "",
        "Odds 1x2",
        f"1: {fmt(best['odds_home'])} | X: {fmt(best['odds_draw'])} | 2: {fmt(best['odds_away'])}",
    ])


def format_tip():
    matches = fetch_today_matches()
    if not matches:
        return "⚠️ Não encontrei jogos com odds para hoje."

    best = matches[0]
    return "\n".join([
        "💰 Sugestão do dia",
        "",
        f"{best['home']} x {best['away']}",
        f"🏆 {best['league']}",
        f"🕒 {best['time']}",
        f"🏦 Casa: {best['bookmaker_title']}",
        "",
        f"📌 Entrada sugerida: {best['suggestion']}",
        f"🔮 Justificativa: {best['prediction']}",
        f"📌 Assertividade estimada: {best['confidence_percent']}%",
        f"⚠️ Risco: {best['risk']}",
    ])


def format_odds():
    matches = fetch_today_matches()
    if not matches:
        return "⚠️ Não encontrei odds para hoje."

    best = matches[0]
    return "\n".join([
        "📈 Odds do jogo destaque",
        "",
        f"{best['home']} x {best['away']}",
        f"🏆 {best['league']}",
        f"🏦 {best['bookmaker_title']}",
        "",
        f"1: {fmt(best['odds_home'])}",
        f"X: {fmt(best['odds_draw'])}",
        f"2: {fmt(best['odds_away'])}",
    ])


def format_markets():
    matches = fetch_today_matches()
    if not matches:
        return "⚠️ Não encontrei mercados para hoje."

    best = matches[0]
    return "\n".join([
        "📊 Mercados do jogo destaque",
        "",
        f"{best['home']} x {best['away']}",
        f"🏆 {best['league']}",
        f"🏦 {best['bookmaker_title']}",
        "",
        f"Over 2.5: {fmt(best['odds_over_25'])}",
        f"Under 2.5: {fmt(best['odds_under_25'])}",
        f"Ambas marcam SIM: {fmt(best['odds_btts_yes'])}",
        f"Ambas marcam NÃO: {fmt(best['odds_btts_no'])}",
        f"Draw no bet {best['home']}: {fmt(best['odds_dnb_home'])}",
        f"Draw no bet {best['away']}: {fmt(best['odds_dnb_away'])}",
        "",
        "Escanteios exigem uma fonte adicional de odds específica.",
    ])


def format_top_matches(limit=8):
    matches = fetch_today_matches()[:limit]
    if not matches:
        return "⚠️ Não encontrei jogos com odds para hoje."

    lines = ["📋 Melhores jogos do dia", ""]
    for i, match in enumerate(matches, start=1):
        lines.append(f"{i}. {match['home']} x {match['away']}")
        lines.append(f"🏆 {match['league']} | 🕒 {match['time']}")
        lines.append(f"🎯 {match['suggestion']}")
        lines.append(f"📌 Assertividade: {match['confidence_percent']}%")
        lines.append(f"1: {fmt(match['odds_home'])} | X: {fmt(match['odds_draw'])} | 2: {fmt(match['odds_away'])}")
        lines.append("")

    return "\n".join(lines)


def format_safe_bets(limit=5):
    matches = fetch_today_matches()
    safe_matches = [
        m for m in matches
        if m["confidence_percent"] >= 75 and m["risk"] in ["médio-baixo", "médio"]
    ][:limit]

    if not safe_matches:
        return "⚠️ Nenhum jogo seguro encontrado hoje."

    lines = ["🛡️ Jogos mais seguros do dia", ""]
    for i, match in enumerate(safe_matches, start=1):
        lines.append(f"{i}. {match['home']} x {match['away']}")
        lines.append(f"🏆 {match['league']} | 🕒 {match['time']}")
        lines.append(f"🎯 Entrada: {match['suggestion']}")
        lines.append(f"📌 Assertividade: {match['confidence_percent']}%")
        lines.append(f"⚠️ Risco: {match['risk']}")
        lines.append(f"1: {fmt(match['odds_home'])} | X: {fmt(match['odds_draw'])} | 2: {fmt(match['odds_away'])}")
        lines.append("")

    return "\n".join(lines)


def format_status():
    state = load_state()
    return (
        "📌 Status do bot\n\n"
        f"Alertas: {'ativados' if state.get('alerts_enabled') else 'desativados'}\n"
        f"Hora do alerta: {ALERT_HOUR}:00\n"
        f"Timezone: {TIMEZONE}\n"
        f"Odds API: {'configurada' if ODDS_API_KEY else 'não configurada'}"
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

    if now.hour != ALERT_HOUR or last_alert_date == today:
        return

    try:
        best = fetch_today_matches()[0]
        send(chat_id, format_best_match(), reply_markup=bookmaker_button(best.get("bookmaker_link")))
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
        best = fetch_today_matches()[0]
        return format_best_match(), bookmaker_button(best.get("bookmaker_link"))
    if text == "/tip":
        best = fetch_today_matches()[0]
        return format_tip(), bookmaker_button(best.get("bookmaker_link"))
    if text == "/odds":
        best = fetch_today_matches()[0]
        return format_odds(), bookmaker_button(best.get("bookmaker_link"))
    if text == "/markets":
        best = fetch_today_matches()[0]
        return format_markets(), bookmaker_button(best.get("bookmaker_link"))
    if text == "/today":
        return format_top_matches(limit=8), inline_menu()
    if text == "/top":
        return format_top_matches(limit=12), inline_menu()
    if text == "/safe":
        return format_safe_bets(limit=5), inline_menu()
    if text == "/alert_on":
        state["alerts_enabled"] = True
        save_state(state)
        return f"✅ Alerta automático ativado para {ALERT_HOUR}:00.", inline_menu()
    if text == "/alert_off":
        state["alerts_enabled"] = False
        save_state(state)
        return "⛔ Alerta automático desativado.", inline_menu()
    if text == "/status":
        return format_status(), inline_menu()

    return (
        "🤖 Bot analista premium online.\n\n"
        "Comandos:\n"
        "/best\n/tip\n/odds\n/markets\n/today\n/top\n/safe\n/alert_on\n/alert_off\n/status",
        inline_menu(),
    )


@app.before_request
def ensure_scheduler():
    start_scheduler_once()


@app.route("/")
def home():
    return jsonify({"ok": True, "service": "aqs2026bot-odds"})


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
        except Exception:
            send(chat_id, "⚠️ Erro ao processar os dados de odds ou mercados.", reply_markup=inline_menu())

    return jsonify({"ok": True})


if __name__ == "__main__":
    start_scheduler_once()
    app.run(host="0.0.0.0", port=10000)
