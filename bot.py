"""
bot.py — Envio de sinais ao Telegram + monitoramento em tempo real de TP/SL
"""

import asyncio
import logging
import time
import threading
from datetime import datetime

import ccxt
import schedule
from telegram import Bot
from telegram.constants import ParseMode

import config
import analyzer
import tracker

# ─── LOGGING ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ─── EXCHANGE (preço em tempo real) ───────────────────────────────────────────

_exchange = getattr(ccxt, config.EXCHANGE)({
    "rateLimit": 1200,
    "enableRateLimit": True,
})

def get_current_price() -> float:
    ticker = _exchange.fetch_ticker(config.SYMBOL)
    return float(ticker["last"])

# ─── ENVIO TELEGRAM ───────────────────────────────────────────────────────────

async def _send_async(message: str) -> None:
    bot = Bot(token=config.TELEGRAM_TOKEN)
    await bot.send_message(
        chat_id=config.CHAT_ID,
        text=message,
        parse_mode=ParseMode.MARKDOWN,
    )

def send_msg(text: str) -> None:
    asyncio.run(_send_async(text))

# ─── FORMATO DO SINAL INICIAL ─────────────────────────────────────────────────

def format_signal(sig: dict) -> str:
    """Formato exato conforme solicitado pelo usuário."""
    d    = sig["direction"]
    lv   = sig["levels"]
    tag  = "BUY" if d == "COMPRA" else "SELL"
    flag = "🟢" if d == "COMPRA" else "🔴"

    msg = (
        f"{flag} *SINAL {tag} — BTCUSD*\n"
        f"\n"
        f"📈 Entrada: `{sig['price']:.4f}`\n"
        f"💪 Confiança: `{sig['confidence']}%`\n"
        f"\n"
        f"🎯 *ALVOS*\n"
        f" TP1: `{lv['tp1']:.3f}`\n"
        f" TP2: `{lv['tp2']:.3f}`\n"
        f" TP3: `{lv['tp3']:.3f}`\n"
        f" SL : `{lv['sl']:.3f}`\n"
        f"\n"
        f"⏳ _Monitorando TPs em tempo real..._"
    )
    return msg

# ─── ALERTA DE TP ATINGIDO ────────────────────────────────────────────────────

def format_tp_hit(tp_num: int, tp_price: float, entry: float,
                  sl: float, direction: str, remaining_tps: list) -> str:
    tag = "BUY" if direction == "COMPRA" else "SELL"
    pct = abs(tp_price - entry) / entry * 100

    remaining_str = ""
    for label, price in remaining_tps:
        remaining_str += f" {label}: `{price:.3f}`\n"

    msg = (
        f"✅ *TP{tp_num} ATINGIDO — BTCUSD {tag}*\n"
        f"\n"
        f"🎯 TP{tp_num}: `{tp_price:.3f}`  _(+{pct:.2f}%)_\n"
        f"📈 Entrada foi: `{entry:.4f}`\n"
        f"🛑 SL atual: `{sl:.3f}`\n"
    )

    if remaining_tps:
        msg += f"\n🎯 *Próximos alvos:*\n{remaining_str}"
        msg += f"\n⏳ _Monitorando em tempo real..._"
    else:
        msg += f"\n🏁 *Todos os alvos atingidos!*\n"
        msg += f"💰 *Resultado: LUCRO MÁXIMO ✅*"

    return msg

# ─── ALERTA DE SL ATINGIDO ────────────────────────────────────────────────────

def format_sl_hit(sl_price: float, entry: float,
                  direction: str, tps_hit: list) -> str:
    tag = "BUY" if direction == "COMPRA" else "SELL"
    pct = abs(sl_price - entry) / entry * 100

    hit_str = ""
    if tps_hit:
        hit_str = f"\n✅ TPs atingidos antes do SL: *{', '.join(tps_hit)}*"

    msg = (
        f"🛑 *STOP LOSS ATINGIDO — BTCUSD {tag}*\n"
        f"\n"
        f"❌ SL: `{sl_price:.3f}`  _(-{pct:.2f}%)_\n"
        f"📈 Entrada foi: `{entry:.4f}`\n"
        f"{hit_str}\n"
        f"\n"
        f"⚠️ _Sinal encerrado. Aguardando próxima oportunidade..._"
    )
    return msg

# ─── MONITOR EM TEMPO REAL ────────────────────────────────────────────────────

def monitor_signal(sig: dict) -> None:
    """
    Roda em thread separada.
    Verifica preço a cada 10s e envia alertas ao atingir TP ou SL.
    Após TP1: move SL para breakeven (entrada) automaticamente.
    """
    d         = sig["direction"]
    entry     = sig["price"]
    lv        = sig["levels"]
    sl        = lv["sl"]
    is_buy    = (d == "COMPRA")

    # Lista de TPs pendentes: [(label, price), ...]
    remaining = [
        ("TP1", lv["tp1"]),
        ("TP2", lv["tp2"]),
        ("TP3", lv["tp3"]),
    ]
    hit_tps = []  # TPs já atingidos

    log.info(f"[Monitor] Iniciado | {d} | Entrada={entry:.4f} | SL={sl:.3f}")

    while remaining:
        time.sleep(10)

        try:
            price = get_current_price()
        except Exception as e:
            log.warning(f"[Monitor] Erro ao buscar preço: {e}")
            continue

        # ── Verificar Stop Loss ──
        sl_atingido = (price <= sl) if is_buy else (price >= sl)
        if sl_atingido:
            log.info(f"[Monitor] SL atingido em {price:.4f}")
            try:
                send_msg(format_sl_hit(sl, entry, d, hit_tps))
            except Exception as e:
                log.error(f"[Monitor] Erro ao enviar SL: {e}")
            return

        # ── Verificar próximo TP ──
        label, tp_price = remaining[0]
        tp_num          = int(label[2])
        tp_atingido     = (price >= tp_price) if is_buy else (price <= tp_price)

        if tp_atingido:
            hit_tps.append(label)
            remaining.pop(0)
            log.info(f"[Monitor] {label} atingido em {price:.4f}")

            # Após TP1: mover SL para breakeven (entrada)
            if tp_num == 1:
                sl = entry
                log.info(f"[Monitor] SL movido para breakeven: {sl:.4f}")

            # Após TP2: mover SL para TP1 (proteger lucro)
            if tp_num == 2:
                sl = lv["tp1"]
                log.info(f"[Monitor] SL movido para TP1: {sl:.4f}")

            try:
                send_msg(format_tp_hit(
                    tp_num, tp_price, entry, sl, d, remaining
                ))
            except Exception as e:
                log.error(f"[Monitor] Erro ao enviar TP{tp_num}: {e}")

    log.info("[Monitor] Todos TPs atingidos. Monitor encerrado.")

def start_monitor(sig: dict) -> None:
    """Inicia monitoramento em thread separada (não bloqueia o bot)."""
    t = threading.Thread(target=monitor_signal, args=(sig,), daemon=True)
    t.start()
    log.info("[Monitor] Thread iniciada.")

# ─── JOB PRINCIPAL ────────────────────────────────────────────────────────────

def run_job() -> None:
    log.info("Verificando mercado...")

    sig = analyzer.get_consensus()
    if sig is None:
        log.info("Sem sinal válido.")
        return

    direction = sig["direction"]

    if tracker.is_on_cooldown(direction):
        rem = tracker.remaining_cooldown(direction)
        log.info(f"Cooldown ativo para {direction} — {rem}s restantes.")
        return

    try:
        send_msg(format_signal(sig))
        tracker.register_signal(sig)
        log.info(f"Sinal {direction} enviado! Confiança: {sig['confidence']}%")
        log.info(tracker.summary())

        # Iniciar monitoramento de TP/SL em background
        start_monitor(sig)

    except Exception as e:
        log.error(f"Erro ao enviar sinal: {e}")

# ─── INICIALIZAÇÃO ────────────────────────────────────────────────────────────

def start() -> None:
    log.info("=" * 50)
    log.info("  Bot BTC/USD — Sinais para Telegram")
    log.info("=" * 50)
    log.info(f"Exchange   : {config.EXCHANGE} | Par: {config.SYMBOL}")
    log.info(f"Timeframes : {config.TIMEFRAMES}")
    log.info(f"Confiança  : mín. {config.MIN_CONFIDENCE}% | R:R mín. {config.MIN_RR}")
    log.info(f"SL × {config.SL_ATR_MULT} | TP1 × {config.TP1_ATR_MULT} | TP2 × {config.TP2_ATR_MULT} | TP3 × {config.TP3_ATR_MULT}")
    log.info("=" * 50)

    run_job()

    schedule.every(config.CHECK_INTERVAL).seconds.do(run_job)

    while True:
        schedule.run_pending()
        time.sleep(5)
