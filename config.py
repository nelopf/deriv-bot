"""
config.py — Configurações para EURUSD via Alpha Vantage
"""

import os
import sys

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8654852978:AAGoPa-oA9xeRb5Oh3lLHulVzqfM0JXaFcc")
CHAT_ID        = os.environ.get("CHAT_ID", "7635744352")

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("ERRO: Configure TELEGRAM_TOKEN e CHAT_ID no Railway.")
    sys.exit(1)

# ─── ALPHA VANTAGE ────────────────────────────────────────────────────────────
# Chave gratuita — 25 requests/dia
# Gere a sua em: https://www.alphavantage.co/support/#api-key

AV_API_KEY     = os.environ.get("0LXQ7XRWD1L424HH", "0LXQ7XRWD1L424HH")
AV_BASE_URL    = "https://www.alphavantage.co/query"

# ─── SÍMBOLO ──────────────────────────────────────────────────────────────────

FROM_CURRENCY  = "EUR"
TO_CURRENCY    = "USD"
SYMBOL_DISPLAY = "EURUSD"

# Timeframes Alpha Vantage: 1min, 5min, 15min, 30min, 60min
TIMEFRAMES = ["15min", "60min", "4h"]

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

MIN_CONFIDENCE   = 65
MIN_RR           = 1.5
CHECK_INTERVAL   = 300   # 5 min (Alpha Vantage free: 25 req/dia)
COOLDOWN_SECONDS = 3600
