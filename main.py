import os
import json
import asyncio
import aiohttp
from datetime import datetime, timezone
from collections import defaultdict

# ── Configurações ─────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "8654852978:AAGoPa-oA9xeRb5Oh3lLHulVzqfM0JXaFcc")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "7635744352")

MARKETS = [
    {"symbol": "^DJI",  "name": "US30 (Dow Jones)", "yf": "^DJI"},
    {"symbol": "^IXIC", "name": "Nasdaq 100",        "yf": "^IXIC"},
]

state = defaultdict(lambda: {
    "candles": [],
    "last_signal": None,
    "last_signal_time": None,
    "tp1": None, "tp2": None, "sl": None,
    "tp1_hit": False, "tp2_hit": False, "sl_hit": False,
    "last_price": None,
})

# ── Telegram ──────────────────────────────────────────────────
async def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[TELEGRAM] {text[:100]}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    print("[Telegram OK]")
                else:
                    print(f"[Telegram erro {resp.status}]")
    except Exception as e:
        print(f"[Telegram erro] {e}")

# ── Yahoo Finance ─────────────────────────────────────────────
async def fetch_candles(symbol, interval="1h", period="30d"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": interval, "range": period}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status != 200:
                    print(f"[YF] Erro {resp.status} para {symbol}")
                    return []
                data = await resp.json()
                chart = data["chart"]["result"][0]
                timestamps = chart["timestamp"]
                ohlcv = chart["indicators"]["quote"][0]
                candles = []
                for i in range(len(timestamps)):
                    o = ohlcv["open"][i]
                    h = ohlcv["high"][i]
                    l = ohlcv["low"][i]
                    c = ohlcv["close"][i]
                    if None in [o, h, l, c]:
                        continue
                    candles.append({
                        "epoch": timestamps[i],
                        "open":  float(o),
                        "high":  float(h),
                        "low":   float(l),
                        "close": float(c),
                    })
                return candles
    except Exception as e:
        print(f"[YF] Erro fetch {symbol}: {e}")
        return []

async def fetch_price(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": "1m", "range": "1d"}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
                closes = [c for c in closes if c is not None]
                return closes[-1] if closes else None
    except:
        return None

# ── Indicadores ───────────────────────────────────────────────
def calc_ema(closes, period):
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for p in closes[period:]:
        ema = p * k + ema * (1 - k)
    return ema

def calc_atr(candles, period=14):
    if len(candles) < period + 1:
        return None
    recent = candles[-(period+1):]
    trs = []
    for i in range(1, len(recent)):
        c, p = recent[i], recent[i-1]
        trs.append(max(c["high"]-c["low"],
                       abs(c["high"]-p["close"]),
                       abs(c["low"]-p["close"])))
    return sum(trs) / len(trs)

# ── SMC: Break of Structure ───────────────────────────────────
def detect_bos(candles):
    """
    BOS Bullish: preço quebra acima do último topo significativo
    BOS Bearish: preço quebra abaixo do último fundo significativo
    """
    if len(candles) < 10:
        return None
    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    closes = [c["close"] for c in candles]

    # Últimos 20 candles para estrutura
    window = candles[-20:]
    w_highs = [c["high"] for c in window]
    w_lows  = [c["low"]  for c in window]

    recent_high = max(w_highs[:-3])  # topo anterior (exceto últimos 3)
    recent_low  = min(w_lows[:-3])   # fundo anterior

    last_close = closes[-1]
    last_high  = highs[-1]
    last_low   = lows[-1]

    bos_bull = last_close > recent_high  # quebra do topo = BOS bullish
    bos_bear = last_close < recent_low   # quebra do fundo = BOS bearish

    return {
        "bull": bos_bull,
        "bear": bos_bear,
        "recent_high": recent_high,
        "recent_low": recent_low,
    }

# ── SMC: Change of Character ──────────────────────────────────
def detect_choch(candles):
    """
    CHoCH: após sequência de topos descendentes, forma topo ascendente (reversão bullish)
    ou após fundos ascendentes, forma fundo descendente (reversão bearish)
    """
    if len(candles) < 6:
        return None
    highs = [c["high"] for c in candles[-6:]]
    lows  = [c["low"]  for c in candles[-6:]]

    # CHoCH Bullish: último fundo > fundo anterior (quebra a sequência baixista)
    choch_bull = lows[-1] > lows[-3] > lows[-5]
    # CHoCH Bearish: último topo < topo anterior
    choch_bear = highs[-1] < highs[-3] < highs[-5]

    return {"bull": choch_bull, "bear": choch_bear}

# ── SMC: Order Block ──────────────────────────────────────────
def detect_order_block(candles):
    """
    Order Block Bullish: último candle bearish antes de movimento bullish forte
    Order Block Bearish: último candle bullish antes de movimento bearish forte
    """
    if len(candles) < 5:
        return None

    ob_bull = ob_bear = False
    ob_zone_high = ob_zone_low = None

    # Procura nos últimos 10 candles
    for i in range(len(candles)-10, len(candles)-3):
        if i < 0:
            continue
        c     = candles[i]
        next1 = candles[i+1]
        next2 = candles[i+2]

        # OB Bullish: candle bearish seguido de 2 candles bullish fortes
        if (c["close"] < c["open"] and
                next1["close"] > next1["open"] and
                next2["close"] > next2["open"] and
                next2["close"] > c["high"]):
            ob_bull = True
            ob_zone_high = c["high"]
            ob_zone_low  = c["low"]

        # OB Bearish: candle bullish seguido de 2 candles bearish fortes
        if (c["close"] > c["open"] and
                next1["close"] < next1["open"] and
                next2["close"] < next2["open"] and
                next2["close"] < c["low"]):
            ob_bear = True
            ob_zone_high = c["high"]
            ob_zone_low  = c["low"]

    return {"bull": ob_bull, "bear": ob_bear,
            "zone_high": ob_zone_high, "zone_low": ob_zone_low}

# ── SMC: Fair Value Gap ───────────────────────────────────────
def detect_fvg(candles):
    """
    FVG Bullish: gap entre topo do candle N-2 e fundo do candle N (sem sobreposição)
    FVG Bearish: gap entre fundo do candle N-2 e topo do candle N
    """
    if len(candles) < 3:
        return None
    c1 = candles[-3]
    c2 = candles[-2]
    c3 = candles[-1]

    fvg_bull = c3["low"]  > c1["high"]   # gap bullish
    fvg_bear = c3["high"] < c1["low"]    # gap bearish

    return {"bull": fvg_bull, "bear": fvg_bear}

# ── SMC: Liquidity Sweep ──────────────────────────────────────
def detect_liquidity_sweep(candles):
    """
    Sweep Bullish: preço varreu mínimas anteriores (caça stops) e voltou acima
    Sweep Bearish: preço varreu máximas anteriores e voltou abaixo
    """
    if len(candles) < 5:
        return None
    recent = candles[-5:]
    lows   = [c["low"]  for c in recent[:-1]]
    highs  = [c["high"] for c in recent[:-1]]
    last   = recent[-1]

    sweep_bull = (last["low"] < min(lows) and last["close"] > min(lows))
    sweep_bear = (last["high"] > max(highs) and last["close"] < max(highs))

    return {"bull": sweep_bull, "bear": sweep_bear}

# ── Análise SMC principal ─────────────────────────────────────
def analyze_smc(symbol):
    s = state[symbol]
    candles = s["candles"]
    if len(candles) < 30:
        return None

    closes = [c["close"] for c in candles]
    atr    = calc_atr(candles, 14)
    ema20  = calc_ema(closes, 20)
    ema50  = calc_ema(closes, 50) if len(closes) >= 50 else None

    if not atr or not ema20:
        return None

    price = closes[-1]

    bos    = detect_bos(candles)
    choch  = detect_choch(candles)
    ob     = detect_order_block(candles)
    fvg    = detect_fvg(candles)
    sweep  = detect_liquidity_sweep(candles)

    if not all([bos, choch, ob, fvg, sweep]):
        return None

    # Tendência geral via EMA
    ema_bull = ema50 and ema20 > ema50 and price > ema20
    ema_bear = ema50 and ema20 < ema50 and price < ema20

    # ── Score BUY (máximo 8) ──────────────────────────────────
    score_buy = (
        (bos["bull"]   * 2) +   # BOS confirma estrutura
        (choch["bull"] * 2) +   # CHoCH confirma reversão
        (ob["bull"]    * 1) +   # Order Block zona de entrada
        (fvg["bull"]   * 1) +   # FVG zona de liquidez
        (sweep["bull"] * 1) +   # Liquidity Sweep caça stops
        (ema_bull      * 1)     # EMA confirma tendência
    )

    # ── Score SELL (máximo 8) ─────────────────────────────────
    score_sell = (
        (bos["bear"]   * 2) +
        (choch["bear"] * 2) +
        (ob["bear"]    * 1) +
        (fvg["bear"]   * 1) +
        (sweep["bear"] * 1) +
        (ema_bear      * 1)
    )

    conf = round(max(score_buy, score_sell) / 8 * 100)

    print(f"[{symbol}] SMC buy={score_buy} sell={score_sell} conf={conf}% price={price:.2f}")

    sl_mult  = 2.0
    tp1_mult = 3.0
    tp2_mult = 5.0

    if score_buy >= 6 and score_buy > score_sell and conf >= 75:
        return {
            "signal": "BUY", "confidence": conf, "price": price,
            "score": score_buy, "atr": atr,
            "tp1": price + atr * tp1_mult,
            "tp2": price + atr * tp2_mult,
            "sl":  price - atr * sl_mult,
            "details": {
                "bos": bos["bull"], "choch": choch["bull"],
                "ob": ob["bull"], "fvg": fvg["bull"], "sweep": sweep["bull"],
            }
        }
    if score_sell >= 6 and score_sell > score_buy and conf >= 75:
        return {
            "signal": "SELL", "confidence": conf, "price": price,
            "score": score_sell, "atr": atr,
            "tp1": price - atr * tp1_mult,
            "tp2": price - atr * tp2_mult,
            "sl":  price + atr * sl_mult,
            "details": {
                "bos": bos["bear"], "choch": choch["bear"],
                "ob": ob["bear"], "fvg": fvg["bear"], "sweep": sweep["bear"],
            }
        }
    return None

# ── Mensagens ─────────────────────────────────────────────────
def msg_signal(market_name, r):
    direcao = "🟢 COMPRA" if r["signal"] == "BUY" else "🔴 VENDA"
    arrow   = "📈" if r["signal"] == "BUY" else "📉"
    now     = datetime.now().strftime("%d/%m/%Y %H:%M")
    rr      = round(abs(r["tp1"] - r["price"]) / abs(r["price"] - r["sl"]), 1)
    stars   = "⭐⭐⭐⭐⭐" if r["confidence"] >= 90 else "⭐⭐⭐⭐" if r["confidence"] >= 80 else "⭐⭐⭐"
    d = r["details"]
    return (
        f"{arrow} <b>SINAL SMC — {market_name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Direção: <b>{direcao}</b>\n"
        f"💰 Entrada: <b>{r['price']:.2f}</b>\n"
        f"✅ TP1: <b>{r['tp1']:.2f}</b>\n"
        f"✅ TP2: <b>{r['tp2']:.2f}</b>\n"
        f"❌ Stop Loss: <b>{r['sl']:.2f}</b>\n"
        f"📐 Risco/Retorno: <b>1:{rr}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 Confirmações SMC:\n"
        f"  {'✅' if d['bos'] else '❌'} Break of Structure\n"
        f"  {'✅' if d['choch'] else '❌'} Change of Character\n"
        f"  {'✅' if d['ob'] else '❌'} Order Block\n"
        f"  {'✅' if d['fvg'] else '❌'} Fair Value Gap\n"
        f"  {'✅' if d['sweep'] else '❌'} Liquidity Sweep\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔒 Confiança: <b>{r['confidence']}%</b> {stars}\n"
        f"📊 Score: <b>{r['score']}/8</b>\n"
        f"⏰ {now}\n\n"
        f"⚠️ <i>Não é recomendação financeira. Use gestão de risco.</i>"
    )

def msg_tp1(market_name, signal, tp1):
    lado = "COMPRA 🟢" if signal == "BUY" else "VENDA 🔴"
    return (f"✅ <b>TP1 ATINGIDO — {market_name}</b>\n"
            f"Sinal {lado}\nPreço atingiu TP1: <b>{tp1:.2f}</b>\n"
            f"💡 Mova o stop para o ponto de entrada.")

def msg_tp2(market_name, signal, tp2):
    lado = "COMPRA 🟢" if signal == "BUY" else "VENDA 🔴"
    return (f"🏆 <b>TP2 ATINGIDO — {market_name}</b>\n"
            f"Sinal {lado}\nPreço atingiu TP2: <b>{tp2:.2f}</b>\n"
            f"🎉 Lucro máximo capturado!")

def msg_sl(market_name, signal, sl):
    lado = "COMPRA 🟢" if signal == "BUY" else "VENDA 🔴"
    return (f"🛑 <b>STOP LOSS ATINGIDO — {market_name}</b>\n"
            f"Sinal {lado}\nPreço atingiu SL: <b>{sl:.2f}</b>\n"
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
async def run_signal_check(symbol, market_name):
    s = state[symbol]
    result = analyze_smc(symbol)
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
    print(f"[{symbol}] 🚨 {result['signal']} conf={result['confidence']}% score={result['score']}/8")
    await send_telegram(msg_signal(market_name, result))

# ── Loop principal por mercado ────────────────────────────────
async def monitor_market(market):
    symbol = market["symbol"]
    name   = market["name"]
    print(f"[{symbol}] Iniciando monitoramento SMC...")

    while True:
        try:
            # Atualiza candles H1 a cada 5 minutos
            candles = await fetch_candles(symbol, interval="1h", period="30d")
            if candles:
                state[symbol]["candles"] = candles
                print(f"[{symbol}] {len(candles)} candles H1 carregados.")
                await run_signal_check(symbol, name)

            # Verifica preço atual a cada 60s para TP/SL
            for _ in range(5):
                await asyncio.sleep(60)
                price = await fetch_price(symbol)
                if price:
                    state[symbol]["last_price"] = price
                    await check_tpsl(symbol, name, price)

        except Exception as e:
            print(f"[{symbol}] Erro: {e}. Tentando novamente em 30s...")
            await asyncio.sleep(30)

# ── Main ──────────────────────────────────────────────────────
async def main():
    print("🚀 Bot SMC — US30 e Nasdaq iniciado!")
    await send_telegram(
        "🤖 <b>Bot SMC — US30 e Nasdaq100</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 Mercados: US30 (Dow Jones) · Nasdaq 100\n"
        "📐 Estratégia: Smart Money Concepts (SMC)\n"
        "🔍 BOS · CHoCH · Order Block · FVG · Liquidity Sweep\n"
        "🔒 Confiança mínima: 75% | Score: 6/8\n"
        "⏱ Atualização: a cada 5 minutos\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Aguardando oportunidades SMC... 🎯"
    )
    tasks = [asyncio.create_task(monitor_market(m)) for m in MARKETS]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
