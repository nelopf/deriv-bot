# =============================================
# CONFIGURAÇÕES DO BOT
# =============================================

TELEGRAM_TOKEN = "8654852978:AAGijmqYv9WnwJOHNBjFgPiMvjBqNPgE7Dw"
CHAT_ID = "7635744352"
DERIV_APP_ID = "1089"
DERIV_API_TOKEN = ""
STAKE = 1.00
COOLDOWN_SECONDS = 300  # 5 minutos entre sinais por ativo

# Ativos monitorados simultaneamente
SYMBOLS = {
    "stpRNG":     {"name": "Step Index", "has_schedule": False, "tick_size": 0.1},
    "cryBTCUSD":  {"name": "BTCUSD",     "has_schedule": False, "tick_size": 50.0},
}
