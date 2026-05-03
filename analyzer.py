"""
analyzer.py — Coleta OHLCV do EURUSD via Yahoo Finance
              e calcula indicadores técnicos
"""

import pandas as pd
import ta
import yfinance as yf

import config

# ─── COLETA DE DADOS ──────────────────────────────────────────────────────────

def fetch_ohlcv(timeframe: str) -> pd.DataFrame:
    """Busca velas OHLCV do EURUSD via Yahoo Finance."""
    params = config.YF_INTERVALS[timeframe]
    df = yf.download(
        config.SYMBOL,
        interval=params["interval"],
        period=params["period"],
        progress=False,
        auto_adjust=True,
    )

    if df.empty:
        raise Exception(f"Sem dados para {timeframe}")

    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].dropna()

    # Agrupar em 4h se necessário
    if timeframe == "4h":
        df = df.resample("4h").agg({
            "open":   "first",
            "high":   "max",
            "low":    "min",
            "close":  "last",
            "volume": "sum",
        }).dropna()

    return df.tail(200)

# ─── CALCULAR INDICADORES ─────────────────────────────────────────────────────

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=config.RSI_PERIOD).rsi()

    macd = ta.trend.MACD(
        df["close"],
        window_fast=config.MACD_FAST,
        window_slow=config.MACD_SLOW,
        window_sign=config.MACD_SIGNAL,
    )
    df["macd"]        = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"]   = macd.macd_diff()

    df["ema_short"] = ta.trend.EMAIndicator(df["close"], window=config.EMA_SHORT).ema_indicator()
    df["ema_long"]  = ta.trend.EMAIndicator(df["close"], window=config.EMA_LONG).ema_indicator()

    bb = ta.volatility.BollingerBands(df["close"], window=config.BB_PERIOD, window_dev=config.BB_STD)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_mid"]   = bb.bollinger_mavg()

    stoch = ta.momentum.StochRSIIndicator(df["close"], window=config.RSI_PERIOD)
    df["stoch_k"] = stoch.stochrsi_k()
    df["stoch_d"] = stoch.stochrsi_d()

    df["atr"] = ta.volatility.AverageTrueRange(
        df["high"], df["low"], df["close"], window=config.ATR_PERIOD
    ).average_true_range()

    return df.dropna()

# ─── PREÇO EM TEMPO REAL ──────────────────────────────────────────────────────

def get_live_price() -> float:
    """Busca preço atual do EURUSD via Yahoo Finance."""
    ticker = yf.Ticker(config.SYMBOL)
    data   = ticker.history(period="1d", interval="1m")
    if data.empty:
        raise Exception("Sem preço disponível")
    return float(data["Close"].iloc[-1])

# ─── ANÁLISE DOS INDICADORES ──────────────────────────────────────────────────

def analyze(df: pd.DataFrame) -> dict:
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
    crossed_up   = prev["macd"] < prev["macd_signal"] and last["macd"] > last["macd_signal"]
    crossed_down = prev["macd"] > prev["macd_signal"] and last["macd"] < last["macd_signal"]
    if crossed_up:
        buy_pts += 1
        details["MACD"] = ("🟢", "cruzamento bullish")
    elif crossed_down:
        sell_pts += 1
        details["MACD"] = ("🔴", "cruzamento bearish")
    elif last["macd_hist"] > 0:
        buy_pts += 0.5
        details["MACD"] = ("⚪", f"hist +{last['macd_hist']:.5f}")
    else:
        sell_pts += 0.5
        details["MACD"] = ("⚪", f"hist {last['macd_hist']:.5f}")

    # 3. EMA 20/50
    total += 1
    golden = prev["ema_short"] < prev["ema_long"] and last["ema_short"] > last["ema_long"]
    death  = prev["ema_short"] > prev["ema_long"] and last["ema_short"] < last["ema_long"]
    if golden:
        buy_pts += 1
        details["EMA 20/50"] = ("🟢", "golden cross")
    elif death:
        sell_pts += 1
        details["EMA 20/50"] = ("🔴", "death cross")
    elif last["ema_short"] > last["ema_long"]:
        buy_pts += 0.5
        details["EMA 20/50"] = ("⚪", "acima da EMA50")
    else:
        sell_pts += 0.5
        details["EMA 20/50"] = ("⚪", "abaixo da EMA50")

    # 4. Bollinger Bands
    total += 1
    bb_width = (last["bb_upper"] - last["bb_lower"]) / last["bb_mid"]
    if last["close"] <= last["bb_lower"] and bb_width > 0.001:
        buy_pts += 1
        details["Bollinger"] = ("🟢", "toque banda inferior")
    elif last["close"] >= last["bb_upper"] and bb_width > 0.001:
        sell_pts += 1
        details["Bollinger"] = ("🔴", "toque banda superior")
    else:
        details["Bollinger"] = ("⚪", f"largura {bb_width:.5f}")

    # 5. Stochastic RSI
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

    # 6. OBV tendência
    total += 1
    obv_slice = df["volume"].iloc[-5:]
    price_slice = df["close"].iloc[-5:]
    if obv_slice.is_monotonic_increasing and price_slice.is_monotonic_increasing:
        buy_pts += 1
        details["Volume"] = ("🟢", "volume + preço subindo")
    elif obv_slice.is_monotonic_increasing and price_slice.is_monotonic_decreasing:
        sell_pts += 1
        details["Volume"] = ("🔴", "divergência bearish")
    else:
        details["Volume"] = ("⚪", "volume lateral")

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

# ─── NÍVEIS DE SL E TP ────────────────────────────────────────────────────────

def calc_levels(price: float, atr: float, direction: str) -> dict:
    if direction == "COMPRA":
        sl  = round(price - atr * config.SL_ATR_MULT,  5)
        tp1 = round(price + atr * config.TP1_ATR_MULT, 5)
        tp2 = round(price + atr * config.TP2_ATR_MULT, 5)
        tp3 = round(price + atr * config.TP3_ATR_MULT, 5)
    else:
        sl  = round(price + atr * config.SL_ATR_MULT,  5)
        tp1 = round(price - atr * config.TP1_ATR_MULT, 5)
        tp2 = round(price - atr * config.TP2_ATR_MULT, 5)
        tp3 = round(price - atr * config.TP3_ATR_MULT, 5)

    risk = abs(price - sl)
    rr1  = round(abs(tp1 - price) / risk, 2) if risk else 0
    rr2  = round(abs(tp2 - price) / risk, 2) if risk else 0
    rr3  = round(abs(tp3 - price) / risk, 2) if risk else 0
    pct  = lambda a, b: round(abs(a - b) / price * 100, 4)

    return {
        "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "rr1": rr1, "rr2": rr2, "rr3": rr3,
        "pct_sl":  pct(price, sl),
        "pct_tp1": pct(tp1, price),
        "pct_tp2": pct(tp2, price),
        "pct_tp3": pct(tp3, price),
        "risk": round(risk, 5),
    }

# ─── CONSENSO MULTI-TIMEFRAME ─────────────────────────────────────────────────

def get_consensus() -> dict | None:
    results = {}

    for tf in config.TIMEFRAMES:
        try:
            df = fetch_ohlcv(tf)
            df = add_indicators(df)
            results[tf] = analyze(df)
            print(f"[{tf}] {results[tf]['direction']} | {results[tf]['confidence']}%")
        except Exception as e:
            print(f"[ERRO] Timeframe {tf}: {e}")
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

    # Preço em tempo real
    try:
        price = get_live_price()
    except Exception as e:
        print(f"[WARN] Usando preço do candle: {e}")
        base  = results.get("1h") or list(results.values())[0]
        price = base["price"]

    base   = results.get("1h") or list(results.values())[0]
    atr    = base["atr"]
    levels = calc_levels(price, atr, direction)

    if levels["rr1"] < config.MIN_RR:
        return None

    return {
        "direction":  direction,
        "confidence": confidence,
        "price":      price,
        "atr":        round(atr, 5),
        "levels":     levels,
        "timeframes": results,
    }
