"""
bot.py — Sinais Volatility 75 Index + monitoramento TP/SL em tempo real
"""

import asyncio
import logging
import time
import threading
from datetime import datetime

import schedule
from telegram import Bot
from telegram.constants import ParseMode

import config
import analyzer
import tracker

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

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

# ─── FORMATO DO SINAL ─────────────────────────────────────────────────────────

def format_signal(sig: dict) -> str:
    d    = sig["direction"]
    lv   = sig["levels"]
    tag  = "BUY" if d == "COMPRA" else "SELL"
    flag = "🟢" if d == "COMPRA" else "🔴"

    return (
        f"{flag} *SINAL {tag} — {config.SYMBOL_DISPLAY}*\n"
        f"\n"
        f"📈 Entrada: `{sig['price']:.4f}`\n"
        f"💪 Confiança: `{sig['confidence']}%`\n"
        f"\n"
        f"🎯 *ALVOS*\n"
        f" TP1: `{lv['tp1']:.4f}`\n"
        f" TP2: `{lv['tp2']:.4f}`\n"
        f" TP3: `{lv['tp3']:.4f}`\n"
        f" SL : `{lv['sl']:.4f}`\n"
        f"\n"
        f"⏳ _Monitorando TPs em tempo real..._"
    )

# ─── ALERTA TP ────────────────────────────────────────────────────────────────

def format_tp_hit(tp_num, tp_price, entry, sl, direction, remaining_tps):
    tag = "BUY" if direction == "COMPRA" else "SELL"
    pct = abs(tp_price - entry) / entry * 100
    remaining_str = "".join(f" {l}: `{p:.4f}`\n" for l, p in remaining_tps)

    msg = (
        f"✅ *TP{tp_num} ATINGIDO — {config.SYMBOL_DISPLAY} {tag}*\n"
        f"\n"
        f"🎯 TP{tp_num}: `{tp_price:.4f}`  _(+{pct:.3f}%)_\n"
        f"📈 Entrada foi: `{entry:.4f}`\n"
        f"🛑 SL atual: `{sl:.4f}`\n"
    )
    if remaining_tps:
        msg += f"\n🎯 *Próximos alvos:*\n{remaining_str}"
        msg += f"\n⏳ _Monitorando em tempo real..._"
    else:
        msg += f"\n🏁 *Todos os alvos atingidos!*\n💰 *LUCRO MÁXIMO ✅*"
    return msg

# ─── ALERTA SL ────────────────────────────────────────────────────────────────

def format_sl_hit(sl_price, entry, direction, tps_hit):
    tag = "BUY" if direction == "COMPRA" else "SELL"
    pct = abs(sl_price - entry) / entry * 100
    hit_str = f"\n✅ TPs antes do SL: *{', '.join(tps_hit)}*" if tps_hit else ""

    return (
        f"🛑 *STOP LOSS ATINGIDO — {config.SYMBOL_DISPLAY} {tag}*\n"
        f"\n"
        f"❌ SL: `{sl_price:.4f}`  _(-{pct:.3f}%)_\n"
        f"📈 Entrada foi: `{entry:.4f}`\n"
        f"{hit_str}\n"
        f"\n"
        f"⚠️ _Sinal encerrado. Aguardando próxima oportunidade..._"
    )

# ─── MONITOR EM TEMPO REAL ────────────────────────────────────────────────────

def monitor_signal(sig: dict) -> None:
    d      = sig["direction"]
    entry  = sig["price"]
    lv     = sig["levels"]
    sl     = lv["sl"]
    is_buy = (d == "COMPRA")

    remaining = [("TP1", lv["tp1"]), ("TP2", lv["tp2"]), ("TP3", lv["tp3"])]
    hit_tps   = []

    log.info(f"[Monitor] {d} | Entrada={entry:.4f} | SL={sl:.4f}")

    while remaining:
        time.sleep(10)

        try:
            price = analyzer.get_live_price()
        except Exception as e:
            log.warning(f"[Monitor] Erro preço: {e}")
            continue

        # Stop Loss
        if (price <= sl) if is_buy else (price >= sl):
            log.info(f"[Monitor] SL atingido em {price:.4f}")
            try:
                send_msg(format_sl_hit(sl, entry, d, hit_tps))
            except Exception as e:
                log.error(f"[Monitor] Erro SL: {e}")
            return

        # Take Profit
        label, tp_price = remaining[0]
        tp_num = int(label[2])
        if (price >= tp_price) if is_buy else (price <= tp_price):
            hit_tps.append(label)
            remaining.pop(0)
            log.info(f"[Monitor] {label} atingido em {price:.4f}")

            if tp_num == 1:
                sl = entry
            if tp_num == 2:
                sl = lv["tp1"]

            try:
                send_msg(format_tp_hit(tp_num, tp_price, entry, sl, d, remaining))
            except Exception as e:
                log.error(f"[Monitor] Erro TP{tp_num}: {e}")

    log.info("[Monitor] Concluído.")

def start_monitor(sig: dict) -> None:
    t = threading.Thread(target=monitor_signal, args=(sig,), daemon=True)
    t.start()

# ─── JOB PRINCIPAL ────────────────────────────────────────────────────────────

def run_job() -> None:
    log.info("Verificando mercado...")
    sig = analyzer.get_consensus()

    if sig is None:
        log.info("Sem sinal válido.")
        return

    direction = sig["direction"]

    if tracker.is_on_cooldown(direction):
        log.info(f"Cooldown — {tracker.remaining_cooldown(direction)}s restantes.")
        return

    try:
        send_msg(format_signal(sig))
        tracker.register_signal(sig)
        log.info(f"Sinal {direction} enviado! Confiança: {sig['confidence']}%")
        start_monitor(sig)
    except Exception as e:
        log.error(f"Erro: {e}")

# ─── INICIALIZAÇÃO ────────────────────────────────────────────────────────────

def start() -> None:
    log.info(f"Bot {config.SYMBOL_DISPLAY} iniciado")

    try:
        now = datetime.now().strftime("%d/%m/%Y %H:%M")
        send_msg(
            f"🤖 *Bot {config.SYMBOL_DISPLAY} iniciado!*\n"
            f"\n"
            f"✅ Conectado e a monitorar o mercado\n"
            f"🕐 Hora de início: `{now}`\n"
            f"📊 Timeframes: `M5 | M15 | M60`\n"
            f"💪 Confiança mínima: `{config.MIN_CONFIDENCE}%`\n"
            f"\n"
            f"⏳ _Aguardando sinal de alta qualidade..._"
        )
    except Exception as e:
        log.error(f"Erro msg início: {e}")

    run_job()

    schedule.every(config.CHECK_INTERVAL).seconds.do(run_job)

    while True:
        schedule.run_pending()
        time.sleep(5)
