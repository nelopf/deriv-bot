"""
analyzer.py — Coleta de dados OHLCV e análise técnica
Calcula todos os indicadores e retorna o sinal por timeframe.
"""

import ccxt
import pandas as pd
import pandas_ta as ta

import config

# ─── EXCHANGE ─────────────────────────────────────────────────────────────────

exchange = getattr(ccxt, config.EXCHANGE)({
    "rateLimit": 1200,
    "enableRateLimit": True,
})

# ─── COLETA DE DADOS ──────────────────────────────────────────────────────────

def fetch_ohlcv(timeframe: str, limit: int = config.LOOKBACK_CANDLES) -> pd.DataFrame:
    """Busca velas OHLCV da exchange e calcula todos os indicadores."""
    raw = exchange.fetch_ohlcv(config.SYMBOL, timeframe=timeframe, limit=limit)
    df  = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)

    # RSI
    df["rsi"] = ta.rsi(df["close"], length=config.RSI_PERIOD)

    # MACD
    macd = ta.macd(
        df["close"],
        fast=config.MACD_FAST,
        slow=config.MACD_SLOW,
        signal=config.MACD_SIGNAL,
    )
    f, s, sig = config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL
    df["macd"]        = macd[f"MACD_{f}_{s}_{sig}"]
    df["macd_signal"] = macd[f"MACDs_{f}_{s}_{sig}"]
    df["macd_hist"]   = macd[f"MACDh_{f}_{s}_{sig}"]

    # EMA
    df["ema_short"] = ta.ema(df["close"], length=config.EMA_SHORT)
    df["ema_long"]  = ta.ema(df["close"], length=config.EMA_LONG)

    # Bollinger Bands
    bb = ta.bbands(df["close"], length=config.BB_PERIOD, std=config.BB_STD)
    p, std = config.BB_PERIOD, config.BB_STD
    df["bb_upper"] = bb[f"BBU_{p}_{std}"]
    df["bb_lower"] = bb[f"BBL_{p}_{std}"]
    df["bb_mid"]   = bb[f"BBM_{p}_{std}"]

    # Stochastic RSI
    stoch = ta.stochrsi(
        df["close"],
        length=config.RSI_PERIOD,
        rsi_length=config.RSI_PERIOD,
        k=14, d=3,
    )
    rp = config.RSI_PERIOD
    df["stoch_k"] = stoch[f"STOCHRSIk_{rp}_{rp}_14_3"]
    df["stoch_d"] = stoch[f"STOCHRSId_{rp}_{rp}_14_3"]

    # OBV
    df["obv"] = ta.obv(df["close"], df["volume"])

    # ATR
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=config.ATR_PERIOD)

    return df.dropna()

# ─── ANÁLISE DOS INDICADORES ──────────────────────────────────────────────────

def analyze(df: pd.DataFrame) -> dict:
    """
    Avalia cada indicador na última vela fechada.
    Retorna direção (COMPRA / VENDA / NEUTRO), confiança e detalhes.
    """
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

    # 2. MACD — cruzamento de linhas
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
        details["MACD"] = ("⚪", f"histograma +{last['macd_hist']:.1f}")
    else:
        sell_pts += 0.5
        details["MACD"] = ("⚪", f"histograma {last['macd_hist']:.1f}")

    # 3. EMA 20 / 50 — tendência
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

    # 4. Bollinger Bands — extremos de volatilidade
    total += 1
    bb_width = (last["bb_upper"] - last["bb_lower"]) / last["bb_mid"]
    if last["close"] <= last["bb_lower"] and bb_width > 0.02:
        buy_pts += 1
        details["Bollinger"] = ("🟢", "toque banda inferior")
    elif last["close"] >= last["bb_upper"] and bb_width > 0.02:
        sell_pts += 1
        details["Bollinger"] = ("🔴", "toque banda superior")
    else:
        details["Bollinger"] = ("⚪", f"largura {bb_width:.3f}")

    # 5. Stochastic RSI — confirmação de reversão
    total += 1
    k, d = last["stoch_k"], last["stoch_d"]
    if k < 20 and k > d:
        buy_pts += 1
        details["Stoch RSI"] = ("🟢", f"K={k:.1f} — sobrevenda")
    elif k > 80 and k < d:
        sell_pts += 1
        details["Stoch RSI"] = ("🔴", f"K={k:.1f} — sobrecompra")
    else:
        details["Stoch RSI"] = ("⚪", f"K={k:.1f}")

    # 6. OBV — força do volume (últimas 5 velas)
    total += 1
    obv_slice = df["obv"].iloc[-5:]
    if obv_slice.is_monotonic_increasing:
        buy_pts += 1
        details["OBV"] = ("🟢", "volume crescente")
    elif obv_slice.is_monotonic_decreasing:
        sell_pts += 1
        details["OBV"] = ("🔴", "volume decrescente")
    else:
        details["OBV"] = ("⚪", "volume lateral")

    # Resultado final
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
        "price":      last["close"],
        "atr":        last["atr"],
        "details":    details,
    }

# ─── CONSENSO MULTI-TIMEFRAME ─────────────────────────────────────────────────

def get_consensus() -> dict | None:
    """
    Analisa todos os timeframes e retorna consenso.
    Sinal só é válido se pelo menos 2 de 3 timeframes concordarem.
    """
    results = {}
    for tf in config.TIMEFRAMES:
        try:
            df = fetch_ohlcv(tf)
            results[tf] = analyze(df)
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
        return None  # Sem consenso

    confidence = round(sum(confs) / len(confs))

    if confidence < config.MIN_CONFIDENCE:
        return None  # Confiança insuficiente

    # Referência de preço e ATR: usar o 1h
    base   = results.get("1h") or list(results.values())[0]
    price  = base["price"]
    atr    = base["atr"]
    levels = calc_levels(price, atr, direction)

    if levels["rr1"] < config.MIN_RR:
        return None  # R:R insuficiente

    return {
        "direction":  direction,
        "confidence": confidence,
        "price":      price,
        "atr":        round(atr, 2),
        "levels":     levels,
        "timeframes": results,
    }

# ─── NÍVEIS DE SL E TP ────────────────────────────────────────────────────────

def calc_levels(price: float, atr: float, direction: str) -> dict:
    """
    Calcula Stop Loss e 3 Take Profits com base no ATR.
    COMPRA: SL abaixo do preço, TPs acima.
    VENDA:  SL acima do preço, TPs abaixo.
    """
    if direction == "COMPRA":
        sl  = round(price - atr * config.SL_ATR_MULT,  2)
        tp1 = round(price + atr * config.TP1_ATR_MULT, 2)
        tp2 = round(price + atr * config.TP2_ATR_MULT, 2)
        tp3 = round(price + atr * config.TP3_ATR_MULT, 2)
    else:
        sl  = round(price + atr * config.SL_ATR_MULT,  2)
        tp1 = round(price - atr * config.TP1_ATR_MULT, 2)
        tp2 = round(price - atr * config.TP2_ATR_MULT, 2)
        tp3 = round(price - atr * config.TP3_ATR_MULT, 2)

    risk = abs(price - sl)
    rr1  = round(abs(tp1 - price) / risk, 2) if risk else 0
    rr2  = round(abs(tp2 - price) / risk, 2) if risk else 0
    rr3  = round(abs(tp3 - price) / risk, 2) if risk else 0

    pct = lambda a, b: round(abs(a - b) / price * 100, 2)

    return {
        "sl":      sl,
        "tp1":     tp1,
        "tp2":     tp2,
        "tp3":     tp3,
        "rr1":     rr1,
        "rr2":     rr2,
        "rr3":     rr3,
        "pct_sl":  pct(price, sl),
        "pct_tp1": pct(tp1, price),
        "pct_tp2": pct(tp2, price),
        "pct_tp3": pct(tp3, price),
        "risk":    round(risk, 2),
    }
