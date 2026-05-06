"""
analyzer.py — Volatility 75 Index com estratégia melhorada
Adiciona: tendência ADX, padrões de vela, suporte/resistência
"""

import json
import threading
import pandas as pd
import ta
import websocket

import config

# ─── BUSCAR CANDLES ───────────────────────────────────────────────────────────

def fetch_candles(granularity_seconds: int, count: int = config.LOOKBACK_CANDLES) -> pd.DataFrame:
    result = {"data": None, "error": None}
    event  = threading.Event()

    def on_open(ws):
        ws.send(json.dumps({
            "ticks_history": config.DERIV_SYMBOL,
            "adjust_start_time": 1,
            "count": 500,
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
    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=config.RSI_PERIOD).rsi()

    # MACD
    macd = ta.trend.MACD(df["close"],
        window_fast=config.MACD_FAST,
        window_slow=config.MACD_SLOW,
        window_sign=config.MACD_SIGNAL)
    df["macd"]        = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"]   = macd.macd_diff()

    # EMA
    df["ema_short"] = ta.trend.EMAIndicator(df["close"], window=config.EMA_SHORT).ema_indicator()
    df["ema_long"]  = ta.trend.EMAIndicator(df["close"], window=config.EMA_LONG).ema_indicator()
    df["ema_100"]   = ta.trend.EMAIndicator(df["close"], window=100).ema_indicator()

    # Bollinger Bands
    bb = ta.volatility.BollingerBands(df["close"], window=config.BB_PERIOD, window_dev=config.BB_STD)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_mid"]   = bb.bollinger_mavg()
    df["bb_pct"]   = bb.bollinger_pband()  # 0=banda inferior, 1=banda superior

    # Stochastic RSI
    stoch = ta.momentum.StochRSIIndicator(df["close"], window=config.RSI_PERIOD)
    df["stoch_k"] = stoch.stochrsi_k()
    df["stoch_d"] = stoch.stochrsi_d()

    # ADX — força da tendência
    adx = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=14)
    df["adx"]    = adx.adx()
    df["adx_pos"] = adx.adx_pos()  # +DI
    df["adx_neg"] = adx.adx_neg()  # -DI

    # ATR
    df["atr"] = ta.volatility.AverageTrueRange(
        df["high"], df["low"], df["close"], window=config.ATR_PERIOD
    ).average_true_range()

    return df.dropna()

# ─── PADRÕES DE VELA ──────────────────────────────────────────────────────────

def detect_candle_pattern(df: pd.DataFrame) -> str:
    """Detecta padrões de reversão nas últimas 3 velas."""
    l  = df.iloc[-1]
    p  = df.iloc[-2]
    p2 = df.iloc[-3]

    body_l  = abs(l["close"] - l["open"])
    body_p  = abs(p["close"] - p["open"])
    range_l = l["high"] - l["low"]

    # Hammer (sinal de compra)
    lower_shadow = min(l["open"], l["close"]) - l["low"]
    upper_shadow = l["high"] - max(l["open"], l["close"])
    if (lower_shadow > body_l * 2 and upper_shadow < body_l * 0.3
            and p["close"] < p["open"]):  # vela anterior bearish
        return "BUY"

    # Shooting Star (sinal de venda)
    if (upper_shadow > body_l * 2 and lower_shadow < body_l * 0.3
            and p["close"] > p["open"]):  # vela anterior bullish
        return "SELL"

    # Engulfing bullish
    if (l["close"] > l["open"] and p["close"] < p["open"]
            and l["open"] < p["close"] and l["close"] > p["open"]):
        return "BUY"

    # Engulfing bearish
    if (l["close"] < l["open"] and p["close"] > p["open"]
            and l["open"] > p["close"] and l["close"] < p["open"]):
        return "SELL"

    # Doji (indecisão)
    if body_l < range_l * 0.1:
        return "NEUTRO"

    return "NONE"

# ─── ANÁLISE ──────────────────────────────────────────────────────────────────

def analyze(df: pd.DataFrame) -> dict:
    if len(df) < 5:
        raise Exception("Dados insuficientes")
    last = df.iloc[-1]
    prev = df.iloc[-2]
    buy_pts = sell_pts = 0
    total   = 0
    details = {}

    # 1. RSI
    total += 1
    rsi = last["rsi"]
    if rsi < config.RSI_OVERSOLD:
        buy_pts += 1
        details["RSI"] = ("🟢", f"{rsi:.1f} — sobrevenda")
    elif rsi > config.RSI_OVERBOUGHT:
        sell_pts += 1
        details["RSI"] = ("🔴", f"{rsi:.1f} — sobrecompra")
    else:
        details["RSI"] = ("⚪", f"{rsi:.1f} — neutro")

    # 2. MACD
    total += 1
    if prev["macd"] < prev["macd_signal"] and last["macd"] > last["macd_signal"]:
        buy_pts += 1
        details["MACD"] = ("🟢", "cruzamento bullish")
    elif prev["macd"] > prev["macd_signal"] and last["macd"] < last["macd_signal"]:
        sell_pts += 1
        details["MACD"] = ("🔴", "cruzamento bearish")
    elif last["macd_hist"] > 0:
        buy_pts += 0.5
        details["MACD"] = ("⚪", f"hist +{last['macd_hist']:.2f}")
    else:
        sell_pts += 0.5
        details["MACD"] = ("⚪", f"hist {last['macd_hist']:.2f}")

    # 3. EMA 20/50
    total += 1
    if prev["ema_short"] < prev["ema_long"] and last["ema_short"] > last["ema_long"]:
        buy_pts += 1
        details["EMA 20/50"] = ("🟢", "golden cross")
    elif prev["ema_short"] > prev["ema_long"] and last["ema_short"] < last["ema_long"]:
        sell_pts += 1
        details["EMA 20/50"] = ("🔴", "death cross")
    elif last["ema_short"] > last["ema_long"]:
        buy_pts += 0.5
        details["EMA 20/50"] = ("⚪", "acima EMA50")
    else:
        sell_pts += 0.5
        details["EMA 20/50"] = ("⚪", "abaixo EMA50")

    # 4. EMA 200 — tendência principal
    total += 1
    if last["close"] > last["ema_100"]:
        buy_pts += 1
        details["EMA 100"] = ("🟢", "acima — tendência alta")
    else:
        sell_pts += 1
        details["EMA 100"] = ("🔴", "abaixo — tendência baixa")

    # 5. Bollinger Bands
    total += 1
    if last["bb_pct"] < 0.05:
        buy_pts += 1
        details["Bollinger"] = ("🟢", "toque banda inferior")
    elif last["bb_pct"] > 0.95:
        sell_pts += 1
        details["Bollinger"] = ("🔴", "toque banda superior")
    elif last["bb_pct"] < 0.3:
        buy_pts += 0.5
        details["Bollinger"] = ("⚪", f"zona baixa {last['bb_pct']:.2f}")
    else:
        sell_pts += 0.5
        details["Bollinger"] = ("⚪", f"zona alta {last['bb_pct']:.2f}")

    # 6. Stochastic RSI
    total += 1
    k, d = last["stoch_k"], last["stoch_d"]
    if k < 0.2 and k > d:
        buy_pts += 1
        details["Stoch RSI"] = ("🟢", f"K={k:.2f} — sobrevenda")
    elif k > 0.8 and k < d:
        sell_pts += 1
        details["Stoch RSI"] = ("🔴", f"K={k:.2f} — sobrecompra")
    else:
        details["Stoch RSI"] = ("⚪", f"K={k:.2f}")

    # 7. ADX — força da tendência
    total += 1
    adx = last["adx"]
    if adx > 25 and last["adx_pos"] > last["adx_neg"]:
        buy_pts += 1
        details["ADX"] = ("🟢", f"{adx:.1f} — tendência forte alta")
    elif adx > 25 and last["adx_neg"] > last["adx_pos"]:
        sell_pts += 1
        details["ADX"] = ("🔴", f"{adx:.1f} — tendência forte baixa")
    else:
        details["ADX"] = ("⚪", f"{adx:.1f} — sem tendência clara")

    # 8. Padrão de vela
    total += 1
    pattern = detect_candle_pattern(df)
    if pattern == "BUY":
        buy_pts += 1
        details["Vela"] = ("🟢", "padrão bullish")
    elif pattern == "SELL":
        sell_pts += 1
        details["Vela"] = ("🔴", "padrão bearish")
    else:
        details["Vela"] = ("⚪", "sem padrão")

    if buy_pts > sell_pts:
        direction  = "COMPRA"
        confidence = round((buy_pts / total) * 100)
    elif sell_pts > buy_pts:
        direction  = "VENDA"
        confidence = round((sell_pts / total) * 100)
    else:
        direction  = "NEUTRO"
        confidence = 50

    return {
        "direction":  direction,
        "confidence": confidence,
        "price":      float(last["close"]),
        "atr":        float(last["atr"]),
        "details":    details,
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
            print(f"[{tf_name}] {results[tf_name]['direction']} | {results[tf_name]['confidence']}%")
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
