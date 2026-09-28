"""
时序单标的 ML 信号策略 (适用于期货单品种,含仓位管理)

改进点(相对初版):
- 仓位管理: 按 signal 强度定仓 (信号越强仓位越大),非固定1手
- 上限按可用资金比例 + 合约价值控制风险
- 支持 signal 标准化后的多空信号
"""

from vnpy.trader.object import BarData, TradeData
from vnpy.trader.constant import Direction

from vnpy.alpha import AlphaStrategy


class TimeseriesDemoStrategy(AlphaStrategy):
    """时序单标的 ML 信号策略 (含仓位管理)"""

    entry_upper: float = 0.0       # 做多信号阈值
    entry_lower: float = 0.0       # 做空信号阈值
    fixed_volume: float = 1.0      # 固定交易手数 (position_mode=fixed 时用)
    price_add: float = 0.0         # 挂单价格偏移
    min_volume: float = 1.0        # 最小下单单位

    # 仓位管理参数
    position_mode: str = "fixed"          # fixed(固定手数) / signal(按信号强度) / kelly(简化凯利)
    max_capital_ratio: float = 0.5         # 最大占用资金比例 (position_mode=signal/kelly)
    signal_scale: float = 2.0              # 信号强度放大系数 (signal 越大仓位越大)

    def on_init(self) -> None:
        """策略初始化"""
        self.write_log("时序ML策略初始化")

    def on_trade(self, trade: TradeData) -> None:
        """成交回调"""
        pass

    def calc_volume(self, signal_value: float, price: float, size: int) -> float:
        """根据仓位模式计算目标手数"""
        if self.position_mode == "fixed":
            return self.fixed_volume

        # 可用资金 * 比例 / (价格 * 合约乘数)
        cash = self.get_cash_available()
        max_value = cash * self.max_capital_ratio
        base_volume = max_value / (price * size) if price > 0 else 0

        if self.position_mode == "signal":
            # 信号强度定仓: |signal| * scale 决定仓位比例 (0~1)
            strength = min(abs(signal_value) * self.signal_scale, 1.0)
            volume = base_volume * strength
        elif self.position_mode == "kelly":
            # 简化凯利: 仓位 = 2*signal (信号正则多,负则空),clip 到 [0,1] * base
            strength = min(abs(signal_value) * 2, 1.0)
            volume = base_volume * strength
        else:
            volume = self.fixed_volume

        # 取整到 min_volume
        volume = int(volume / self.min_volume) * self.min_volume
        return max(volume, self.min_volume)

    def on_bars(self, bars: dict[str, BarData]) -> None:
        """K线切片回调"""
        last_signal = self.get_signal()
        if last_signal.is_empty():
            return

        # 当前持仓
        pos: float = 0.0
        for vt_symbol, p in self.pos_data.items():
            pos += p

        signal_row = last_signal.row(0, named=True)
        signal_value: float = signal_row["signal"]
        vt_symbol: str = signal_row["vt_symbol"]

        bar: BarData | None = bars.get(vt_symbol)
        if not bar:
            return

        price: float = bar.close_price
        # 合约乘数从引擎的 sizes dict 获取
        size: float = self.strategy_engine.sizes.get(vt_symbol, 10)

        # 信号决策 + 仓位计算
        if signal_value > self.entry_upper:
            target_vol = self.calc_volume(signal_value, price, size)
            if pos < 0:
                self.set_target(vt_symbol, 0)
            if pos <= 0:
                self.set_target(vt_symbol, target_vol)

        elif signal_value < self.entry_lower:
            target_vol = self.calc_volume(signal_value, price, size)
            if pos > 0:
                self.set_target(vt_symbol, 0)
            if pos >= 0:
                self.set_target(vt_symbol, -target_vol)

        else:
            # 中间区间空仓
            if pos != 0:
                self.set_target(vt_symbol, 0)

        self.execute_trading(bars, price_add=self.price_add)
