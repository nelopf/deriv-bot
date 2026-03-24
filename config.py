# =============================================
# CONFIGURAÇÕES DO BOT
# =============================================

TELEGRAM_TOKEN = "8654852978:AAGijmqYv9WnwJOHNBjFgPiMvjBqNPgE7Dw"
CHAT_ID = "7635744352"
DERIV_APP_ID = "1089"
DERIV_API_TOKEN = ""
STAKE = 1.00
COOLDOWN_SECONDS = 300  # 5 minutos entre sinais

# Ativos monitorados
SYMBOLS = {
    # tick_size = movimento mínimo por alvo
    # V75 move ~7-15 pontos por minuto — TPs espaçados em 10 pontos cada
    "R_75": {"name": "Volatility 75 Index", "tick_size": 10.0, "mode": "generic"},
}
