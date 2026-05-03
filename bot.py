"""
bot.py — Envio de sinais ao Telegram + monitoramento em tempo real de TP/SL
         Preço em tempo real via API da Deriv
"""

import asyncio
import logging
import time
import threading

import requests
import schedule
from telegram import Bot
from telegram.constants import ParseMode
from datetime import datetime

import config
import analyzer
import tracker

# ─── LOGGING ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ─── PREÇO EM TEMPO REAL DA DERIV ─────────────────────────────────────────────

def get_live_price() -> float:
    """Busca preço atual do BTCUSD na Deriv. Fallback para Binance."""
    try:
        resp = requests.get(
            "https://api.deriv.com/api/v2/ticks/frxBTCUSD",
            timeout=5,
        )
        return float(resp.json()["tick"]["quote"])
    except Exception:
        import ccxt
        ex = getattr(ccxt, config.EXCHANGE)({"enableRateLimit": True})
        return float(ex.fetch_ticker(config.SYMBOL)["last"])

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
    d    = sig["direction"]
    lv   = sig["levels"]
    tag  = "BUY" if d == "COMPRA" else "SELL"
    flag = "🟢" if d == "COMPRA" else "🔴"

    msg = (
        f"{flag} *SINAL {tag} — {config.SYMBOL_DISPLAY}*\n"
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

# ─── ALERTA TP ATINGIDO ───────────────────────────────────────────────────────

def format_tp_hit(tp_num: int, tp_price: float, entry: float,
                  sl: float, direction: str, remaining_tps: list) -> str:
    tag = "BUY" if direction == "COMPRA" else "SELL"
    pct = abs(tp_price - entry) / entry * 100

    remaining_str = ""
    for label, price in remaining_tps:
        remaining_str += f" {label}: `{price:.3f}`\n"

    msg = (
        f"✅ *TP{tp_num} ATINGIDO — {config.SYMBOL_DISPLAY} {tag}*\n"
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

# ─── ALERTA SL ATINGIDO ───────────────────────────────────────────────────────

def format_sl_hit(sl_price: float, entry: float,
                  direction: str, tps_hit: list) -> str:
    tag = "BUY" if direction == "COMPRA" else "SELL"
    pct = abs(sl_price - entry) / entry * 100

    hit_str = ""
    if tps_hit:
        hit_str = f"\n✅ TPs atingidos antes do SL: *{', '.join(tps_hit)}*"

    msg = (
        f"🛑 *STOP LOSS ATINGIDO — {config.SYMBOL_DISPLAY} {tag}*\n"
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
    Verifica preço a cada 10s via API da Deriv.
    Envia alerta ao atingir TP ou SL.
    Após TP1: SL vai para breakeven.
    Após TP2: SL vai para TP1.
    """
    d         = sig["direction"]
    entry     = sig["price"]
    lv        = sig["levels"]
    sl        = lv["sl"]
    is_buy    = (d == "COMPRA")

    remaining = [
        ("TP1", lv["tp1"]),
        ("TP2", lv["tp2"]),
        ("TP3", lv["tp3"]),
    ]
    hit_tps = []

    log.info(f"[Monitor] Iniciado | {d} | Entrada={entry:.4f} | SL={sl:.3f}")

    while remaining:
        time.sleep(10)

        try:
            price = get_live_price()
        except Exception as e:
            log.warning(f"[Monitor] Erro ao buscar preço: {e}")
            continue

        # Verificar Stop Loss
        sl_hit = (price <= sl) if is_buy else (price >= sl)
        if sl_hit:
            log.info(f"[Monitor] SL atingido em {price:.4f}")
            try:
                send_msg(format_sl_hit(sl, entry, d, hit_tps))
            except Exception as e:
                log.error(f"[Monitor] Erro ao enviar SL: {e}")
            return

        # Verificar próximo TP
        label, tp_price = remaining[0]
        tp_num          = int(label[2])
        tp_hit          = (price >= tp_price) if is_buy else (price <= tp_price)

        if tp_hit:
            hit_tps.append(label)
            remaining.pop(0)
            log.info(f"[Monitor] {label} atingido em {price:.4f}")

            if tp_num == 1:
                sl = entry  # Breakeven
                log.info(f"[Monitor] SL → breakeven {sl:.4f}")
            if tp_num == 2:
                sl = lv["tp1"]  # Proteger lucro
                log.info(f"[Monitor] SL → TP1 {sl:.4f}")

            try:
                send_msg(format_tp_hit(tp_num, tp_price, entry, sl, d, remaining))
            except Exception as e:
                log.error(f"[Monitor] Erro ao enviar TP{tp_num}: {e}")

    log.info("[Monitor] Todos TPs atingidos. Encerrado.")

def start_monitor(sig: dict) -> None:
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
        start_monitor(sig)
    except Exception as e:
        log.error(f"Erro ao enviar sinal: {e}")

# ─── INICIALIZAÇÃO ────────────────────────────────────────────────────────────

def start() -> None:
    log.info("=" * 50)
    log.info(f"  Bot {config.SYMBOL_DISPLAY} — Sinais para Deriv")
    log.info("=" * 50)
    log.info(f"Exchange   : {config.EXCHANGE} | Par: {config.SYMBOL}")
    log.info(f"Timeframes : {config.TIMEFRAMES}")
    log.info(f"Confiança  : mín. {config.MIN_CONFIDENCE}% | R:R mín. {config.MIN_RR}")
    log.info("=" * 50)

    run_job()

    schedule.every(config.CHECK_INTERVAL).seconds.do(run_job)

    while True:
        schedule.run_pending()
        time.sleep(5)
