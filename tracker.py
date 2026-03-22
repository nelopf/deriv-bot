class TradeTracker:
    def __init__(self):
        self.reset()

    def reset(self):
        self.total = 0
        self.wins = 0
        self.losses = 0
        self.balance = 0.0
        self.current_streak = 0
        self.max_streak = 0

    def record(self, profit: float):
        self.total += 1
        self.balance += profit
        if profit > 0:
            self.wins += 1
            self.current_streak += 1
            if self.current_streak > self.max_streak:
                self.max_streak = self.current_streak
        else:
            self.losses += 1
            self.current_streak = 0

    def get_stats(self) -> dict:
        winrate = round((self.wins / self.total) * 100, 1) if self.total > 0 else 0
        return {
            "total": self.total,
            "wins": self.wins,
            "losses": self.losses,
            "winrate": winrate,
            "balance": self.balance,
            "max_streak": self.max_streak,
        }
