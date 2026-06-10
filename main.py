import os
import json
import asyncio
import websockets
import aiohttp
from datetime import datetime
from collections import defaultdict

# ── Configurações ─────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "8654852978:AAGoPa-oA9xeRb5Oh3lLHulVzqfM0JXaFcc")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "7635744352")
DERIV_APP_ID     = os.environ.get("DERIV_APP_ID", "1089")

MARKETS = [
    {"symbol": "R_10",    "name": "Volatility 10"},
    {"symbol": "R_25",    "name": "Volatility 25"},
    {"symbol": "R_50",    "name": "Volatility 50"},
    {"symbol": "R_75",    "name": "Volatility 75"},
    {"symbol": "R_100",   "name": "Volatility 100"},
    {"symbol": "1HZ10V",  "name": "Volatility 10 (1s)"},
    {"symbol": "1HZ25V",  "name": "Volatility 25 (1s)"},
    {"symbol": "1HZ50V",  "name": "Volatility 50 (1s)"},
    {"symbol": "1HZ75V",  "name": "Volatility 75 (1s)"},
    {"symbol": "1HZ100V", "name": "Volatility 100 (1s)"},
]

state = defaultdict(lambda: {
    "candles": [], "last_signal": None, "last_signal_time": None,
    "tp1": None, "tp2": None, "sl": None,
    "tp1_hit": False, "tp2_hit": False, "sl_hit": False,
})

async def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[TELEGRAM] {text[:80]}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    print(f"[Telegram erro {resp.status}] {await resp.text()}")
                else:
                    print(f"[Telegram OK] Mensagem enviada!")
    except Exception as e:
        print(f"[Telegram erro] {e}")

def calc_ema(closes, period):
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return ema

def calc_macd(closes):
    if len(closes) < 35:
        return None
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    if not ema12 or not ema26:
        return None
    macd_line = ema12 - ema26
    macd_series = []
    for i in range(max(0, len(closes) - 9), len(closes)):
        sl = closes[:i + 1]
        e12 = calc_ema(sl, 12)
        e26 = calc_ema(sl, 26)
        if e12 and e26:
            macd_series.append(e12 - e26)
    if not macd_series:
        return None
    signal_line = calc_ema(macd_series, min(9, len(macd_series))) or (sum(macd_series) / len(macd_series))
    return {"macd_line": macd_line, "signal_line": signal_line}

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    sl = closes[-(period + 1):]
    gains = losses = 0
    for i in range(1, len(sl)):
        diff = sl[i] - sl[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100
    return 100 - 100 / (1 + gains / losses)

def calc_atr(candles, period=14):
    if len(candles) < period + 1:
        return None
    trs = []
    recent = candles[-(period + 1):]
    for i in range(1, len(recent)):
        c = recent[i]
        prev = recent[i - 1]
        trs.append(max(
            c["high"] - c["low"],
            abs(c["high"] - prev["close"]),
            abs(c["low"] - prev["close"])
        ))
    return sum(trs) / len(trs) if trs else None

def analyze_signal(symbol):
    s = state[symbol]
    candles = s["candles"]
    if len(candles) < 35:
        return None

    closes = [c["close"] for c in candles]
    ema20  = calc_ema(closes, 20)
    ema50  = calc_ema(closes, 50) if len(closes) >= 50 else calc_ema(closes, len(closes) // 2)
    ema200 = calc_ema(closes, min(200, len(closes)))
    macd   = calc_macd(closes)
    rsi    = calc_rsi(closes)
    atr    = calc_atr(candles)

    if not all([ema20, ema50, ema200, macd, rsi, atr]):
        return None

    price = closes[-1]

    ema_buy  = ema20 > ema50 > ema200
    ema_sell = ema20 < ema50 < ema200
    macd_buy  = macd["macd_line"] > macd["signal_line"] and macd["macd_line"] > 0
    macd_sell = macd["macd_line"] < macd["signal_line"] and macd["macd_line"] < 0
    rsi_buy  = 40 <= rsi <= 68
    rsi_sell = 32 <= rsi <= 60

    score_buy  = (ema_buy * 3) + (macd_buy * 2) + (rsi_buy * 2) + ((price > ema20) * 1)
    score_sell = (ema_sell * 3) + (macd_sell * 2) + (rsi_sell * 2) + ((price < ema20) * 1)

    conf = round(max(score_buy, score_sell) / 8 * 100)

    print(f"[{symbol}] score_buy={score_buy} score_sell={score_sell} rsi={rsi:.1f} macd={macd['macd_line']:.4f}")

    if score_buy >= 6 and score_buy > score_sell and conf >= 75:
        return {"signal": "BUY", "confidence": conf, "price": price, "atr": atr,
                "tp1": price + atr * 2, "tp2": price + atr * 3.5, "sl": price - atr * 1.5}
    if score_sell >= 6 and score_sell > score_buy and conf >= 75:
        return {"signal": "SELL", "confidence": conf, "price": price, "atr": atr,
                "tp1": price - atr * 2, "tp2": price - atr * 3.5, "sl": price + atr * 1.5}
    return None

def msg_signal(market_name, r):
    direcao = "🟢 COMPRA" if r["signal"] == "BUY" else "🔴 VENDA"
    arrow   = "📈" if r["signal"] == "BUY" else "📉"
    now     = datetime.now().strftime("%d/%m/%Y %H:%M")
    return (
        f"{arrow} <b>SINAL H1 — {market_name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Direção: <b>{direcao}</b>\n"
        f"💰 Entrada: <b>{r['price']:.4f}</b>\n"
        f"✅ TP1: <b>{r['tp1']:.4f}</b>\n"
        f"✅ TP2: <b>{r['tp2']:.4f}</b>\n"
        f"❌ Stop Loss: <b>{r['sl']:.4f}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔒 Confiança: {r['confidence']}%\n"
        f"⏰ {now}\n\n"
        f"⚠️ <i>Não é recomendação financeira. Use gestão de risco.</i>"
    )

def msg_tp1(market_name, signal, tp1):
    lado = "COMPRA 🟢" if signal == "BUY" else "VENDA 🔴"
    return (f"✅ <b>TP1 ATINGIDO — {market_name}</b>\nSinal {lado}\n"
            f"Preço atingiu TP1: <b>{tp1:.4f}</b>\n💡 Mova o stop para o ponto de entrada.")

def msg_tp2(market_name, signal, tp2):
    lado = "COMPRA 🟢" if signal == "BUY" else "VENDA 🔴"
    return (f"🏆 <b>TP2 ATINGIDO — {market_name}</b>\nSinal {lado}\n"
            f"Preço atingiu TP2: <b>{tp2:.4f}</b>\n🎉 Lucro máximo capturado!")

def msg_sl(market_name, signal, sl):
    lado = "COMPRA 🟢" if signal == "BUY" else "VENDA 🔴"
    return (f"🛑 <b>STOP LOSS ATINGIDO — {market_name}</b>\nSinal {lado}\n"
            f"Preço atingiu SL: <b>{sl:.4f}</b>\n📌 Aguardando próximo sinal.")

async def check_tpsl(symbol, market_name, price):
    s = state[symbol]
    if not s["last_signal"] or s["sl_hit"] or (s["tp1_hit"] and s["tp2_hit"]):
        return
    is_buy = s["last_signal"] == "BUY"
    if not s["tp1_hit"]:
        hit = price >= s["tp1"] if is_buy else price <= s["tp1"]
        if hit:
            s["tp1_hit"] = True
            await send_telegram(msg_tp1(market_name, s["last_signal"], s["tp1"]))
    if s["tp1_hit"] and not s["tp2_hit"]:
        hit = price >= s["tp2"] if is_buy else price <= s["tp2"]
        if hit:
            s["tp2_hit"] = True
            await send_telegram(msg_tp2(market_name, s["last_signal"], s["tp2"]))
            s["last_signal"] = None
    if not s["sl_hit"]:
        hit = price <= s["sl"] if is_buy else price >= s["sl"]
        if hit:
            s["sl_hit"] = True
            await send_telegram(msg_sl(market_name, s["last_signal"], s["sl"]))
            s["last_signal"] = None

async def run_signal_check(symbol, market_name):
    s = state[symbol]
    result = analyze_signal(symbol)
    if not result:
        return
    now = asyncio.get_event_loop().time()
    cooldown = 2 * 3600
    if (s["last_signal"] == result["signal"] and
            s["last_signal_time"] and
            now - s["last_signal_time"] < cooldown):
        return
    s["last_signal"]      = result["signal"]
    s["last_signal_time"] = now
    s["tp1"] = result["tp1"]
    s["tp2"] = result["tp2"]
    s["sl"]  = result["sl"]
    s["tp1_hit"] = s["tp2_hit"] = s["sl_hit"] = False
    print(f"[{symbol}] 🚨 SINAL: {result['signal']} @ {result['price']:.4f} | Conf: {result['confidence']}%")
    await send_telegram(msg_signal(market_name, result))

async def connect_market(market):
    symbol = market["symbol"]
    name   = market["name"]
    uri    = f"wss://ws.binaryws.com/websockets/v3?app_id={DERIV_APP_ID}"
    while True:
        try:
            print(f"[{symbol}] Conectando...")
            async with websockets.connect(uri, ping_interval=30, ping_timeout=10) as ws:
                await ws.send(json.dumps({
                    "ticks_history": symbol, "adjust_start_time": 1,
                    "count": 200, "end": "latest", "granularity": 3600, "style": "candles",
                }))
                subscribed = False
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("msg_type") == "candles" and msg.get("candles"):
                        state[symbol]["candles"] = [
                            {"open": float(c["open"]), "high": float(c["high"]),
                             "low": float(c["low"]), "close": float(c["close"]), "epoch": c["epoch"]}
                            for c in msg["candles"]
                        ]
                        print(f"[{symbol}] {len(state[symbol]['candles'])} candles carregados.")
                        if not subscribed:
                            subscribed = True
                            await asyncio.sleep(0.5)
                            await ws.send(json.dumps({"ticks": symbol, "subscribe": 1}))
                            await asyncio.sleep(0.5)
                            await ws.send(json.dumps({
                                "ticks_history": symbol, "adjust_start_time": 1,
                                "count": 1, "end": "latest",
                                "granularity": 3600, "style": "candles", "subscribe": 1,
                            }))
                        # Rodar análise imediata ao carregar
                        await run_signal_check(symbol, name)

                    elif msg.get("msg_type") == "tick" and msg.get("tick"):
                        price = float(msg["tick"]["quote"])
                        await check_tpsl(symbol, name, price)

                    elif msg.get("msg_type") == "ohlc" and msg.get("ohlc"):
                        c = msg["ohlc"]
                        candle = {"open": float(c["open"]), "high": float(c["high"]),
                                  "low": float(c["low"]), "close": float(c["close"]), "epoch": c["open_time"]}
                        candles = state[symbol]["candles"]
                        if candles and candles[-1]["epoch"] == c["open_time"]:
                            candles[-1] = candle
                        else:
                            candles.append(candle)
                            if len(candles) > 250:
                                candles.pop(0)
                            print(f"[{symbol}] Novo candle H1! Analisando...")
                            await run_signal_check(symbol, name)

                    elif msg.get("error"):
                        code = msg["error"].get("code", "")
                        if code != "AlreadySubscribed":
                            print(f"[{symbol}] Erro: {msg['error']['message']}")

        except Exception as e:
            print(f"[{symbol}] Desconectado: {e}. Reconectando em 5s...")
            await asyncio.sleep(5)

async def main():
    print("🚀 Bot Deriv iniciado!")
    await send_telegram(
        "🤖 <b>Bot de Sinais Deriv iniciado!</b>\n"
        "📊 Monitorando 10 mercados Volatility no H1\n"
        "Estratégia: MACD + EMA Tripla + RSI\n"
        "─────────────────────\n"
        "Aguardando oportunidades..."
    )
    tasks = []
    for i, market in enumerate(MARKETS):
        await asyncio.sleep(1.5)
        tasks.append(asyncio.create_task(connect_market(market)))
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
