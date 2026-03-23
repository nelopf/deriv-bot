from collections import deque
from datetime import datetime
import numpy as np

# Configurações gerais
RSI_PERIOD = 14
BB_PERIOD = 20
BB_STD = 2.0
MIN_TICKS = 50
SIGNAL_CONFIDENCE = 75
TICK_DURATION = 5


class SignalAnalyzer:
    def __init__(self, mode: str = "generic"):
        """
        mode: 
          'generic' — RSI + Bollinger (Step Index, etc.)
          'boom'    — Lógica específica para Boom (só BUY)
          'crash'   — Lógica específica para Crash (só SELL)
        """
        self.mode = mode
        self.prices = deque(maxlen=300)
        self.epochs = deque(maxlen=300)

    def add_tick(self, price: float, epoch: int):
        self.prices.append(price)
        self.epochs.append(epoch)

    # ─── Indicadores ───────────────────────────────────────────

    def _rsi(self, period=RSI_PERIOD):
        prices = list(self.prices)
        if len(prices) < period + 1:
            return None
        deltas = np.diff(prices)
        gains  = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _bollinger_bands(self, period=BB_PERIOD, std_dev=BB_STD):
        prices = list(self.prices)
        if len(prices) < period:
            return None, None, None
        window = np.array(prices[-period:])
        mid   = np.mean(window)
        std   = np.std(window)
        upper = mid + std_dev * std
        lower = mid - std_dev * std
        return upper, mid, lower

    def _last_spike_distance(self):
        """Conta quantos ticks passaram desde o último spike (movimento brusco)."""
        prices = list(self.prices)
        if len(prices) < 10:
            return 999
        diffs = np.abs(np.diff(prices))
        mean_diff = np.mean(diffs)
        std_diff  = np.std(diffs)
        spike_threshold = mean_diff + 3 * std_diff

        for i in range(len(diffs) - 1, -1, -1):
            if diffs[i] >= spike_threshold:
                return len(diffs) - i
        return 999  # nenhum spike recente

    def _trend_direction(self, period=20):
        """Retorna 1 se tendência de alta, -1 se baixa, 0 se lateral."""
        prices = list(self.prices)
        if len(prices) < period:
            return 0
        window = prices[-period:]
        slope = (window[-1] - window[0]) / period
        if slope > 0.001:
            return 1
        elif slope < -0.001:
            return -1
        return 0

    def _consecutive_direction(self, count=5):
        """Conta quantos ticks consecutivos foram na mesma direção."""
        prices = list(self.prices)
        if len(prices) < count + 1:
            return 0, 0
        diffs = np.diff(prices[-count-1:])
        ups   = sum(1 for d in diffs if d > 0)
        downs = sum(1 for d in diffs if d < 0)
        return ups, downs

    # ─── Estratégias ───────────────────────────────────────────

    def _analyze_boom(self):
        """
        Boom 500: preço tende a subir até ao spike.
        Estratégia: entrar BUY após queda pós-spike ou RSI oversold.
        """
        prices = list(self.prices)
        if len(prices) < MIN_TICKS:
            return None

        rsi = self._rsi()
        upper, mid, lower = self._bollinger_bands()
        if rsi is None or lower is None:
            return None

        current_price = prices[-1]
        spike_dist    = self._last_spike_distance()
        trend         = self._trend_direction()
        ups, downs    = self._consecutive_direction(5)

        confidence = 0

        # RSI oversold — bom momento para BUY no Boom
        if rsi < 35:
            confidence += 35
        elif rsi < 45:
            confidence += 20

        # Preço perto da banda inferior — reversão esperada
        if current_price <= lower:
            confidence += 30
        elif current_price <= lower + (mid - lower) * 0.3:
            confidence += 15

        # Logo após um spike — preço tende a subir novamente
        if 5 <= spike_dist <= 30:
            confidence += 20

        # Queda consecutiva — exaustão de vendedores
        if downs >= 4:
            confidence += 15

        if confidence >= SIGNAL_CONFIDENCE:
            return {
                "type": "BUY",
                "price": round(current_price, 4),
                "confidence": min(confidence, 99),
                "duration": TICK_DURATION,
                "time": datetime.now().strftime("%H:%M:%S"),
            }
        return None

    def _analyze_crash(self):
        """
        Crash 500: preço tende a descer até ao spike.
        Estratégia: entrar SELL após subida pós-spike ou RSI overbought.
        """
        prices = list(self.prices)
        if len(prices) < MIN_TICKS:
            return None

        rsi = self._rsi()
        upper, mid, lower = self._bollinger_bands()
        if rsi is None or upper is None:
            return None

        current_price = prices[-1]
        spike_dist    = self._last_spike_distance()
        trend         = self._trend_direction()
        ups, downs    = self._consecutive_direction(5)

        confidence = 0

        # RSI overbought — bom momento para SELL no Crash
        if rsi > 65:
            confidence += 35
        elif rsi > 55:
            confidence += 20

        # Preço perto da banda superior — reversão esperada
        if current_price >= upper:
            confidence += 30
        elif current_price >= upper - (upper - mid) * 0.3:
            confidence += 15

        # Logo após um spike — preço tende a descer novamente
        if 5 <= spike_dist <= 30:
            confidence += 20

        # Subida consecutiva — exaustão de compradores
        if ups >= 4:
            confidence += 15

        if confidence >= SIGNAL_CONFIDENCE:
            return {
                "type": "SELL",
                "price": round(current_price, 4),
                "confidence": min(confidence, 99),
                "duration": TICK_DURATION,
                "time": datetime.now().strftime("%H:%M:%S"),
            }
        return None

    def _analyze_generic(self):
        """RSI + Bollinger Bands genérico para Step Index e outros."""
        prices = list(self.prices)
        if len(prices) < MIN_TICKS:
            return None

        rsi = self._rsi()
        upper, mid, lower = self._bollinger_bands()
        if rsi is None or upper is None:
            return None

        current_price = prices[-1]
        signal_type   = None
        confidence    = 0

        # BUY
        if rsi < 30:
            confidence += 40
        elif rsi < 40:
            confidence += 20

        if current_price <= lower:
            confidence += 40
        elif current_price <= lower + (mid - lower) * 0.3:
            confidence += 20

        if confidence >= SIGNAL_CONFIDENCE:
            signal_type = "BUY"

        # SELL
        sell_score = 0
        if rsi > 70:
            sell_score += 40
        elif rsi > 60:
            sell_score += 20

        if current_price >= upper:
            sell_score += 40
        elif current_price >= upper - (upper - mid) * 0.3:
            sell_score += 20

        if sell_score >= SIGNAL_CONFIDENCE and sell_score > confidence:
            signal_type = "SELL"
            confidence  = sell_score

        if signal_type is None:
            return None

        return {
            "type": signal_type,
            "price": round(current_price, 4),
            "confidence": min(confidence, 99),
            "duration": TICK_DURATION,
            "time": datetime.now().strftime("%H:%M:%S"),
        }

    # ─── Entrada principal ──────────────────────────────────────

    def analyze(self):
        if self.mode == "boom":
            return self._analyze_boom()
        elif self.mode == "crash":
            return self._analyze_crash()
        else:
            return self._analyze_generic()
