from datetime import datetime, timedelta, time
from typing import Optional, Callable
from pathlib import Path

from pandas import DataFrame
from xtquant.xtdata import (
    get_local_data,
    download_history_data,
    get_instrument_detail
)
from xtquant import xtdatacenter as xtdc

from vnpy.trader.setting import SETTINGS
from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData, TickData, HistoryRequest
from vnpy.trader.utility import ZoneInfo, TEMP_DIR
from vnpy.trader.datafeed import BaseDatafeed


INTERVAL_VT2XT: dict[Interval, str] = {
    Interval.MINUTE: "1m",
    Interval.DAILY: "1d",
    Interval.TICK: "tick"
}

INTERVAL_ADJUSTMENT_MAP: dict[Interval, timedelta] = {
    Interval.MINUTE: timedelta(minutes=1),
    Interval.DAILY: timedelta()         # 日线无需进行调整
}

EXCHANGE_VT2XT: dict[str, Exchange] = {
    Exchange.SSE: "SH",
    Exchange.SZSE: "SZ",
    Exchange.BSE: "BJ",
    Exchange.SHFE: "SF",
    Exchange.CFFEX: "IF",
    Exchange.INE: "INE",
    Exchange.DCE: "DF",
    Exchange.CZCE: "ZF",
    Exchange.GFEX: "GF",
}

CHINA_TZ = ZoneInfo("Asia/Shanghai")


class XtDatafeed(BaseDatafeed):
    """迅投研数据服务接口"""

    def __init__(self):
        """"""
        self.username: str = SETTINGS["datafeed.username"]
        self.password: str = SETTINGS["datafeed.password"]
        self.inited: bool = False
        self.password = "4aebb9927879326eb2be5e97542853a0b9b9ddd2"

    def init(self, output: Callable = print) -> bool:
        """初始化"""
        if self.inited:
            return True

        try:
            # 使用Token连接，无需启动客户端
            if self.username != "client":
                xtdc.set_token(self.password)

                now: datetime = datetime.now()
                home_dir: Path = TEMP_DIR.joinpath("xt").joinpath(now.strftime("%Y%m%d%H%M%S%f"))
                xtdc.set_data_home_dir(str(home_dir))

                xtdc.init()

            get_instrument_detail("000001.SZ")
        except Exception as ex:
            output(f"迅投研数据服务初始化失败，发生异常：{ex}")
            return False

        self.inited = True
        return True

    def query_bar_history(self, req: HistoryRequest, output: Callable = print) -> Optional[list[BarData]]:
        """查询K线数据"""
        history: list[BarData] = []

        if not self.inited:
            n: bool = self.init(output)
            if not n:
                return history

        df: DataFrame = get_history_df(req, output)
        if df.empty:
            return history

        adjustment: timedelta = INTERVAL_ADJUSTMENT_MAP[req.interval]

        # 遍历解析
        auction_bar: BarData = None

        for tp in df.itertuples():
            # 将迅投研时间戳（K线结束时点）转换为VeighNa时间戳（K线开始时点）
            dt: datetime = datetime.fromtimestamp(tp.time / 1000)
            dt = dt.replace(tzinfo=CHINA_TZ)
            dt = dt - adjustment

            # 日线，过滤尚未走完的当日数据
            if req.interval == Interval.DAILY:
                incomplete_bar: bool = (
                    dt.date() == datetime.now().date()
                    and datetime.now().time() < time(hour=15)
                )
                if incomplete_bar:
                    continue
            # 分钟线，过滤盘前集合竞价数据（合并到开盘后第1根K线中）
            else:
                if (
                    req.exchange in (Exchange.SSE, Exchange.SZSE, Exchange.BSE, Exchange.CFFEX)
                    and dt.time() < time(hour=9, minute=30)
                ):
                    auction_bar = BarData(
                        symbol=req.symbol,
                        exchange=req.exchange,
                        datetime=dt,
                        open_price=float(tp.open),
                        volume=float(tp.volume),
                        turnover=float(tp.amount),
                        gateway_name="XT"
                    )
                    continue

            # 生成K线对象
            bar: BarData = BarData(
                symbol=req.symbol,
                exchange=req.exchange,
                datetime=dt,
                interval=req.interval,
                volume=float(tp.volume),
                turnover=float(tp.amount),
                open_interest=float(tp.openInterest),
                open_price=float(tp.open),
                high_price=float(tp.high),
                low_price=float(tp.low),
                close_price=float(tp.close),
                gateway_name="XT"
            )

            # 合并集合竞价数据
            if auction_bar:
                bar.open_price = auction_bar.open_price
                bar.volume += auction_bar.volume
                bar.turnover += auction_bar.turnover
                auction_bar = None

            history.append(bar)

        return history

    def query_tick_history(self, req: HistoryRequest, output: Callable = print) -> Optional[list[TickData]]:
        """查询Tick数据"""
        history: list[TickData] = []

        if not self.inited:
            n: bool = self.init(output)
            if not n:
                return history

        df: DataFrame = get_history_df(req, output)
        if df.empty:
            return history

        # 遍历解析
        for tp in df.itertuples():
            dt: datetime = datetime.fromtimestamp(tp.time / 1000)
            dt = dt.replace(tzinfo=CHINA_TZ)

            tick: TickData = TickData(
                symbol=req.symbol,
                exchange=req.exchange,
                datetime=dt,
                volume=float(tp.volume),
                turnover=float(tp.amount),
                open_interest=float(tp.openInt),
                open_price=float(tp.open),
                high_price=float(tp.high),
                low_price=float(tp.low),
                last_price=float(tp.lastPrice),
                pre_close=float(tp.lastClose),
                bid_price_1=float(tp.bidPrice[0]),
                ask_price_1=float(tp.askPrice[0]),
                bid_volume_1=float(tp.bidVol[0]),
                ask_volume_1=float(tp.askVol[0]),
                gateway_name="XT",
            )

            bid_price_2: float = float(tp.bidPrice[1])
            if bid_price_2:
                tick.bid_price_2 = bid_price_2
                tick.bid_price_3 = float(tp.bidPrice[2])
                tick.bid_price_4 = float(tp.bidPrice[3])
                tick.bid_price_5 = float(tp.bidPrice[4])

                tick.ask_price_2 = float(tp.askPrice[1])
                tick.ask_price_3 = float(tp.askPrice[2])
                tick.ask_price_4 = float(tp.askPrice[3])
                tick.ask_price_5 = float(tp.askPrice[4])

                tick.bid_volume_2 = float(tp.bidVol[1])
                tick.bid_volume_3 = float(tp.bidVol[2])
                tick.bid_volume_4 = float(tp.bidVol[3])
                tick.bid_volume_5 = float(tp.bidVol[4])

                tick.ask_volume_2 = float(tp.askVol[1])
                tick.ask_volume_3 = float(tp.askVol[2])
                tick.ask_volume_4 = float(tp.askVol[3])
                tick.ask_volume_5 = float(tp.askVol[4])

            history.append(tick)

        return history


def get_history_df(req: HistoryRequest, output: Callable = print) -> DataFrame:
    """获取历史数据DataFrame"""
    symbol: str = req.symbol
    exchange: Exchange = req.exchange
    start: datetime = req.start
    end: datetime = req.end
    interval: Interval = req.interval

    if not interval:
        interval = Interval.TICK

    xt_interval: str = INTERVAL_VT2XT.get(interval, None)
    if not xt_interval:
        output(f"讯投研查询历史数据失败：不支持的时间周期{interval.value}")
        return DataFrame()

    # 为了查询夜盘数据
    end += timedelta(1)

    # 从服务器下载获取
    xt_symbol: str = symbol + "." + EXCHANGE_VT2XT[exchange]
    start: str = start.strftime("%Y%m%d%H%M%S")
    end: str = end.strftime("%Y%m%d%H%M%S")

    if exchange in (Exchange.SSE, Exchange.SZSE) and len(symbol) > 6:
        xt_symbol += "O"

    download_history_data(xt_symbol, xt_interval, start, end)
    data: dict = get_local_data([], [xt_symbol], xt_interval, start, end, -1, "front_ratio", False)      # 默认等比前复权

    df: DataFrame = data[xt_symbol]
    return df
