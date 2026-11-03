"""财务健康检查(三大报表关键指标 + 增长/盈利质量/杠杆)。

数据源: longbridge financial-report(IS 利润 / BS 资产负债 / CF 现金流)。

提取并加工:
  增长: 营收 YoY / 净利润 YoY / EPS YoY / 自由现金流 YoY
  盈利: 毛利率 / 净利率 / ROE / 盈利质量(自由现金流 ÷ 净利润)
  杠杆: 负债率(总负债/总资产) / 权益乘数 / 净债务
  现金: 经营现金流 / 资本支出

各项给出简单灯号(🟢 良好 / 🟡 中性 / 🔴 预警),灯号阈值为通用经验值。

用法:
    python get_financial_health.py AAPL.US
    python get_financial_health.py 0700.HK --json
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_financial_report,
    print_display_table,
    print_error,
    print_json,
    to_float,
)

# 中文名 → 标准键(实测 financial-report 的 accounts 按 name 匹配,ranking_code 不总存在)
_ACCOUNT_MAP = {
    "每股收益": "eps",
    "基本每股收益": "eps",
    "每股基本收益": "eps",
    "营业收入": "revenue",
    "净利润": "net_profit",
    "归母净利润": "net_profit",
    "归属于母公司股东的净利润": "net_profit",
    "毛利率": "gross_margin",
    "净利率": "net_margin",
    "净利润率": "net_margin",
    "归母净利润率": "net_margin",
    "总资产": "total_assets",
    "总负债": "total_liabilities",
    "权益乘数": "leverage",
    "净债务": "net_debt",
    "经营现金流": "operating_cf",
    "自由现金流": "fcf",
    "资本支出": "capex",
    "eps": "eps",
    "roe": "roe",
    "revenue": "revenue",
    "net income": "net_profit",
    "gross margin": "gross_margin",
    "net margin": "net_margin",
    "total assets": "total_assets",
    "total liabilities": "total_liabilities",
    "equity multiplier": "leverage",
    "net debt": "net_debt",
    "operating cash flow": "operating_cf",
    "free cash flow": "fcf",
    "capital expenditure": "capex",
}


def _flatten(report: dict) -> dict:
    """把三张报表的 accounts 展平成 {标准键: {value, yoy, period}}(取每项最新一期)。"""
    out = {}
    for stmt in ("IS", "BS", "CF"):
        for group in ((report.get("list") or {}).get(stmt) or {}).get("indicators", []):
            for acc in group.get("accounts", []):
                name = str(acc.get("name") or "").strip()
                key = _ACCOUNT_MAP.get(name.casefold())
                if not key:
                    continue
                vals = acc.get("values") or []
                if not vals:
                    continue
                latest = vals[0]  # 实测最新期在前
                v = to_float(latest.get("value"))
                if v is None:
                    continue
                if key not in out or (name == "净利润" and out[key]["name"] != "净利润"):
                    out[key] = {
                        "value": v,
                        "yoy_pct": to_float(latest.get("yoy")),
                        "period": latest.get("period", ""),
                        "year": latest.get("year"),
                        "period_type": (latest.get("period_type") or latest.get("report_type")
                                        or acc.get("period_type") or acc.get("report_type")),
                        "name": name,
                    }
    return out


def _light(value, good, warn, higher_is_good=True) -> str:
    """简单灯号。good/warn 为阈值,方向由 higher_is_good 决定。None 返回空。"""
    if value is None:
        return ""
    ok = value >= good if higher_is_good else value <= good
    bad = value < warn if higher_is_good else value > warn
    if ok:
        return "🟢"
    if bad:
        return "🔴"
    return "🟡"


def analyze(symbol: str, output_json: bool = False, quiet: bool = False) -> dict:
    report = get_financial_report(symbol)
    if not report:
        raise ValueError(f"无 {symbol} 财务报表数据")
    items = _flatten(report)
    if not items:
        raise ValueError(f"{symbol} 报表中未匹配到关键科目(字段名可能变化)")

    g = lambda k: items.get(k, {}).get("value")  # noqa: E731
    yoy = lambda k: items.get(k, {}).get("yoy_pct")  # noqa: E731

    def same_period(left, right):
        left, right = items.get(left, {}), items.get(right, {})
        period = left.get("period")
        if not period or period != right.get("period"):
            return False
        year = re.search(r"(?:19|20)[0-9]{2}", str(period))
        year_in_period = year.group() if year else None
        left_year = str(left.get("year") or year_in_period or "")
        right_year = str(right.get("year") or year_in_period or "")
        return bool(left_year and left_year == right_year
                    and left.get("period_type") == right.get("period_type"))
    debt_ratio = None
    if (g("total_liabilities") is not None and (g("total_assets") or 0) > 0
            and same_period("total_liabilities", "total_assets")):
        debt_ratio = g("total_liabilities") / g("total_assets") * 100
    earnings_quality = None  # FCF / 净利润(%)
    if g("fcf") is not None and (g("net_profit") or 0) > 0 and same_period("fcf", "net_profit"):
        earnings_quality = g("fcf") / g("net_profit") * 100

    rows = []
    def add(label, value, unit, light, extra=""):
        rows.append({"指标": label, "值": value if value is not None else "N/A",
                     "单位": unit, "灯": light, "备注": extra})

    add("最新报告期", None, "", "", items.get("revenue", items.get("eps", {})).get("period", ""))
    add("营收 YoY", yoy("revenue"), "%", _light(yoy("revenue"), 10, 0), "≥10% 高增长")
    add("净利润 YoY", yoy("net_profit"), "%", _light(yoy("net_profit"), 10, 0))
    add("毛利率", g("gross_margin"), "%", _light(g("gross_margin"), 40, 20), "行业差异大")
    add("净利率", g("net_margin"), "%", _light(g("net_margin"), 15, 5))
    add("ROE", g("roe"), "%", _light(g("roe"), 15, 8))
    add("负债率", debt_ratio, "%", _light(debt_ratio, 60, 75, higher_is_good=False), "总负债/总资产")
    add("经营现金流 YoY", yoy("operating_cf"), "%", _light(yoy("operating_cf"), 0, -10))
    add("FCF/净利润", earnings_quality, "%", _light(earnings_quality, 80, 50), "≥80% 盈利质量好")
    if g("net_debt") is not None:
        add("净债务", g("net_debt"), "", "", "负值=净现金 🟢" if (g("net_debt") or 0) < 0 else "正值=净负债")

    # 红绿灯计数
    greens = sum(1 for r in rows if r["灯"] == "🟢")
    reds = sum(1 for r in rows if r["灯"] == "🔴")
    scored = sum(bool(r["灯"]) for r in rows)
    if reds == 0 and (scored < 5 or debt_ratio is None or earnings_quality is None):
        verdict = "⚪ 关键指标不足，无法判断财务稳健"
    elif reds == 0 and greens >= 5:
        verdict = "🟢 多项指标达到经验阈值（无红灯）"
    elif reds == 0:
        verdict = "🟢 已评估指标无红灯"
    elif reds <= 2:
        verdict = "🟡 有少量预警项,需关注"
    else:
        verdict = "🔴 多项指标触发经验预警"

    result = {
        "symbol": symbol,
        "period": rows[0]["备注"],
        "items": {k: v for k, v in items.items()},
        "computed": {"debt_ratio_pct": debt_ratio, "earnings_quality_pct": earnings_quality},
        "table": rows,
        "greens": greens, "reds": reds, "scored_metrics": scored,
        "verdict": verdict,
        "note": "经验阈值未按行业校准。FCF/净利润只在同期净利润为正且报表口径一致时评估。",
    }

    if output_json:
        print_json(result)
        return result
    if quiet:
        return result

    print(f"{symbol} 财务健康检查(报告期 {result['period']})")
    print_display_table(
        [{"指标": r["指标"], "值": (f"{r['值']:.2f}" if isinstance(r["值"], (int, float)) else r["值"]),
          "单位": r["单位"], "灯": r["灯"], "备注": r["备注"]} for r in rows[1:]],
        columns=["指标", "值", "单位", "灯", "备注"])
    print()
    print(f"  结论: {verdict}(🟢{greens} / 🔴{reds})")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="财务健康检查(三大报表关键指标)")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US / 0700.HK")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze(args.symbol, output_json=args.output_json)
    except Exception as e:
        print_error("财务健康", str(e))
        sys.exit(1)
