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
# mode: 'boom', 'crash' ou 'generic'
SYMBOLS = {
    "CRASH500": {"name": "Crash 500 Index", "tick_size": 0.01, "mode": "crash"},
    "BOOM500":  {"name": "Boom 500 Index",  "tick_size": 0.01, "mode": "boom"},
}
