"""
多品种时序 ML 策略 (每个品种独立按信号做多空 + 风险平价仓位)

对每个品种独立应用时序信号: signal>upper 做多, signal<lower 做空, 中间空仓。
仓位: 按各品种波动率倒数分配(等风险), 波动大的品种少仓, 控制总仓位。
"""
from vnpy.trader.object import BarData, TradeData
from vnpy.trader.constant import Direction

from vnpy.alpha import AlphaStrategy


class MultiTimeseriesStrategy(AlphaStrategy):
    """多品种时序ML策略 (各品种独立信号 + 风险平价仓位)"""

    entry_upper: float = 0.0      # 做多阈值
    entry_lower: float = 0.0      # 做空阈值
    fixed_volume: float = 1.0     # 默认手数(position_mode=fixed)
    price_add: float = 5.0        # 挂单偏移
    position_mode: str = "fixed"  # fixed / risk_parity
    lookback: int = 20            # 波动率回看窗口
    target_vol: float = 0.15      # 目标年化波动率(用于定仓)


class MultiTimeseriesStrategy(AlphaStrategy):
    """多品种时序ML策略 (各品种独立信号)"""

    entry_upper: float = 0.0
    entry_lower: float = 0.0
    fixed_volume: float = 1.0
    price_add: float = 5.0
    position_mode: str = "fixed"   # fixed / risk_parity
    lookback: int = 20
    vol_target: float = 0.05
    max_volume: float = 1.0
    max_positions: int = 3          # 最多同时持仓品种数

    def on_init(self) -> None:
        self.write_log("多品种时序策略初始化")
        # 缓存各品种历史收盘(算波动率)
        self.price_history: dict[str, list[float]] = {}

    def on_trade(self, trade: TradeData) -> None:
        pass

    def calc_vol(self, prices: list[float]) -> float:
        """计算年化波动率"""
        if len(prices) < self.lookback:
            return 0.2   # 默认
        rets = [(prices[i] / prices[i-1] - 1) for i in range(1, len(prices))][-self.lookback:]
        import numpy as np
        vol = float(np.std(rets) * (240 ** 0.5))   # 年化
        return max(vol, 0.05)   # 下限5%避免除0

    def calc_volume(self, vt_symbol: str, price: float, size: float) -> float:
        """计算目标手数(风险平价)"""
        if self.position_mode == "fixed":
            return self.fixed_volume

        prices = self.price_history.get(vt_symbol, [])
        vol = self.calc_vol(prices)
        # 按波动率定仓: 目标波动 / 实际波动 * 资金 / (价格*size)
        cash = self.get_cash_available()
        # 单品种风险预算 = 总资金 * vol_target / (品种数 * vol)
        n_symbols = 12
        risk_budget = cash * self.vol_target / (n_symbols * vol)
        volume = risk_budget / (price * size) if price > 0 else 0
        volume = int(volume)   # 取整
        return max(1, min(volume, self.max_volume))

    def on_bars(self, bars: dict[str, BarData]) -> None:
        last_signal = self.get_signal()
        if last_signal.is_empty():
            return

        sig_map = dict(zip(last_signal["vt_symbol"], last_signal["signal"]))

        # 统计当前持仓品种数
        held = [s for s, p in self.pos_data.items() if p != 0]
        new_positions_available = max(0, self.max_positions - len(held))

        # 按信号强度排序候选品种(绝对值越大越强)
        candidates = []
        for vt_symbol, bar in bars.items():
            if not bar or vt_symbol not in sig_map:
                continue
            price = bar.close_price
            if not price or price != price:
                continue
            candidates.append((vt_symbol, abs(sig_map[vt_symbol]), bar))
        candidates.sort(key=lambda x: x[1], reverse=True)

        for vt_symbol, _, bar in candidates:
            signal_value = sig_map[vt_symbol]
            price = bar.close_price

            # 更新价格历史(算波动率)
            hist = self.price_history.setdefault(vt_symbol, [])
            hist.append(price)
            if len(hist) > self.lookback * 2:
                hist.pop(0)

            pos = self.pos_data.get(vt_symbol, 0)
            size = self.strategy_engine.sizes.get(vt_symbol, 10)

            if signal_value > self.entry_upper:
                # 已持仓直接调仓,新开仓受 max_positions 限制
                if pos > 0:
                    continue
                if pos < 0:
                    self.set_target(vt_symbol, 0)
                elif new_positions_available > 0:
                    target_vol = self.calc_volume(vt_symbol, price, size)
                    self.set_target(vt_symbol, target_vol)
                    new_positions_available -= 1
            elif signal_value < self.entry_lower:
                if pos < 0:
                    continue
                if pos > 0:
                    self.set_target(vt_symbol, 0)
                elif new_positions_available > 0:
                    target_vol = self.calc_volume(vt_symbol, price, size)
                    self.set_target(vt_symbol, -target_vol)
                    new_positions_available -= 1
            else:
                # 中间区间: 平仓(释放持仓名额)
                if pos != 0:
                    self.set_target(vt_symbol, 0)

        self.execute_trading(bars, price_add=self.price_add)
