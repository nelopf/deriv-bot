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
        tp1 = round(price + tick_size * 5,  3)
        tp2 = round(price + tick_size * 10, 3)
        tp3 = round(price + tick_size * 20, 3)
    else:
        tp1 = round(price - tick_size * 5,  3)
        tp2 = round(price - tick_size * 10, 3)
        tp3 = round(price - tick_size * 20, 3)
    return tp1, tp2, tp3


async def send_signal(signal: dict, symbol_name: str, tp1: float, tp2: float, tp3: float):
    emoji   = "🟢" if signal["type"] == "BUY" else "🔴"
    arrow   = "📈" if signal["type"] == "BUY" else "📉"
    special = "📊"

    msg = (
        f"{emoji} *SINAL {signal['type']} — {special} {symbol_name}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 *Ativo:* {symbol_name}\n"
        f"{arrow} *Entrada:* `{signal['price']}`\n"
        f"⏱ *Duração:* 5 ticks\n"
        f"💪 *Confiança:* {signal['confidence']}%\n"
        f"🕐 *Hora de entrada:* {signal['time']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🎯 *ALVOS*\n"
        f"🥇 TP1: `{tp1}`\n"
        f"🥈 TP2: `{tp2}`\n"
        f"🥉 TP3: `{tp3}`\n"
        f"━━━━━━━━━━━━━━━\n"
        f"_Monitorando TPs em tempo real..._"
    )
    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)
    print(f"[SINAL] {symbol_name} | {signal['type']} @ {signal['price']} | TP1:{tp1} TP2:{tp2} TP3:{tp3}")


async def send_tp_hit(tp_num: int, entry: float, tp_price: float, signal_type: str, symbol_name: str):
    arrow  = "📈" if signal_type == "BUY" else "📉"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    medal  = medals[tp_num]

    msg = (
        f"{medal} *TP{tp_num} ATINGIDO — {symbol_name}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{arrow} *Entrada:* `{entry}`\n"
        f"✅ *TP{tp_num}:* `{tp_price}`\n"
        f"🕐 *Hora:* {datetime.now().strftime('%H:%M:%S')}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"_Aguardando próximo alvo..._"
    )
    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)


async def send_exit(entry: float, exit_price: float, signal_type: str, symbol_name: str, tracker: TradeTracker):
    stats   = tracker.get_stats()
    winrate = stats["winrate"]
    filled  = round(winrate / 10)
    bar     = "🟩" * filled + "⬜" * (10 - filled)
    arrow   = "📈" if signal_type == "BUY" else "📉"

    msg = (
        f"🏆 *SAÍDA FINAL — TP3 ATINGIDO*\n"
        f"📊 *Ativo:* {symbol_name}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{arrow} *Entrada:* `{entry}`\n"
        f"🏁 *Saída:* `{exit_price}`\n"
        f"✅ Lucro máximo alcançado!\n"
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
        stats   = tracker.get_stats()
        winrate = stats["winrate"]
        filled  = round(winrate / 10)
        bar     = "🟩" * filled + "⬜" * (10 - filled)
        perf    = "🏆" if winrate >= 75 else ("⚠️" if winrate >= 50 else "🔻")
        msg += (
            f"\n{perf} *{info['name']}*\n"
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
                print(f"[BOT] Inscrito em {symbol_name} (modo: {mode})")

                last_signal_price = None   # evita sinal duplicado
                last_signal_time  = 0
                active_signal     = None
                tp1 = tp2 = tp3   = None
                tp1_hit = tp2_hit = False
                tp1_hit_global    = True   # começa True para permitir 1o sinal

                while True:
                    response = await ws.recv()
                    data     = json.loads(response)

                    if "tick" in data:
                        tick  = data["tick"]
                        price = float(tick["quote"])
                        epoch = tick["epoch"]
                        analyzer.add_tick(price, epoch)
                        now = time.time()

                        # --- Monitorar TPs em tempo real ---
                        if active_signal is not None:
                            sig_type = active_signal["type"]
                            entry    = active_signal["price"]

                            # TP1
                            if not tp1_hit:
                                if (sig_type == "BUY" and price >= tp1) or \
                                   (sig_type == "SELL" and price <= tp1):
                                    tp1_hit      = True
                                    tp1_hit_global = True  # libera próximo sinal após TP1
                                    await send_tp_hit(1, entry, tp1, sig_type, symbol_name)

                            # TP2
                            if tp1_hit and not tp2_hit:
                                if (sig_type == "BUY" and price >= tp2) or \
                                   (sig_type == "SELL" and price <= tp2):
                                    tp2_hit = True
                                    await send_tp_hit(2, entry, tp2, sig_type, symbol_name)

                            # TP3 — saída final
                            if tp2_hit:
                                if (sig_type == "BUY" and price >= tp3) or \
                                   (sig_type == "SELL" and price <= tp3):
                                    tracker.record(abs(round(tp3 - entry, 4)))
                                    await send_exit(entry, price, sig_type, symbol_name, tracker)
                                    active_signal     = None
                                    tp1 = tp2 = tp3   = None
                                    tp1_hit = tp2_hit = False
                                    tp1_hit_global    = True  # libera após saída completa
                                    last_signal_price = None

                        # --- Procurar novo sinal ---
                        # Só procura novo sinal se:
                        # 1. Não há sinal activo
                        # 2. TP1 já foi atingido (saída confirmada)
                        # 3. Cooldown passou
                        cooldown_ok  = (now - last_signal_time) >= COOLDOWN_SECONDS
                        pode_entrar  = active_signal is None and tp1_hit_global and cooldown_ok

                        if pode_entrar:
                            signal = analyzer.analyze()
                            if signal:
                                if last_signal_price and abs(signal["price"] - last_signal_price) < tick_size:
                                    continue
                                last_signal_price = signal["price"]
                                last_signal_time  = now
                                active_signal     = signal
                                tp1, tp2, tp3     = calculate_targets(signal["price"], signal["type"], tick_size)
                                tp1_hit = tp2_hit = False
                                tp1_hit_global    = False  # bloqueia novo sinal até TP1
                                await send_signal(signal, symbol_name, tp1, tp2, tp3)

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
    print("[BOT] Iniciando — Crash 500 + Boom 500...")
    trackers = {symbol: TradeTracker() for symbol in SYMBOLS}

    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            f"🤖 *Bot iniciado!*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 Monitorando *2 ativos:*\n"
            f"💣 Crash 500 Index — só SELL\n"
            f"💥 Boom 500 Index — só BUY\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💰 Stake: ${STAKE}\n"
            f"🎯 Confiança mínima: 75%\n"
            f"⏱ Cooldown: 5 minutos\n"
            f"📡 Notificação: TP1, TP2 e TP3\n"
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
