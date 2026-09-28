"""
简化 A股选股策略 (等权买入 top_k, 避开 equity_demo 兼容问题)

每周调仓: 按 ML 信号选 top_k 股票, 等权买入, 持有 N 天。
逻辑简单可靠, 适配 A 股高价股(茅台等)。
"""
import polars as pl

from vnpy.trader.object import BarData, TradeData
from vnpy.trader.constant import Direction
from vnpy.trader.utility import round_to

from vnpy.alpha import AlphaStrategy


class SimpleStockStrategy(AlphaStrategy):
    """简化等权选股策略"""

    top_k: int = 10                # 持仓股票数
    hold_days: int = 5              # 持仓天数(周调仓)
    cash_ratio: float = 0.95        # 资金使用率
    min_volume: int = 100           # A股最小100股
    open_rate: float = 0.00025
    close_rate: float = 0.00125
    min_commission: float = 5
    price_add: float = 0.01

    def on_init(self) -> None:
        from collections import defaultdict
        self.holding_days: dict = defaultdict(int)
        self.day_count: int = 0
        self.write_log("简化选股策略初始化")

    def on_trade(self, trade: TradeData) -> None:
        if trade.direction == Direction.SHORT:
            self.holding_days.pop(trade.vt_symbol, None)

    def on_bars(self, bars: dict[str, BarData]) -> None:
        self.day_count += 1
        # 每 hold_days 天调仓一次
        if self.day_count % self.hold_days != 0:
            return

        last_signal = self.get_signal()
        if last_signal.is_empty():
            return

        # 选信号 top_k
        top_signals = last_signal.sort("signal", descending=True).head(self.top_k)
        target_symbols = set(top_signals["vt_symbol"].to_list())

        # 当前持仓
        pos_symbols = {v for v, p in self.pos_data.items() if p > 0}

        # 更新持仓天数
        for s in pos_symbols:
            self.holding_days[s] += 1

        # 卖出: 不在目标池 + 持仓超 hold_days
        sell_symbols = []
        for s in pos_symbols:
            if s not in target_symbols and self.holding_days[s] >= self.hold_days:
                sell_symbols.append(s)

        cash = self.get_cash_available()

        # 执行卖出
        for vt_symbol in sell_symbols:
            bar = bars.get(vt_symbol)
            if not bar:
                continue
            price = bar.close_price
            if not price or price != price:
                continue
            vol = self.get_pos(vt_symbol)
            if vol > 0:
                self.set_target(vt_symbol, 0)
                turnover = price * vol
                cost = max(turnover * self.close_rate, self.min_commission)
                cash += turnover - cost

        # 买入: 目标池中未持仓的
        buy_candidates = [s for s in top_signals["vt_symbol"].to_list() if s not in pos_symbols]
        if buy_candidates:
            buy_value = cash * self.cash_ratio / len(buy_candidates)
            for vt_symbol in buy_candidates:
                bar = bars.get(vt_symbol)
                if not bar:
                    continue
                price = bar.close_price
                if not price or price != price or price <= 0:
                    continue
                # 买入股数 = buy_value / 价格, round 到 100
                volume = int(buy_value / price / self.min_volume) * self.min_volume
                if volume >= self.min_volume:
                    self.set_target(vt_symbol, volume)
                    turnover = price * volume
                    cost = max(turnover * self.open_rate, self.min_commission)
                    cash -= turnover + cost

        self.execute_trading(bars, price_add=self.price_add)
