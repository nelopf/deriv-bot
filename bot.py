import asyncio
import json
import websockets
from datetime import datetime
from telegram import Bot
from telegram.constants import ParseMode
from analyzer import SignalAnalyzer
from tracker import TradeTracker
from config import TELEGRAM_TOKEN, CHAT_ID, DERIV_APP_ID, DERIV_API_TOKEN, STAKE

bot = Bot(token=TELEGRAM_TOKEN)
analyzer = SignalAnalyzer()
tracker = TradeTracker()

DERIV_WS_URL = f"wss://ws.binaryws.com/websockets/v3?app_id={DERIV_APP_ID}"


async def send_signal(signal: dict):
    emoji = "🟢" if signal["type"] == "BUY" else "🔴"
    msg = (
        f"{emoji} *SINAL {signal['type']}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 *Ativo:* Volatility 25 (1s)\n"
        f"📈 *Entrada:* `{signal['price']}`\n"
        f"⏱ *Duração:* {signal['duration']} ticks\n"
        f"💪 *Confiança:* {signal['confidence']}%\n"
        f"🕐 *Hora:* {signal['time']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"_Aguardando resultado..._"
    )
    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)


async def send_result(result: dict):
    if result["profit"] > 0:
        emoji = "✅"
        status = "WIN"
        valor = f"+${result['profit']:.2f}"
    else:
        emoji = "❌"
        status = "LOSS"
        valor = f"-${abs(result['profit']):.2f}"

    stats = tracker.get_stats()
    winrate = stats["winrate"]
    filled = round(winrate / 10)
    bar = "🟩" * filled + "⬜" * (10 - filled)

    msg = (
        f"{emoji} *SAÍDA: {status}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💰 *Resultado:* `{valor}`\n"
        f"📈 *Entrada:* `{result['entry']}`\n"
        f"📉 *Saída:* `{result['exit']}`\n"
        f"🕐 *Hora de saída:* {result['time']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 *RELATÓRIO DO DIA*\n"
        f"🔢 Total de operações: *{stats['total']}*\n"
        f"✅ Wins: *{stats['wins']}*  |  ❌ Losses: *{stats['losses']}*\n"
        f"🎯 Assertividade: *{winrate}%*\n"
        f"{bar}\n"
        f"💵 Saldo do dia: `{stats['balance']:+.2f} USD`\n"
        f"📦 Maior sequência de wins: *{stats['max_streak']}*\n"
        f"━━━━━━━━━━━━━━━"
    )
    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)


async def send_daily_summary():
    stats = tracker.get_stats()
    winrate = stats["winrate"]
    filled = round(winrate / 10)
    bar = "🟩" * filled + "⬜" * (10 - filled)
    perf_emoji = "🏆" if winrate >= 75 else ("⚠️" if winrate >= 50 else "🔻")

    msg = (
        f"📋 *RESUMO DIÁRIO*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{perf_emoji} *Performance:* {winrate}%\n"
        f"{bar}\n"
        f"🔢 Total: *{stats['total']}* operações\n"
        f"✅ Wins: *{stats['wins']}*  |  ❌ Losses: *{stats['losses']}*\n"
        f"💵 Resultado líquido: `{stats['balance']:+.2f} USD`\n"
        f"📦 Maior sequência: *{stats['max_streak']}* wins consecutivos\n"
        f"━━━━━━━━━━━━━━━\n"
        f"_Contadores resetados para amanhã._"
    )
    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)
    tracker.reset()


async def place_contract(ws, signal: dict):
    contract_type = "CALL" if signal["type"] == "BUY" else "PUT"
    buy_msg = {
        "buy": 1,
        "subscribe": 1,
        "price": STAKE,
        "parameters": {
            "amount": STAKE,
            "basis": "stake",
            "contract_type": contract_type,
            "currency": "USD",
            "duration": signal["duration"],
            "duration_unit": "t",
            "symbol": "1HZ25V",
        }
    }
    await ws.send(json.dumps(buy_msg))


async def subscribe_ticks():
    print("[BOT] Conectando à Deriv WebSocket...")

    async with websockets.connect(DERIV_WS_URL) as ws:

        if DERIV_API_TOKEN:
            await ws.send(json.dumps({"authorize": DERIV_API_TOKEN}))
            auth_resp = json.loads(await ws.recv())
            if "error" in auth_resp:
                print(f"[ERRO AUTH] {auth_resp['error']['message']}")
                return
            print("[BOT] Autorizado na Deriv.")

        await ws.send(json.dumps({"ticks": "1HZ25V", "subscribe": 1}))
        print("[BOT] Inscrito em Volatility 25 (1s). Aguardando sinais...")

        last_signal_type = None
        last_signal = None
        contract_open = False

        while True:
            try:
                response = await ws.recv()
                data = json.loads(response)

                if "tick" in data:
                    tick = data["tick"]
                    price = float(tick["quote"])
                    epoch = tick["epoch"]
                    analyzer.add_tick(price, epoch)

                    if not contract_open:
                        signal = analyzer.analyze()
                        if signal and signal["type"] != last_signal_type:
                            last_signal_type = signal["type"]
                            last_signal = signal
                            await send_signal(signal)
                            if DERIV_API_TOKEN:
                                await place_contract(ws, signal)
                                contract_open = True

                elif "buy" in data:
                    print(f"[CONTRATO ABERTO] ID: {data['buy'].get('contract_id')}")

                elif "proposal_open_contract" in data:
                    poc = data["proposal_open_contract"]
                    is_done = poc.get("is_expired") or poc.get("is_settleable") or poc.get("status") == "sold"

                    if is_done:
                        entry = float(poc.get("entry_tick", last_signal["price"] if last_signal else 0))
                        exit_ = float(poc.get("exit_tick", 0))
                        profit = float(poc.get("profit", 0))

                        result = {
                            "entry": round(entry, 4),
                            "exit": round(exit_, 4),
                            "profit": profit,
                            "time": datetime.now().strftime("%H:%M:%S"),
                        }
                        tracker.record(profit)
                        await send_result(result)
                        contract_open = False
                        last_signal_type = None

                elif "error" in data:
                    print(f"[ERRO DERIV] {data['error']['message']}")
                    contract_open = False

            except Exception as e:
                print(f"[ERRO] {e}")
                await asyncio.sleep(3)
                break


async def daily_summary_loop():
    while True:
        now = datetime.now()
        seconds_until_midnight = (
            (24 - now.hour - 1) * 3600 +
            (59 - now.minute) * 60 +
            (60 - now.second)
        )
        await asyncio.sleep(seconds_until_midnight)
        await send_daily_summary()


async def subscribe_ticks_loop():
    while True:
        try:
            await subscribe_ticks()
        except Exception as e:
            print(f"[RECONECTANDO] {e}")
            await asyncio.sleep(5)


async def main():
    print("[BOT] Iniciando bot de sinais Deriv V25(1s)...")
    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            f"🤖 *Bot iniciado!*\n"
            f"📊 Monitorando: Volatility 25 (1s)\n"
            f"💰 Stake por operação: ${STAKE}\n"
            f"🎯 Mín. confiança para sinal: 75%\n"
            f"_Aguardando primeiro sinal..._"
        ),
        parse_mode=ParseMode.MARKDOWN
    )
    await asyncio.gather(
        subscribe_ticks_loop(),
        daily_summary_loop()
    )


if __name__ == "__main__":
    asyncio.run(main())
