"""
config.py — Configurações para Volatility 75 Index (Deriv)
"""

import os
import sys

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("ERRO: Configure TELEGRAM_TOKEN e CHAT_ID no Railway.")
    sys.exit(1)

# ─── DERIV ────────────────────────────────────────────────────────────────────

DERIV_APP_ID   = "1089"
DERIV_SYMBOL   = "R_75"              # Volatility 75 Index
SYMBOL_DISPLAY = "Volatility 75 Index"
DERIV_WS_URL   = "wss://ws.binaryws.com/websockets/v3?app_id=1089"

# Timeframes adequados para V75
TIMEFRAMES = ["M5", "M15", "M60"]
TIMEFRAME_SECONDS = {
    "M5":  300,
    "M15": 900,
    "M60": 3600,
}

# ─── INDICADORES ──────────────────────────────────────────────────────────────

RSI_PERIOD     = 14
RSI_OVERSOLD   = 30
RSI_OVERBOUGHT = 70
EMA_SHORT      = 20
EMA_LONG       = 50
MACD_FAST      = 12
MACD_SLOW      = 26
MACD_SIGNAL    = 9
BB_PERIOD      = 20
BB_STD         = 2.0
ATR_PERIOD     = 14

# ─── STOP LOSS E TAKE PROFIT ──────────────────────────────────────────────────

SL_ATR_MULT  = 1.2
TP1_ATR_MULT = 1.5
TP2_ATR_MULT = 2.5
TP3_ATR_MULT = 4.0

# ─── FILTROS ──────────────────────────────────────────────────────────────────

MIN_CONFIDENCE   = 55
MIN_RR           = 1.2
LOOKBACK_CANDLES = 200
CHECK_INTERVAL   = 60
COOLDOWN_SECONDS = 1200
