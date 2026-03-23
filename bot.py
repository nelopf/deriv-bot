import asyncio
import json
import time
import websockets
from datetime import datetime
from telegram import Bot
from telegram.constants import ParseMode
from analyzer import SignalAnalyzer
from tracker import TradeTracker
from config import TELEGRAM_TOKEN, CHAT_ID, DERIV_APP_ID, STAKE, SYMBOLS, COOLDOWN_SECONDS

bot = Bot(token=TELEGRAM_TOKEN)
DERIV_WS_URL = f"wss://ws.binaryws.com/websockets/v3?app_id={DERIV_APP_ID}"


def calculate_targets(price: float, signal_type: str, tick_size: float):
    if signal_type == "BUY":
        tp1 = round(price + tick_size * 5,  4)
        tp2 = round(price + tick_size * 10, 4)
        tp3 = round(price + tick_size * 20, 4)
        sl  = round(price - tick_size * 10, 4)
    else:
        tp1 = round(price - tick_size * 5,  4)
        tp2 = round(price - tick_size * 10, 4)
        tp3 = round(price - tick_size * 20, 4)
        sl  = round(price + tick_size * 10, 4)
    return tp1, tp2, tp3, sl


async def send_signal(signal: dict, symbol_name: str, tick_size: float):
    emoji = "🟢" if signal["type"] == "BUY" else "🔴"
    arrow = "📈" if signal["type"] == "BUY" else "📉"
    special = "💥" if "Boom" in symbol_name else "💣"
    tp1, tp2, tp3, sl = calculate_targets(signal["price"], signal["type"], tick_size)

    msg = (
        f"{emoji} *SINAL {signal['type']} — {special} {symbol_name}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 *Ativo:* {symbol_name}\n"
        f"{arrow} *Entrada:* `{signal['price']}`\n"
        f"⏱ *Duração sugerida:* 5 ticks\n"
        f"💪 *Confiança:* {signal['confidence']}%\n"
        f"🕐 *Hora:* {signal['time']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🎯 *ALVOS*\n"
        f"🥇 TP1: `{tp1}` — _5 ticks_\n"
        f"🥈 TP2: `{tp2}` — _10 ticks_\n"
        f"🥉 TP3: `{tp3}` — _20 ticks_\n"
        f"🛑 *Stop Loss:* `{sl}`\n"
        f"━━━━━━━━━━━━━━━\n"
        f"_Monitorando saída em tempo real..._"
    )
    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)
    print(f"[SINAL] {symbol_name} | {signal['type']} @ {signal['price']}")


async def send_exit(exit_type: str, entry: float, exit_price: float, signal_type: str, symbol_name: str, tracker: TradeTracker):
    stats = tracker.get_stats()
    winrate = stats["winrate"]
    filled = round(winrate / 10)
    bar = "🟩" * filled + "⬜" * (10 - filled)

    if exit_type == "TP3":
        emoji = "🏆"
        status = "WIN — TP3 ATINGIDO"
        resultado = "✅ Lucro máximo alcançado!"
    else:
        emoji = "🛑"
        status = "LOSS — STOP LOSS ATINGIDO"
        resultado = "❌ Stop loss activado"

    arrow = "📈" if signal_type == "BUY" else "📉"

    msg = (
        f"{emoji} *SAÍDA: {status}*\n"
        f"📊 *Ativo:* {symbol_name}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{arrow} *Entrada:* `{entry}`\n"
        f"📉 *Saída:* `{exit_price}`\n"
        f"{resultado}\n"
        f"🕐 *Hora:* {datetime.now().strftime('%H:%M:%S')}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 *RELATÓRIO — {symbol_name}*\n"
        f"🔢 Total: *{stats['total']}*  "
        f"✅ *{stats['wins']}* wins  ❌ *{stats['losses']}* losses\n"
        f"🎯 Assertividade: *{winrate}%*\n"
        f"{bar}\n"
        f"💵 Saldo do dia: `{stats['balance']:+.2f} USD`\n"
        f"📦 Maior sequência: *{stats['max_streak']}* wins\n"
        f"━━━━━━━━━━━━━━━"
    )
    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)


async def send_daily_summary(trackers: dict):
    msg = "📋 *RESUMO DIÁRIO*\n━━━━━━━━━━━━━━━\n"
    for symbol, info in SYMBOLS.items():
        tracker = trackers[symbol]
        stats = tracker.get_stats()
        winrate = stats["winrate"]
        filled = round(winrate / 10)
        bar = "🟩" * filled + "⬜" * (10 - filled)
        perf_emoji = "🏆" if winrate >= 75 else ("⚠️" if winrate >= 50 else "🔻")
        msg += (
            f"\n{perf_emoji} *{info['name']}*\n"
            f"🔢 Total: *{stats['total']}* | ✅ *{stats['wins']}* | ❌ *{stats['losses']}*\n"
            f"🎯 *{winrate}%* {bar}\n"
            f"💵 Saldo: `{stats['balance']:+.2f} USD`\n"
            f"━━━━━━━━━━━━━━━\n"
        )
        tracker.reset()
    msg += "_Contadores resetados para amanhã._"
    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)


async def monitor_symbol(symbol: str, symbol_info: dict, tracker: TradeTracker):
    symbol_name = symbol_info["name"]
    tick_size   = symbol_info["tick_size"]
    mode        = symbol_info["mode"]
    analyzer    = SignalAnalyzer(mode=mode)

    while True:
        try:
            async with websockets.connect(DERIV_WS_URL) as ws:
                await ws.send(json.dumps({"ticks": symbol, "subscribe": 1}))
                print(f"[BOT] Inscrito em {symbol_name} (modo: {mode}). Aguardando sinais...")

                last_signal_type = None
                last_signal_time = 0
                active_signal    = None
                tp1 = tp2 = tp3 = sl = None

                while True:
                    response = await ws.recv()
                    data = json.loads(response)

                    if "tick" in data:
                        tick  = data["tick"]
                        price = float(tick["quote"])
                        epoch = tick["epoch"]
                        analyzer.add_tick(price, epoch)
                        now = time.time()

                        # Monitorar saída em tempo real
                        if active_signal is not None:
                            sig_type = active_signal["type"]
                            entry    = active_signal["price"]
                            hit_tp3  = (sig_type == "BUY"  and price >= tp3) or \
                                       (sig_type == "SELL" and price <= tp3)
                            hit_sl   = (sig_type == "BUY"  and price <= sl)  or \
                                       (sig_type == "SELL" and price >= sl)

                            if hit_tp3:
                                tracker.record(abs(round(tp3 - entry, 4)))
                                await send_exit("TP3", entry, price, sig_type, symbol_name, tracker)
                                active_signal = None
                                tp1 = tp2 = tp3 = sl = None
                                last_signal_type = None

                            elif hit_sl:
                                tracker.record(-abs(round(sl - entry, 4)))
                                await send_exit("SL", entry, price, sig_type, symbol_name, tracker)
                                active_signal = None
                                tp1 = tp2 = tp3 = sl = None
                                last_signal_type = None

                        # Procurar novo sinal
                        cooldown_ok = (now - last_signal_time) >= COOLDOWN_SECONDS
                        if active_signal is None and cooldown_ok:
                            signal = analyzer.analyze()
                            if signal and signal["type"] != last_signal_type:
                                last_signal_type = signal["type"]
                                last_signal_time = now
                                active_signal    = signal
                                tp1, tp2, tp3, sl = calculate_targets(signal["price"], signal["type"], tick_size)
                                await send_signal(signal, symbol_name, tick_size)

                    elif "error" in data:
                        print(f"[ERRO {symbol_name}] {data['error']['message']}")

        except Exception as e:
            print(f"[RECONECTANDO {symbol_name}] {e}")
            await asyncio.sleep(5)


async def daily_summary_loop(trackers: dict):
    while True:
        now = datetime.now()
        seconds_until_midnight = (
            (24 - now.hour - 1) * 3600 +
            (59 - now.minute) * 60 +
            (60 - now.second)
        )
        await asyncio.sleep(seconds_until_midnight)
        await send_daily_summary(trackers)


async def main():
    print("[BOT] Iniciando bot — Crash 500 + Boom 500...")
    trackers = {symbol: TradeTracker() for symbol in SYMBOLS}

    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            f"🤖 *Bot iniciado!*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 Monitorando *2 ativos em simultâneo:*\n"
            f"💣 Crash 500 Index — só SELL\n"
            f"💥 Boom 500 Index — só BUY\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 Stake por operação: ${STAKE}\n"
            f"🎯 Mín. confiança: 75%\n"
            f"⏱ Cooldown entre sinais: 5 minutos\n"
            f"📡 Saída em tempo real: TP3 ou SL\n"
            f"━━━━━━━━━━━━━━━\n"
            f"_Aguardando primeiro sinal..._"
        ),
        parse_mode=ParseMode.MARKDOWN
    )

    await asyncio.gather(
        *[monitor_symbol(sym, info, trackers[sym]) for sym, info in SYMBOLS.items()],
        daily_summary_loop(trackers)
    )


if __name__ == "__main__":
    asyncio.run(main())
