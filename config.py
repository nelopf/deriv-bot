"""
config.py — Configurações para Jump 25 Index (Deriv)
"""

import os
import sys

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8654852978:AAGoPa-oA9xeRb5Oh3lLHulVzqfM0JXaFcc")
CHAT_ID        = os.environ.get("CHAT_ID", "7635744352")

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("ERRO: Configure TELEGRAM_TOKEN e CHAT_ID no Railway.")
    sys.exit(1)

# ─── DERIV ────────────────────────────────────────────────────────────────────

DERIV_APP_ID   = "1089"                          # App ID público da Deriv
DERIV_SYMBOL   = "J25"                           # Jump 25 Index
SYMBOL_DISPLAY = "Jump 25 Index"                 # Nome exibido no sinal
DERIV_WS_URL   = f"wss://ws.binaryws.com/websockets/v3?app_id={DERIV_APP_ID}"

TIMEFRAMES = ["M15", "M60", "H4"]               # 15min, 1h, 4h na Deriv
TIMEFRAME_SECONDS = {
    "M15": 900,
    "M60": 3600,
    "H4":  14400,
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

# ─── STOP LOSS E TAKE PROFIT (multiplicadores do ATR) ─────────────────────────

SL_ATR_MULT  = 1.2
TP1_ATR_MULT = 1.5
TP2_ATR_MULT = 2.5
TP3_ATR_MULT = 4.0

# ─── FILTROS DE QUALIDADE ─────────────────────────────────────────────────────

MIN_CONFIDENCE   = 60
MIN_RR           = 1.3
LOOKBACK_CANDLES = 200
CHECK_INTERVAL   = 60
COOLDOWN_SECONDS = 3600
