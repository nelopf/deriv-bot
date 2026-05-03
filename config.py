"""
config.py — Configurações para EURUSD (Yahoo Finance)
"""

import os
import sys

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("ERRO: Configure TELEGRAM_TOKEN e CHAT_ID no Railway.")
    sys.exit(1)

# ─── SÍMBOLO ──────────────────────────────────────────────────────────────────

SYMBOL         = "EURUSD=X"      # Yahoo Finance ticker
SYMBOL_DISPLAY = "EURUSD"        # Nome exibido no sinal

# Timeframes Yahoo Finance: 1m, 5m, 15m, 30m, 60m, 1d
TIMEFRAMES = ["15m", "1h", "4h"]
YF_INTERVALS = {
    "15m": {"interval": "15m", "period": "5d"},
    "1h":  {"interval": "1h",  "period": "30d"},
    "4h":  {"interval": "1h",  "period": "60d"},   # YF não tem 4h, usa 1h e agrupa
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

MIN_CONFIDENCE   = 65
MIN_RR           = 1.5
CHECK_INTERVAL   = 60
COOLDOWN_SECONDS = 3600
