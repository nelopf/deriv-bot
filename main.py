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

# Mercados monitorados: Step Index, Volatility 25, Volatility 75
MARKETS = [
    {"symbol": "stpRNG",  "name": "Step Index",     "atr_mult": 2.0},
    {"symbol": "R_25",    "name": "Volatility 25",  "atr_mult": 3.0},
    {"symbol": "R_75",    "name": "Volatility 75",  "atr_mult": 4.0},
]

state = defaultdict(lambda: {
    "candles_h1":  [],
    "candles_h4":  [],
    "last_signal": None,
    "last_signal_time": None,
    "tp1": None, "tp2": None, "sl": None,
    "tp1_hit": False, "tp2_hit": False, "sl_hit": False,
})

# ── Telegram ──────────────────────────────────────────────────
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
                    print(f"[Telegram erro {resp.status}]")
                else:
                    print(f"[Telegram OK]")
    except Exception as e:
        print(f"[Telegram erro] {e}")

# ── Indicadores ───────────────────────────────────────────────
def calc_ema(closes, period):
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return ema

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    sl = closes[-(period + 1):]
    gains = losses = 0
    for i in range(1, len(sl)):
        diff = sl[i] - sl[i - 1]
        if diff > 0: gains += diff
        else: losses -= diff
    if losses == 0: return 100
    return 100 - 100 / (1 + gains / losses)

def calc_macd(closes):
    if len(closes) < 35:
        return None
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    if not ema12 or not ema26:
        return None
    macd_line = ema12 - ema26
    series = []
    for i in range(max(0, len(closes) - 15), len(closes)):
        e12 = calc_ema(closes[:i+1], 12)
        e26 = calc_ema(closes[:i+1], 26)
        if e12 and e26:
            series.append(e12 - e26)
    if not series:
        return None
    sig = calc_ema(series, min(9, len(series))) or sum(series)/len(series)
    return {"line": macd_line, "signal": sig, "hist": macd_line - sig}

def calc_atr(candles, period=14):
    if len(candles) < period + 1:
        return None
    recent = candles[-(period+1):]
    trs = []
    for i in range(1, len(recent)):
        c, p = recent[i], recent[i-1]
        trs.append(max(c["high"]-c["low"], abs(c["high"]-p["close"]), abs(c["low"]-p["close"])))
    return sum(trs) / len(trs)

def calc_adx(candles, period=14):
    if len(candles) < period + 2:
        return None
    recent = candles[-(period+2):]
    pdm, mdm, trl = [], [], []
    for i in range(1, len(recent)):
        c, p = recent[i], recent[i-1]
        hd = c["high"] - p["high"]
        ld = p["low"]  - c["low"]
        pdm.append(hd if hd > ld and hd > 0 else 0)
        mdm.append(ld if ld > hd and ld > 0 else 0)
        trl.append(max(c["high"]-c["low"], abs(c["high"]-p["close"]), abs(c["low"]-p["close"])))
    atr_s = sum(trl) or 0.0001
    pdi = 100 * sum(pdm) / atr_s
    mdi = 100 * sum(mdm) / atr_s
    dx  = 100 * abs(pdi - mdi) / (pdi + mdi + 0.0001)
    return {"adx": dx, "pdi": pdi, "mdi": mdi}

def calc_bb(closes, period=20, std_mult=2.0):
    if len(closes) < period:
        return None
    sl = closes[-period:]
    mid = sum(sl) / period
    std = (sum((x - mid)**2 for x in sl) / period) ** 0.5
    return {"upper": mid + std_mult*std, "mid": mid, "lower": mid - std_mult*std}

def candle_pattern(candles):
    """Detecta padrão do último candle fechado"""
    if len(candles) < 3:
        return None
    c  = candles[-1]
    p1 = candles[-2]
    p2 = candles[-3]
    body    = abs(c["close"] - c["open"])
    candle_range = c["high"] - c["low"] or 0.0001
    body_pct = body / candle_range

    # Candle bullish forte (corpo > 60% do range, fecha no topo)
    bull_strong = (c["close"] > c["open"] and body_pct > 0.6 and
                   c["close"] > p1["close"] and p1["close"] > p2["close"])
    # Candle bearish forte
    bear_strong = (c["close"] < c["open"] and body_pct > 0.6 and
                   c["close"] < p1["close"] and p1["close"] < p2["close"])
    return {"bull": bull_strong, "bear": bear_strong}

def is_anomalous_candle(candles, atr, mult=2.5):
    """Detecta se o último candle teve um range muito acima do normal (spike)"""
    if len(candles) < 2 or not atr:
        return False
    last = candles[-1]
    candle_range = last["high"] - last["low"]
    return candle_range > atr * mult

# ── Análise principal ─────────────────────────────────────────
def analyze_signal(symbol, atr_mult):
    s = state[symbol]
    h1 = s["candles_h1"]
    h4 = s["candles_h4"]

    if len(h1) < 50:
        return None

    closes_h1 = [c["close"] for c in h1]

    # ── Indicadores H1 ────────────────────────────────────────
    ema20  = calc_ema(closes_h1, 20)
    ema50  = calc_ema(closes_h1, 50)
    ema200 = calc_ema(closes_h1, min(200, len(closes_h1)))
    macd   = calc_macd(closes_h1)
    rsi    = calc_rsi(closes_h1, 14)
    atr    = calc_atr(h1, 14)
    adx    = calc_adx(h1, 14)
    bb     = calc_bb(closes_h1, 20)
    pat    = candle_pattern(h1)

    if not all([ema20, ema50, ema200, macd, rsi, atr, adx, bb, pat]):
        return None

    # ── Filtro anti-spike: ignora se último candle foi anômalo ─
    if is_anomalous_candle(h1, atr):
        print(f"[{symbol}] Candle anômalo detectado, ignorando análise.")
        return None

    price = closes_h1[-1]

    # ── Tendência H4 (filtro maior timeframe) ─────────────────
    h4_trend_up = h4_trend_down = False
    if len(h4) >= 20:
        closes_h4 = [c["close"] for c in h4]
        ema20_h4 = calc_ema(closes_h4, 20)
        ema50_h4 = calc_ema(closes_h4, 50) if len(closes_h4) >= 50 else calc_ema(closes_h4, len(closes_h4)//2)
        rsi_h4   = calc_rsi(closes_h4, 14)
        adx_h4   = calc_adx(h4, 14)
        if ema20_h4 and ema50_h4 and rsi_h4 and adx_h4:
            h4_trend_up   = ema20_h4 > ema50_h4 and rsi_h4 > 50 and adx_h4["adx"] > 20
            h4_trend_down = ema20_h4 < ema50_h4 and rsi_h4 < 50 and adx_h4["adx"] > 20

    # ── Condições BUY ─────────────────────────────────────────
    b_ema     = ema20 > ema50 > ema200                          # EMA tripla altista
    b_macd    = macd["line"] > macd["signal"] and macd["hist"] > 0  # MACD acima + histograma positivo
    b_rsi     = 50 <= rsi <= 68                                  # RSI zona de força sem sobrecompra
    b_adx     = adx["adx"] > 25 and adx["pdi"] > adx["mdi"]    # ADX forte + direcional positivo
    b_price   = price > ema20 and price > bb["mid"]             # Preço acima das médias
    b_candle  = pat["bull"]                                      # Candle bullish confirmado
    b_h4      = h4_trend_up                                     # H4 também altista

    # ── Condições SELL ────────────────────────────────────────
    s_ema     = ema20 < ema50 < ema200
    s_macd    = macd["line"] < macd["signal"] and macd["hist"] < 0
    s_rsi     = 32 <= rsi <= 50
    s_adx     = adx["adx"] > 25 and adx["mdi"] > adx["pdi"]
    s_price   = price < ema20 and price < bb["mid"]
    s_candle  = pat["bear"]
    s_h4      = h4_trend_down

    # ── Score máximo = 12 ─────────────────────────────────────
    score_buy = (
        (b_ema    * 3) +
        (b_macd   * 2) +
        (b_rsi    * 2) +
        (b_adx    * 2) +
        (b_price  * 1) +
        (b_candle * 1) +
        (b_h4     * 1)
    )
    score_sell = (
        (s_ema    * 3) +
        (s_macd   * 2) +
        (s_rsi    * 2) +
        (s_adx    * 2) +
        (s_price  * 1) +
        (s_candle * 1) +
        (s_h4     * 1)
    )

    conf = round(max(score_buy, score_sell) / 12 * 100)

    print(f"[{symbol}] buy={score_buy} sell={score_sell} conf={conf}% rsi={rsi:.1f} adx={adx['adx']:.1f} h4_up={h4_trend_up} h4_dn={h4_trend_down}")

    # ── Níveis com ATR calibrado ──────────────────────────────
    # SL mais largo para suportar spikes típicos dos mercados sintéticos
    sl_mult  = atr_mult * 2.5
    tp1_mult = atr_mult * 3.0
    tp2_mult = atr_mult * 5.0

    # ── Mínimo 9/12 pontos e 80% confiança ───────────────────
    if score_buy >= 9 and score_buy > score_sell and conf >= 80:
        return {
            "signal": "BUY", "confidence": conf,
            "price": price, "atr": atr,
            "tp1": price + atr * tp1_mult,
            "tp2": price + atr * tp2_mult,
            "sl":  price - atr * sl_mult,
            "score": score_buy,
        }
    if score_sell >= 9 and score_sell > score_buy and conf >= 80:
        return {
            "signal": "SELL", "confidence": conf,
            "price": price, "atr": atr,
            "tp1": price - atr * tp1_mult,
            "tp2": price - atr * tp2_mult,
            "sl":  price + atr * sl_mult,
            "score": score_sell,
        }
    return None

# ── Mensagens ─────────────────────────────────────────────────
def msg_signal(market_name, r):
    direcao = "🟢 COMPRA" if r["signal"] == "BUY" else "🔴 VENDA"
    arrow   = "📈" if r["signal"] == "BUY" else "📉"
    now     = datetime.now().strftime("%d/%m/%Y %H:%M")
    rr_val  = round(abs(r["tp1"] - r["price"]) / abs(r["price"] - r["sl"]), 1)
    stars   = "⭐⭐⭐⭐⭐" if r["confidence"] >= 90 else "⭐⭐⭐⭐" if r["confidence"] >= 80 else "⭐⭐⭐"
    return (
        f"{arrow} <b>SINAL H1 — {market_name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Direção: <b>{direcao}</b>\n"
        f"💰 Entrada: <b>{r['price']:.4f}</b>\n"
        f"✅ TP1: <b>{r['tp1']:.4f}</b>\n"
        f"✅ TP2: <b>{r['tp2']:.4f}</b>\n"
        f"❌ Stop Loss: <b>{r['sl']:.4f}</b>\n"
        f"📐 Risco/Retorno: <b>1:{rr_val}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔒 Confiança: <b>{r['confidence']}%</b> {stars}\n"
        f"📊 Score: <b>{r['score']}/12</b>\n"
        f"⏰ {now}\n\n"
        f"⚠️ <i>Não é recomendação financeira. Use gestão de risco.</i>"
    )

def msg_tp1(market_name, signal, tp1):
    lado = "COMPRA 🟢" if signal == "BUY" else "VENDA 🔴"
    return (f"✅ <b>TP1 ATINGIDO — {market_name}</b>\n"
            f"Sinal {lado}\nPreço atingiu TP1: <b>{tp1:.4f}</b>\n"
            f"💡 Mova o stop para o ponto de entrada.")

def msg_tp2(market_name, signal, tp2):
    lado = "COMPRA 🟢" if signal == "BUY" else "VENDA 🔴"
    return (f"🏆 <b>TP2 ATINGIDO — {market_name}</b>\n"
            f"Sinal {lado}\nPreço atingiu TP2: <b>{tp2:.4f}</b>\n"
            f"🎉 Lucro máximo capturado!")

def msg_sl(market_name, signal, sl):
    lado = "COMPRA 🟢" if signal == "BUY" else "VENDA 🔴"
    return (f"🛑 <b>STOP LOSS ATINGIDO — {market_name}</b>\n"
            f"Sinal {lado}\nPreço atingiu SL: <b>{sl:.4f}</b>\n"
            f"📌 Aguardando próximo sinal.")

# ── TP/SL monitor ─────────────────────────────────────────────
async def check_tpsl(symbol, market_name, price):
    s = state[symbol]
    if not s["last_signal"] or s["sl_hit"] or (s["tp1_hit"] and s["tp2_hit"]):
        return
    is_buy = s["last_signal"] == "BUY"
    if not s["tp1_hit"]:
        if (is_buy and price >= s["tp1"]) or (not is_buy and price <= s["tp1"]):
            s["tp1_hit"] = True
            await send_telegram(msg_tp1(market_name, s["last_signal"], s["tp1"]))
    if s["tp1_hit"] and not s["tp2_hit"]:
        if (is_buy and price >= s["tp2"]) or (not is_buy and price <= s["tp2"]):
            s["tp2_hit"] = True
            await send_telegram(msg_tp2(market_name, s["last_signal"], s["tp2"]))
            s["last_signal"] = None
    if not s["sl_hit"]:
        if (is_buy and price <= s["sl"]) or (not is_buy and price >= s["sl"]):
            s["sl_hit"] = True
            await send_telegram(msg_sl(market_name, s["last_signal"], s["sl"]))
            s["last_signal"] = None

# ── Signal check ──────────────────────────────────────────────
async def run_signal_check(symbol, market_name, atr_mult):
    s = state[symbol]
    result = analyze_signal(symbol, atr_mult)
    if not result:
        return
    now = asyncio.get_event_loop().time()
    cooldown = 4 * 3600
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
    print(f"[{symbol}] 🚨 {result['signal']} conf={result['confidence']}% score={result['score']}/12")
    await send_telegram(msg_signal(market_name, result))

# ── WebSocket por mercado ─────────────────────────────────────
async def connect_market(market):
    symbol   = market["symbol"]
    name     = market["name"]
    atr_mult = market["atr_mult"]
    uri      = f"wss://ws.binaryws.com/websockets/v3?app_id={DERIV_APP_ID}"

    while True:
        try:
            print(f"[{symbol}] Conectando...")
            async with websockets.connect(uri, ping_interval=30, ping_timeout=10) as ws:

                # Pedir H4 (granularity 14400s)
                await ws.send(json.dumps({
                    "ticks_history": symbol, "adjust_start_time": 1,
                    "count": 100, "end": "latest", "granularity": 14400, "style": "candles",
                }))
                # Pedir H1
                await asyncio.sleep(0.3)
                await ws.send(json.dumps({
                    "ticks_history": symbol, "adjust_start_time": 1,
                    "count": 200, "end": "latest", "granularity": 3600, "style": "candles",
                }))

                subscribed = False
                h4_loaded  = False

                async for raw in ws:
                    msg = json.loads(raw)

                    if msg.get("msg_type") == "candles" and msg.get("candles"):
                        candles_data = [
                            {"open": float(c["open"]), "high": float(c["high"]),
                             "low": float(c["low"]), "close": float(c["close"]), "epoch": c["epoch"]}
                            for c in msg["candles"]
                        ]
                        # Identificar se é H4 ou H1 pelo número de candles e intervalo
                        if not h4_loaded and len(candles_data) <= 110:
                            state[symbol]["candles_h4"] = candles_data
                            h4_loaded = True
                            print(f"[{symbol}] {len(candles_data)} candles H4 carregados.")
                        else:
                            state[symbol]["candles_h1"] = candles_data
                            print(f"[{symbol}] {len(candles_data)} candles H1 carregados.")
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
                            await run_signal_check(symbol, name, atr_mult)

                    elif msg.get("msg_type") == "tick" and msg.get("tick"):
                        price = float(msg["tick"]["quote"])
                        await check_tpsl(symbol, name, price)

                    elif msg.get("msg_type") == "ohlc" and msg.get("ohlc"):
                        c = msg["ohlc"]
                        candle = {
                            "open": float(c["open"]), "high": float(c["high"]),
                            "low": float(c["low"]), "close": float(c["close"]),
                            "epoch": c["open_time"],
                        }
                        candles = state[symbol]["candles_h1"]
                        if candles and candles[-1]["epoch"] == c["open_time"]:
                            candles[-1] = candle
                        else:
                            candles.append(candle)
                            if len(candles) > 250:
                                candles.pop(0)
                            print(f"[{symbol}] Novo candle H1 fechado! Analisando...")
                            await run_signal_check(symbol, name, atr_mult)

                    elif msg.get("error"):
                        if msg["error"].get("code") != "AlreadySubscribed":
                            print(f"[{symbol}] Erro: {msg['error']['message']}")

        except Exception as e:
            print(f"[{symbol}] Desconectado: {e}. Reconectando em 5s...")
            await asyncio.sleep(5)

# ── Main ──────────────────────────────────────────────────────
async def main():
    print("🚀 Bot Deriv H1 + H4 iniciado!")
    await send_telegram(
        "🤖 <b>Bot de Sinais Deriv — Versão Premium</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 Mercados: Step Index, Volatility 25, Volatility 75\n"
        "📐 Estratégia: H1 + H4 confirmado\n"
        "🔍 Filtros: EMA Tripla + MACD + RSI + ADX + Bollinger + Padrão de Candle + Anti-Spike\n"
        "🔒 Confiança mínima: 80% | Score: 9/12\n"
        "⏱ Cooldown: 4h por mercado\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Aguardando oportunidades de alta qualidade... 🎯"
    )
    tasks = []
    for i, market in enumerate(MARKETS):
        await asyncio.sleep(2.0)
        tasks.append(asyncio.create_task(connect_market(market)))
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
