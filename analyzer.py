from collections import deque
from datetime import datetime
import numpy as np

# Configurações da estratégia
RSI_PERIOD = 14
BB_PERIOD = 20
BB_STD = 2.0
MIN_TICKS = 50          # mínimo de ticks para começar a analisar
SIGNAL_CONFIDENCE = 75  # % mínimo de confiança para emitir sinal
TICK_DURATION = 5       # duração sugerida da operação em ticks


class SignalAnalyzer:
    def __init__(self):
        self.prices = deque(maxlen=200)
        self.epochs = deque(maxlen=200)

    def add_tick(self, price: float, epoch: int):
        self.prices.append(price)
        self.epochs.append(epoch)

    def _rsi(self, prices, period=RSI_PERIOD):
        if len(prices) < period + 1:
            return None
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _bollinger_bands(self, prices, period=BB_PERIOD, std_dev=BB_STD):
        if len(prices) < period:
            return None, None, None
        window = np.array(prices[-period:])
        mid = np.mean(window)
        std = np.std(window)
        upper = mid + std_dev * std
        lower = mid - std_dev * std
        return upper, mid, lower

    def analyze(self):
        prices = list(self.prices)

        if len(prices) < MIN_TICKS:
            return None

        rsi = self._rsi(prices)
        upper, mid, lower = self._bollinger_bands(prices)

        if rsi is None or upper is None:
            return None

        current_price = prices[-1]
        signal_type = None
        confidence_score = 0

        # --- Lógica de BUY ---
        if rsi < 30:
            confidence_score += 40
        elif rsi < 40:
            confidence_score += 20

        if current_price <= lower:
            confidence_score += 40
        elif current_price <= (lower + (mid - lower) * 0.3):
            confidence_score += 20

        if confidence_score >= SIGNAL_CONFIDENCE:
            signal_type = "BUY"

        # --- Lógica de SELL ---
        sell_score = 0

        if rsi > 70:
            sell_score += 40
        elif rsi > 60:
            sell_score += 20

        if current_price >= upper:
            sell_score += 40
        elif current_price >= (upper - (upper - mid) * 0.3):
            sell_score += 20

        if sell_score >= SIGNAL_CONFIDENCE and sell_score > confidence_score:
            signal_type = "SELL"
            confidence_score = sell_score

        if signal_type is None:
            return None

        return {
            "type": signal_type,
            "price": round(current_price, 4),
            "rsi": round(rsi, 2),
            "upper_band": round(upper, 4),
            "lower_band": round(lower, 4),
            "confidence": min(confidence_score, 99),
            "duration": TICK_DURATION,
            "time": datetime.now().strftime("%H:%M:%S"),
        }
