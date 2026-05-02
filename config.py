"""
config.py — Configurações centrais do bot
Todas as variáveis de ambiente são lidas aqui.
"""

import os
import sys

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID        = os.environ.get("CHAT_ID", "")

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("ERRO: Configure as variáveis TELEGRAM_TOKEN e CHAT_ID no Railway.")
    sys.exit(1)

# ─── EXCHANGE ─────────────────────────────────────────────────────────────────

SYMBOL     = "BTC/USDT"
EXCHANGE   = "binance"           # Alternativas: "bybit", "okx", "kucoin"
TIMEFRAMES = ["15m", "1h", "4h"] # Consenso multi-timeframe

# ─── INDICADORES ──────────────────────────────────────────────────────────────

RSI_PERIOD     = 14
RSI_OVERSOLD   = 30
RSI_OVERBOUGHT = 70

EMA_SHORT = 20
EMA_LONG  = 50

MACD_FAST   = 12
MACD_SLOW   = 26
MACD_SIGNAL = 9

BB_PERIOD = 20
BB_STD    = 2.0

ATR_PERIOD = 14

# ─── STOP LOSS E TAKE PROFIT (multiplicadores do ATR) ─────────────────────────

SL_ATR_MULT  = 1.2   # Stop Loss  = entrada ± (ATR × 1.2)
TP1_ATR_MULT = 1.5   # TP1        = entrada ± (ATR × 1.5)
TP2_ATR_MULT = 2.5   # TP2        = entrada ± (ATR × 2.5)
TP3_ATR_MULT = 4.0   # TP3        = entrada ± (ATR × 4.0)

# ─── FILTROS DE QUALIDADE ─────────────────────────────────────────────────────

MIN_CONFIDENCE   = 65    # % mínimo de confiança para emitir sinal
MIN_RR           = 1.5   # Relação Risco/Retorno mínima (baseada no TP1)
LOOKBACK_CANDLES = 200   # Velas para cálculo dos indicadores

# ─── EXECUÇÃO ─────────────────────────────────────────────────────────────────

CHECK_INTERVAL   = 60    # Segundos entre cada verificação
COOLDOWN_SECONDS = 3600  # Cooldown entre sinais iguais (1 hora)
