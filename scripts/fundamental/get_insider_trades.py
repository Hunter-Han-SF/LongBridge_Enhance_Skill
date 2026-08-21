"""获取 SEC Form 4 内部人交易 + 买卖信号汇总(⚠️仅美股)。

对应 Longbridge CLI: insider-trades <SYMBOL>
独立性比卖方评级强:高管/大股东用真金白银投票。
type: BUY(买入)/SELL(卖出)/EXERCISE(行权)/GRANT(授予)/GIFT(赠与)等;
code: 'A'= acquire(买)/'D'= dispose(卖)/'M'= option exercise(Form 4 code)。

加工:净买入金额、买卖笔数/金额统计、最大单笔交易。

用法:
    python get_insider_trades.py TSLA.US
    python get_insider_trades.py TSLA.US --count 40
    python get_insider_trades.py TSLA.US --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_insider_trades,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)

_BUY_TYPES = {"BUY", "PURCHASE", "GRANT", "EXERCISE"}
_SELL_TYPES = {"SELL", "SALE"}


def _classify(t: str, code: str) -> str:
    t = str(t or "").upper()
    code = str(code or "").upper()
    if t in _SELL_TYPES or code == "D":
        return "卖出"
    if t in _BUY_TYPES or code == "A":
        return "买入"
    return t or code or "其他"


def fetch_insider_trades(symbol: str, count: int = 20, output_json: bool = False) -> dict:
    trades = get_insider_trades(symbol, count=count)
    if is_empty(trades):
        raise ValueError(f"无内部人交易数据({symbol})。确认是美股(SEC Form 4 仅覆盖 US)。")

    for t in trades:
        t["side"] = _classify(t.get("type"), t.get("code"))

    buys = [t for t in trades if t["side"] == "买入"]
    sells = [t for t in trades if t["side"] == "卖出"]
    buy_value = sum(to_float(t.get("value")) or 0 for t in buys)
    sell_value = sum(to_float(t.get("value")) or 0 for t in sells)
    net = buy_value - sell_value
    largest = max(trades, key=lambda t: to_float(t.get("value")) or 0)

    def _signal(net_value: float) -> str:
        if net_value > 0 and sell_value == 0:
            return "净买入(偏多)"
        if net_value < 0 and buy_value == 0:
            return "净卖出(偏空)"
        return "多空混合(中性)"

    result = {
        "symbol": symbol,
        "total": len(trades),
        "stats": {
            "buy_count": len(buys), "sell_count": len(sells),
            "buy_value": buy_value, "sell_value": sell_value, "net_value": net,
            "signal": _signal(net),
        },
        "largest_trade": largest,
        "trades": trades,
    }

    if output_json:
        print_json(result)
        return result

    s = result["stats"]
    print(f"{symbol} 内部人交易(近 {len(trades)} 笔)")
    print(f"  买入 {s['buy_count']} 笔 / {s['buy_value']/1e6:.2f}M 美元,"
          f"卖出 {s['sell_count']} 笔 / {s['sell_value']/1e6:.2f}M 美元")
    print(f"  净额 {net/1e6:+.2f}M 美元 → {s['signal']}")
    print(f"  最大单笔: {largest.get('owner')}({largest.get('title')})"
          f" {largest.get('side')} {largest.get('shares')} 股"
          f" @ {largest.get('price')}(值 {to_float(largest.get('value')) or 0:,.0f})")
    print()
    rows = [{
        "日期": t.get("date", ""),
        "内部人": str(t.get("owner", ""))[:12],
        "职务": str(t.get("title", ""))[:10],
        "方向": t.get("side", ""),
        "股数": f"{to_float(t.get('shares')) or 0:,.0f}",
        "价格": t.get("price", ""),
        "金额": f"{to_float(t.get('value')) or 0:,.0f}",
        "剩余持股": f"{to_float(t.get('shares_after')) or 0:,.0f}",
    } for t in trades]
    print_display_table(rows, columns=["日期", "内部人", "职务", "方向", "股数", "价格", "金额", "剩余持股"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="内部人交易(SEC Form 4,仅US)")
    parser.add_argument("symbol", help="美股代码,如 TSLA.US")
    parser.add_argument("--count", type=int, default=20, help="返回笔数(默认 20)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_insider_trades(args.symbol, count=args.count, output_json=args.output_json)
    except Exception as e:
        print_error("获取内部人交易", str(e))
        sys.exit(1)
