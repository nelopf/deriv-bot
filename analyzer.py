"""
analyzer.py — Volatility 75 — Estratégia simplificada e decisiva
Usa apenas indicadores com maior peso de decisão
"""

import json
import threading
import pandas as pd
import ta
import websocket

import config

# ─── BUSCAR CANDLES ───────────────────────────────────────────────────────────

def fetch_candles(granularity_seconds: int, count: int = 500) -> pd.DataFrame:
    result = {"data": None, "error": None}
    event  = threading.Event()

    def on_open(ws):
        ws.send(json.dumps({
            "ticks_history": config.DERIV_SYMBOL,
            "adjust_start_time": 1,
            "count": count,
            "end": "latest",
            "granularity": granularity_seconds,
            "style": "candles",
        }))

    def on_message(ws, message):
        data = json.loads(message)
        if "candles" in data:
            result["data"] = data["candles"]
        elif "error" in data:
            result["error"] = data["error"]["message"]
        ws.close()
        event.set()

    def on_error(ws, error):
        result["error"] = str(error)
        event.set()

    ws = websocket.WebSocketApp(
        config.DERIV_WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
    )
    t = threading.Thread(target=ws.run_forever)
    t.daemon = True
    t.start()
    event.wait(timeout=15)

    if result["error"]:
        raise Exception(f"Deriv erro: {result['error']}")
    if not result["data"]:
        raise Exception("Sem dados da Deriv")

    df = pd.DataFrame(result["data"])
    df["timestamp"] = pd.to_datetime(df["epoch"], unit="s")
    df.set_index("timestamp", inplace=True)
    df = df[["open", "high", "low", "close"]].astype(float)
    df["volume"] = 1
    return df

# ─── PREÇO EM TEMPO REAL ──────────────────────────────────────────────────────

def get_live_price() -> float:
    result = {"price": None, "error": None}
    event  = threading.Event()

    def on_open(ws):
        ws.send(json.dumps({"ticks": config.DERIV_SYMBOL, "subscribe": 0}))

    def on_message(ws, message):
        data = json.loads(message)
        if "tick" in data:
            result["price"] = float(data["tick"]["quote"])
        elif "error" in data:
            result["error"] = data["error"]["message"]
        ws.close()
        event.set()

    def on_error(ws, error):
        result["error"] = str(error)
        event.set()

    ws = websocket.WebSocketApp(
        config.DERIV_WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
    )
    t = threading.Thread(target=ws.run_forever)
    t.daemon = True
    t.start()
    event.wait(timeout=10)

    if result["error"]:
        raise Exception(f"Erro preço: {result['error']}")
    if result["price"] is None:
        raise Exception("Preço não recebido")
    return result["price"]

# ─── INDICADORES ──────────────────────────────────────────────────────────────

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # RSI
    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()

    # MACD
    macd = ta.trend.MACD(df["close"], window_fast=12, window_slow=26, window_sign=9)
    df["macd"]        = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"]   = macd.macd_diff()

    # EMA 50 e EMA 200
    df["ema50"]  = ta.trend.EMAIndicator(df["close"], window=50).ema_indicator()
    df["ema200"] = ta.trend.EMAIndicator(df["close"], window=200).ema_indicator()

    # ATR
    df["atr"] = ta.volatility.AverageTrueRange(
        df["high"], df["low"], df["close"], window=14
    ).average_true_range()

    return df.dropna()

# ─── ANÁLISE — 3 INDICADORES DECISIVOS ───────────────────────────────────────

def analyze(df: pd.DataFrame) -> dict:
    if len(df) < 5:
        raise Exception("Dados insuficientes")

    last = df.iloc[-1]
    prev = df.iloc[-2]
    score = 0   # positivo = compra, negativo = venda
    details = {}

    # 1. RSI — peso 2
    rsi = last["rsi"]
    if rsi < 30:
        score += 2
        details["RSI"] = ("🟢", f"{rsi:.1f} — sobrevenda forte")
    elif rsi < 40:
        score += 1
        details["RSI"] = ("🟢", f"{rsi:.1f} — zona compra")
    elif rsi > 70:
        score -= 2
        details["RSI"] = ("🔴", f"{rsi:.1f} — sobrecompra forte")
    elif rsi > 60:
        score -= 1
        details["RSI"] = ("🔴", f"{rsi:.1f} — zona venda")
    else:
        details["RSI"] = ("⚪", f"{rsi:.1f} — neutro")

    # 2. MACD cruzamento — peso 3 (mais decisivo)
    crossed_up   = prev["macd"] < prev["macd_signal"] and last["macd"] > last["macd_signal"]
    crossed_down = prev["macd"] > prev["macd_signal"] and last["macd"] < last["macd_signal"]
    if crossed_up:
        score += 3
        details["MACD"] = ("🟢", "cruzamento bullish ⚡")
    elif crossed_down:
        score -= 3
        details["MACD"] = ("🔴", "cruzamento bearish ⚡")
    elif last["macd_hist"] > 0:
        score += 1
        details["MACD"] = ("🟢", f"histograma positivo")
    else:
        score -= 1
        details["MACD"] = ("🔴", f"histograma negativo")

    # 3. EMA 50 vs EMA 200 — tendência principal — peso 3
    if last["ema50"] > last["ema200"]:
        score += 3
        details["Tendência"] = ("🟢", "EMA50 > EMA200 — alta")
    else:
        score -= 3
        details["Tendência"] = ("🔴", "EMA50 < EMA200 — baixa")

    # 4. Preço vs EMA50 — peso 2
    if last["close"] > last["ema50"]:
        score += 2
        details["Preço/EMA50"] = ("🟢", "preço acima EMA50")
    else:
        score -= 2
        details["Preço/EMA50"] = ("🔴", "preço abaixo EMA50")

    # Score máximo possível: 10, mínimo: -10
    max_score = 10
    if score >= 4:
        direction  = "COMPRA"
        confidence = min(round((score / max_score) * 100), 100)
    elif score <= -4:
        direction  = "VENDA"
        confidence = min(round((abs(score) / max_score) * 100), 100)
    else:
        direction  = "NEUTRO"
        confidence = 50

    return {
        "direction":  direction,
        "confidence": confidence,
        "price":      float(last["close"]),
        "atr":        float(last["atr"]),
        "details":    details,
        "score":      score,
    }

# ─── NÍVEIS SL / TP ───────────────────────────────────────────────────────────

def calc_levels(price: float, atr: float, direction: str) -> dict:
    if direction == "COMPRA":
        sl  = round(price - atr * config.SL_ATR_MULT,  4)
        tp1 = round(price + atr * config.TP1_ATR_MULT, 4)
        tp2 = round(price + atr * config.TP2_ATR_MULT, 4)
        tp3 = round(price + atr * config.TP3_ATR_MULT, 4)
    else:
        sl  = round(price + atr * config.SL_ATR_MULT,  4)
        tp1 = round(price - atr * config.TP1_ATR_MULT, 4)
        tp2 = round(price - atr * config.TP2_ATR_MULT, 4)
        tp3 = round(price - atr * config.TP3_ATR_MULT, 4)

    risk = abs(price - sl)
    rr1  = round(abs(tp1 - price) / risk, 2) if risk else 0
    rr2  = round(abs(tp2 - price) / risk, 2) if risk else 0
    rr3  = round(abs(tp3 - price) / risk, 2) if risk else 0
    pct  = lambda a, b: round(abs(a - b) / price * 100, 3)

    return {
        "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "rr1": rr1, "rr2": rr2, "rr3": rr3,
        "pct_sl":  pct(price, sl),
        "pct_tp1": pct(tp1, price),
        "pct_tp2": pct(tp2, price),
        "pct_tp3": pct(tp3, price),
        "risk": round(risk, 4),
    }

# ─── CONSENSO MULTI-TIMEFRAME ─────────────────────────────────────────────────

def get_consensus() -> dict | None:
    results    = {}
    tf_seconds = list(config.TIMEFRAME_SECONDS.items())

    for tf_name, tf_sec in tf_seconds:
        try:
            df = fetch_candles(tf_sec)
            df = add_indicators(df)
            results[tf_name] = analyze(df)
            print(f"[{tf_name}] {results[tf_name]['direction']} | {results[tf_name]['confidence']}% | score={results[tf_name]['score']}")
        except Exception as e:
            print(f"[ERRO] {tf_name}: {e}")
            return None

    directions = [r["direction"] for r in results.values()]
    buy_count  = directions.count("COMPRA")
    sell_count = directions.count("VENDA")

    if buy_count >= 2:
        direction = "COMPRA"
        confs = [r["confidence"] for r in results.values() if r["direction"] == "COMPRA"]
    elif sell_count >= 2:
        direction = "VENDA"
        confs = [r["confidence"] for r in results.values() if r["direction"] == "VENDA"]
    else:
        return None

    confidence = round(sum(confs) / len(confs))
    if confidence < config.MIN_CONFIDENCE:
        return None

    try:
        price = get_live_price()
    except Exception as e:
        print(f"[WARN] Preço do candle: {e}")
        base  = results.get("M15") or list(results.values())[0]
        price = base["price"]

    base   = results.get("M15") or list(results.values())[0]
    atr    = base["atr"]
    levels = calc_levels(price, atr, direction)

    if levels["rr1"] < config.MIN_RR:
        return None

    return {
        "direction":  direction,
        "confidence": confidence,
        "price":      price,
        "atr":        round(atr, 4),
        "levels":     levels,
        "timeframes": results,
    }
