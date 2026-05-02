"""
tracker.py — Rastreamento e cooldown de sinais
Evita enviar o mesmo sinal repetido dentro do período de cooldown.
Mantém um histórico simples dos últimos sinais emitidos.
"""

import time
from datetime import datetime
from collections import deque

import config

# ─── ESTADO INTERNO ───────────────────────────────────────────────────────────

_last_signal: dict = {
    "direction": None,
    "timestamp": 0.0,
}

# Histórico dos últimos 50 sinais emitidos
_history: deque = deque(maxlen=50)

# ─── VERIFICAÇÃO DE COOLDOWN ──────────────────────────────────────────────────

def is_on_cooldown(direction: str) -> bool:
    """
    Retorna True se um sinal igual já foi enviado
    dentro do período de cooldown configurado.
    """
    if _last_signal["direction"] != direction:
        return False
    elapsed = time.time() - _last_signal["timestamp"]
    return elapsed < config.COOLDOWN_SECONDS

def remaining_cooldown(direction: str) -> int:
    """Retorna quantos segundos faltam para o cooldown expirar."""
    if _last_signal["direction"] != direction:
        return 0
    elapsed = time.time() - _last_signal["timestamp"]
    remaining = config.COOLDOWN_SECONDS - elapsed
    return max(0, int(remaining))

# ─── REGISTRO DE SINAL ────────────────────────────────────────────────────────

def register_signal(signal: dict) -> None:
    """
    Registra o sinal enviado no estado e no histórico.
    Deve ser chamado logo após o envio com sucesso ao Telegram.
    """
    direction = signal["direction"]
    now_ts    = time.time()
    now_str   = datetime.now().strftime("%d/%m/%Y %H:%M")

    _last_signal["direction"] = direction
    _last_signal["timestamp"] = now_ts

    _history.appendleft({
        "datetime":   now_str,
        "direction":  direction,
        "price":      signal["price"],
        "confidence": signal["confidence"],
        "sl":         signal["levels"]["sl"],
        "tp1":        signal["levels"]["tp1"],
        "tp2":        signal["levels"]["tp2"],
        "tp3":        signal["levels"]["tp3"],
    })

# ─── ACESSO AO HISTÓRICO ──────────────────────────────────────────────────────

def get_history() -> list:
    """Retorna lista com os sinais mais recentes (mais novo primeiro)."""
    return list(_history)

def get_last_signal() -> dict:
    """Retorna o último sinal registrado."""
    return dict(_last_signal)

def summary() -> str:
    """Gera um resumo do histórico para log."""
    if not _history:
        return "Nenhum sinal emitido ainda."
    total  = len(_history)
    buys   = sum(1 for s in _history if s["direction"] == "COMPRA")
    sells  = total - buys
    last   = _history[0]
    return (
        f"Total de sinais: {total} | "
        f"Compras: {buys} | Vendas: {sells} | "
        f"Último: {last['direction']} em {last['datetime']}"
    )
