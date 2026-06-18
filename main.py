import os
import asyncio
import aiohttp
from datetime import datetime
from collections import defaultdict

# ── Configurações ─────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "SEU_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "SEU_CHAT_ID")

MARKETS = [
    {"symbol": "^DJI",  "name": "US30 (Dow Jones)"},
    {"symbol": "^IXIC", "name": "Nasdaq 100"},
]

state = defaultdict(lambda: {
    "candles_m15": [], "candles_h1": [], "candles_h4": [],
    "last_signal": None, "last_signal_time": None,
    "tp1": None, "tp2": None, "sl": None,
    "tp1_hit": False, "tp2_hit": False, "sl_hit": False,
})

# ── Telegram ──────────────────────────────────────────────────
async def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                print("[Telegram OK]" if resp.status == 200 else f"[Telegram erro {resp.status}]")
    except Exception as e:
        print(f"[Telegram erro] {e}")

# ── Yahoo Finance ─────────────────────────────────────────────
async def fetch_candles(symbol, interval, period):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params={"interval": interval, "range": period}, headers=headers) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                chart = data["chart"]["result"][0]
                ts    = chart["timestamp"]
                q     = chart["indicators"]["quote"][0]
                out   = []
                for i in range(len(ts)):
                    o,h,l,c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
                    if None in [o,h,l,c]: continue
                    out.append({"epoch": ts[i], "open": float(o), "high": float(h), "low": float(l), "close": float(c)})
                return out
    except Exception as e:
        print(f"[YF] {symbol} {interval}: {e}")
        return []

async def fetch_price(symbol):
    try:
        candles = await fetch_candles(symbol, "1m", "1d")
        return candles[-1]["close"] if candles else None
    except:
        return None

# ── Indicadores ───────────────────────────────────────────────
def ema(closes, period):
    if len(closes) < period: return None
    k = 2/(period+1)
    v = sum(closes[:period])/period
    for p in closes[period:]: v = p*k + v*(1-k)
    return v

def atr(candles, period=14):
    if len(candles) < period+1: return None
    r = candles[-(period+1):]
    trs = [max(r[i]["high"]-r[i]["low"], abs(r[i]["high"]-r[i-1]["close"]), abs(r[i]["low"]-r[i-1]["close"])) for i in range(1,len(r))]
    return sum(trs)/len(trs)

def rsi(closes, period=14):
    if len(closes) < period+1: return None
    sl = closes[-(period+1):]
    g = l = 0
    for i in range(1, len(sl)):
        d = sl[i]-sl[i-1]
        if d > 0: g += d
        else: l -= d
    return 100 if l==0 else 100-100/(1+g/l)

# ── SMC por timeframe ─────────────────────────────────────────
def smc_analysis(candles, label=""):
    if len(candles) < 20: return None
    closes = [c["close"] for c in candles]
    price  = closes[-1]

    # BOS
    window = candles[-20:]
    wh = [c["high"] for c in window]
    wl = [c["low"]  for c in window]
    recent_high = max(wh[:-3])
    recent_low  = min(wl[:-3])
    bos_bull = closes[-1] > recent_high
    bos_bear = closes[-1] < recent_low

    # CHoCH
    lows  = [c["low"]  for c in candles[-6:]]
    highs = [c["high"] for c in candles[-6:]]
    choch_bull = lows[-1]  > lows[-3]  > lows[-5]
    choch_bear = highs[-1] < highs[-3] < highs[-5]

    # Order Block
    ob_bull = ob_bear = False
    for i in range(len(candles)-8, len(candles)-3):
        if i < 0: continue
        c, n1, n2 = candles[i], candles[i+1], candles[i+2]
        if c["close"]<c["open"] and n1["close"]>n1["open"] and n2["close"]>n2["open"] and n2["close"]>c["high"]:
            ob_bull = True
        if c["close"]>c["open"] and n1["close"]<n1["open"] and n2["close"]<n2["open"] and n2["close"]<c["low"]:
            ob_bear = True

    # FVG
    if len(candles) >= 3:
        c1,c3 = candles[-3], candles[-1]
        fvg_bull = c3["low"]  > c1["high"]
        fvg_bear = c3["high"] < c1["low"]
    else:
        fvg_bull = fvg_bear = False

    # Liquidity Sweep
    recent5 = candles[-5:]
    prev_lows  = [c["low"]  for c in recent5[:-1]]
    prev_highs = [c["high"] for c in recent5[:-1]]
    last = recent5[-1]
    sweep_bull = last["low"]  < min(prev_lows)  and last["close"] > min(prev_lows)
    sweep_bear = last["high"] > max(prev_highs) and last["close"] < max(prev_highs)

    # EMA trend
    e20 = ema(closes, 20)
    e50 = ema(closes, min(50, len(closes)//2))
    ema_bull = e20 and e50 and e20 > e50 and price > e20
    ema_bear = e20 and e50 and e20 < e50 and price < e20

    # RSI
    r = rsi(closes)
    rsi_bull = r and 50 < r < 75
    rsi_sell = r and 25 < r < 50

    score_buy = (bos_bull*2 + choch_bull*2 + ob_bull*1 + fvg_bull*1 + sweep_bull*1 + ema_bull*1 + rsi_bull*1)
    score_sell= (bos_bear*2 + choch_bear*2 + ob_bear*1 + fvg_bear*1 + sweep_bear*1 + ema_bear*1 + rsi_sell*1)

    return {
        "score_buy":  score_buy,
        "score_sell": score_sell,
        "bos_bull": bos_bull, "bos_bear": bos_bear,
        "choch_bull": choch_bull, "choch_bear": choch_bear,
        "ob_bull": ob_bull, "ob_bear": ob_bear,
        "fvg_bull": fvg_bull, "fvg_bear": fvg_bear,
        "sweep_bull": sweep_bull, "sweep_bear": sweep_bear,
        "ema_bull": ema_bull, "ema_bear": ema_bear,
        "rsi": r,
    }

# ── Análise Multi-Timeframe ───────────────────────────────────
def analyze_mtf(symbol):
    s = state[symbol]
    m15 = smc_analysis(s["candles_m15"], "M15")
    h1  = smc_analysis(s["candles_h1"],  "H1")
    h4  = smc_analysis(s["candles_h4"],  "H4")

    if not all([m15, h1, h4]):
        return None

    candles = s["candles_h1"]
    if not candles: return None
    price   = candles[-1]["close"]
    atr_val = atr(candles, 14)
    if not atr_val: return None

    print(f"[{symbol}] M15 buy={m15['score_buy']} sell={m15['score_sell']} | H1 buy={h1['score_buy']} sell={h1['score_sell']} | H4 buy={h4['score_buy']} sell={h4['score_sell']}")

    # ── BUY: H1 + H4 obrigatórios, M15 bônus ─────────────────
    buy_confirmed = (
        h1["score_buy"] >= 4 and
        h4["score_buy"] >= 3 and
        h1["score_buy"] > h1["score_sell"] and
        h4["score_buy"] > h4["score_sell"]
    )
    m15_bonus_buy  = m15["score_buy"]  >= 3 and m15["score_buy"]  > m15["score_sell"]

    # ── SELL: H1 + H4 obrigatórios, M15 bônus ────────────────
    sell_confirmed = (
        h1["score_sell"] >= 4 and
        h4["score_sell"] >= 3 and
        h1["score_sell"] > h1["score_buy"] and
        h4["score_sell"] > h4["score_buy"]
    )
    m15_bonus_sell = m15["score_sell"] >= 3 and m15["score_sell"] > m15["score_buy"]

    # Confiança sobe se M15 também confirmar
    total_buy  = h1["score_buy"]  + h4["score_buy"]  + (m15["score_buy"]  if m15_bonus_buy  else 0)
    total_sell = h1["score_sell"] + h4["score_sell"] + (m15["score_sell"] if m15_bonus_sell else 0)
    max_score  = 18
    conf = round(max(total_buy, total_sell) / max_score * 100)

    if buy_confirmed:
        return {
            "signal": "BUY", "confidence": conf, "price": price, "atr": atr_val,
            "tp1": price + atr_val * 3.0,
            "tp2": price + atr_val * 5.0,
            "sl":  price - atr_val * 2.0,
            "m15": m15, "h1": h1, "h4": h4,
        }
    if sell_confirmed:
        return {
            "signal": "SELL", "confidence": conf, "price": price, "atr": atr_val,
            "tp1": price - atr_val * 3.0,
            "tp2": price - atr_val * 5.0,
            "sl":  price + atr_val * 2.0,
            "m15": m15, "h1": h1, "h4": h4,
        }
    return None

# ── Mensagens ─────────────────────────────────────────────────
def fmt_check(v): return "✅" if v else "❌"

def msg_signal(market_name, r):
    d   = r["signal"] == "BUY"
    arr = "📈" if d else "📉"
    dir = "🟢 COMPRA" if d else "🔴 VENDA"
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    rr  = round(abs(r["tp1"]-r["price"])/abs(r["price"]-r["sl"]), 1)
    stars = "⭐⭐⭐⭐⭐" if r["confidence"]>=85 else "⭐⭐⭐⭐" if r["confidence"]>=75 else "⭐⭐⭐"
    m15,h1,h4 = r["m15"], r["h1"], r["h4"]
    key = "bull" if d else "bear"
    return (
        f"{arr} <b>SINAL SMC MTF — {market_name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Direção: <b>{dir}</b>\n"
        f"💰 Entrada: <b>{r['price']:.2f}</b>\n"
        f"✅ TP1: <b>{r['tp1']:.2f}</b>\n"
        f"✅ TP2: <b>{r['tp2']:.2f}</b>\n"
        f"❌ Stop Loss: <b>{r['sl']:.2f}</b>\n"
        f"📐 Risco/Retorno: <b>1:{rr}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 Confirmações SMC:\n"
        f"  {fmt_check(m15[f'bos_{key}'])} BOS   · {fmt_check(h1[f'bos_{key}'])} BOS   · {fmt_check(h4[f'bos_{key}'])} BOS\n"
        f"  {fmt_check(m15[f'choch_{key}'])} CHoCH · {fmt_check(h1[f'choch_{key}'])} CHoCH · {fmt_check(h4[f'choch_{key}'])} CHoCH\n"
        f"  {fmt_check(m15[f'ob_{key}'])} OB    · {fmt_check(h1[f'ob_{key}'])} OB    · {fmt_check(h4[f'ob_{key}'])} OB\n"
        f"  {fmt_check(m15[f'fvg_{key}'])} FVG   · {fmt_check(h1[f'fvg_{key}'])} FVG   · {fmt_check(h4[f'fvg_{key}'])} FVG\n"
        f"  {fmt_check(m15[f'sweep_{key}'])} Sweep · {fmt_check(h1[f'sweep_{key}'])} Sweep · {fmt_check(h4[f'sweep_{key}'])} Sweep\n"
        f"         M15          H1           H4\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔒 Confiança: <b>{r['confidence']}%</b> {stars}\n"
        f"⏰ {now}\n\n"
        f"⚠️ <i>Não é recomendação financeira. Use gestão de risco.</i>"
    )

def msg_tp1(name, sig, tp1):
    return f"✅ <b>TP1 ATINGIDO — {name}</b>\nSinal {'COMPRA 🟢' if sig=='BUY' else 'VENDA 🔴'}\nPreço: <b>{tp1:.2f}</b>\n💡 Mova o stop para a entrada."

def msg_tp2(name, sig, tp2):
    return f"🏆 <b>TP2 ATINGIDO — {name}</b>\nSinal {'COMPRA 🟢' if sig=='BUY' else 'VENDA 🔴'}\nPreço: <b>{tp2:.2f}</b>\n🎉 Lucro máximo capturado!"

def msg_sl(name, sig, sl):
    return f"🛑 <b>STOP LOSS — {name}</b>\nSinal {'COMPRA 🟢' if sig=='BUY' else 'VENDA 🔴'}\nPreço: <b>{sl:.2f}</b>\n📌 Aguardando próximo sinal."

# ── TP/SL ─────────────────────────────────────────────────────
async def check_tpsl(symbol, name, price):
    s = state[symbol]
    if not s["last_signal"] or s["sl_hit"] or (s["tp1_hit"] and s["tp2_hit"]): return
    b = s["last_signal"] == "BUY"
    if not s["tp1_hit"]:
        if (b and price >= s["tp1"]) or (not b and price <= s["tp1"]):
            s["tp1_hit"] = True
            await send_telegram(msg_tp1(name, s["last_signal"], s["tp1"]))
    if s["tp1_hit"] and not s["tp2_hit"]:
        if (b and price >= s["tp2"]) or (not b and price <= s["tp2"]):
            s["tp2_hit"] = True
            await send_telegram(msg_tp2(name, s["last_signal"], s["tp2"]))
            s["last_signal"] = None
    if not s["sl_hit"]:
        if (b and price <= s["sl"]) or (not b and price >= s["sl"]):
            s["sl_hit"] = True
            await send_telegram(msg_sl(name, s["last_signal"], s["sl"]))
            s["last_signal"] = None

async def run_signal_check(symbol, name):
    s = state[symbol]
    result = analyze_mtf(symbol)
    if not result: return
    now = asyncio.get_event_loop().time()
    if (s["last_signal"] == result["signal"] and
            s["last_signal_time"] and
            now - s["last_signal_time"] < 4*3600): return
    s.update({
        "last_signal": result["signal"], "last_signal_time": now,
        "tp1": result["tp1"], "tp2": result["tp2"], "sl": result["sl"],
        "tp1_hit": False, "tp2_hit": False, "sl_hit": False,
    })
    print(f"[{symbol}] 🚨 SINAL {result['signal']} conf={result['confidence']}%")
    await send_telegram(msg_signal(name, result))

# ── Monitor por mercado ───────────────────────────────────────
async def monitor_market(market):
    symbol = market["symbol"]
    name   = market["name"]
    print(f"[{symbol}] Iniciando monitoramento SMC Multi-Timeframe...")

    while True:
        try:
            # Carregar os 3 timeframes
            m15 = await fetch_candles(symbol, "15m", "5d")
            h1  = await fetch_candles(symbol, "1h",  "30d")
            h4  = await fetch_candles(symbol, "1h",  "60d")  # agrupa para H4 abaixo

            # Agrupa H1 em H4 (cada 4 candles H1 = 1 candle H4)
            h4_candles = []
            for i in range(0, len(h4)-3, 4):
                group = h4[i:i+4]
                h4_candles.append({
                    "epoch": group[0]["epoch"],
                    "open":  group[0]["open"],
                    "high":  max(c["high"] for c in group),
                    "low":   min(c["low"]  for c in group),
                    "close": group[-1]["close"],
                })

            if m15: state[symbol]["candles_m15"] = m15
            if h1:  state[symbol]["candles_h1"]  = h1
            if h4_candles: state[symbol]["candles_h4"] = h4_candles

            print(f"[{symbol}] M15={len(m15)} H1={len(h1)} H4={len(h4_candles)} candles")
            await run_signal_check(symbol, name)

            # Verifica preço a cada 60s para TP/SL
            for _ in range(5):
                await asyncio.sleep(60)
                price = await fetch_price(symbol)
                if price:
                    await check_tpsl(symbol, name, price)

        except Exception as e:
            print(f"[{symbol}] Erro: {e}. Tentando em 30s...")
            await asyncio.sleep(30)

# ── Main ──────────────────────────────────────────────────────
async def main():
    print("🚀 Bot SMC Multi-Timeframe iniciado!")
    await send_telegram(
        "🤖 <b>Bot SMC — US30 e Nasdaq100</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 Mercados: US30 · Nasdaq 100\n"
        "📐 Estratégia: SMC Multi-Timeframe\n"
        "⏱ Timeframes: M15 + H1 + H4\n"
        "🔍 BOS · CHoCH · OB · FVG · Sweep · EMA · RSI\n"
        "⚡ Sinal apenas quando M15 + H1 + H4 confirmam\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Aguardando confirmação nos 3 timeframes... 🎯"
    )
    await asyncio.gather(*[asyncio.create_task(monitor_market(m)) for m in MARKETS])

if __name__ == "__main__":
    asyncio.run(main())
