"""测试夹具:全部取自 2026-08-21 对真实 CLI 的探测输出(已裁剪)。

配合 mock_run_cli 使用:按 (子命令序列) 分发返回对应夹具。
"""
from __future__ import annotations

import json
import unittest.mock
from typing import Any, Callable

# ---- warrant ----
WARRANT_LIST = [
    {"expiry": "2028-08-02", "last": "0.67", "leverage_ratio": "1.3361194029850747",
     "name": "UB#TENCTRP2808D", "symbol": "61304.HK", "type": "Call"},
    {"expiry": "2028-12-29", "last": "0.66", "leverage_ratio": "1.3563636363636364",
     "name": "SG#TENCTRP28125", "symbol": "53472.HK", "type": "Call"},
    {"expiry": "2026-09-01", "last": "0.01", "leverage_ratio": "447.6",
     "name": "CTTENCT@EC2609B", "symbol": "28582.HK", "type": "Call"},
]
WARRANT_QUOTE = [
    {"expiry": "2026-09-01", "implied_vol": "0.822", "last": "0.010",
     "prev_close": "0.010", "symbol": "28582.HK", "type": "Call"},
    {"expiry": "2028-08-02", "implied_vol": "0.000", "last": "0.670",
     "prev_close": "0.670", "symbol": "61304.HK", "type": "Bear"},
]
WARRANT_ISSUERS = [
    {"id": "8", "name_cn": "法兴", "name_en": "SG"},
    {"id": "15", "name_cn": "瑞银", "name_en": "UB"},
    {"id": "14", "name_cn": "汇丰", "name_en": "HS"},
]

# ---- screener ----
SCREENER_STRATEGIES = [
    {"id": 19, "name": "今日大涨股票", "type": "platform"},
    {"id": 27, "name": "低估值", "type": "platform"},
]
SCREENER_RUN = {"items": [
    {"industry": "医疗器械", "marketcap": 4909979957.52, "name": "心泰医疗",
     "pbmrq": 1.8645164729946344, "pettm": 16.150798190442924,
     "prevchg": 16.256157635467993, "prevclose": 14.16,
     "salesgrowthyoy": 13.02140996647048, "symbol": "2291.HK"},
]}
SCREENER_FILTER = {"items": [
    {"industry": "餐厅", "marketcap": 80539080.952, "name": "佳景集团",
     "pbmrq": 0.1845509170552187, "pettm": 15.303825956489122,
     "prevchg": 5.0, "prevclose": 0.5, "salesgrowthyoy": "",
     "symbol": "708.HK"},
]}
SCREENER_INDICATORS = [
    {"id": "-1", "key": "market", "max": None, "min": None, "name": "市场", "unit": ""},
    {"id": "1", "key": "marketcap", "max": None, "min": None, "name": "市值",
     "unit": "美元"},
]

# ---- brokers / participants ----
BROKERS_QUEUE = {
    "asks": [{"broker_ids": [3284, 5345, 3436], "position": 1},
             {"broker_ids": [2340, 2083], "position": 2}],
    "bids": [{"broker_ids": [5337, 9059, 5345], "position": 1},
             {"broker_ids": [6999, 2453], "position": 2}],
}
PARTICIPANTS = [
    {"broker_id": "5345", "name_cn": "摩根士丹利(香港)", "name_en": "MS"},
    {"broker_id": "5337", "name_cn": "高盛(亚洲)", "name_en": "GS"},
    {"broker_id": "7707, 7708, 7709", "name_cn": "同舟证券", "name_en": "Ark"},
    {"broker_id": "3284", "name_cn": "美林远东", "name_en": "ML"},
]

# ---- finance-calendar ----
CAL_SPLIT = {
    "date": "2026-08-21",
    "list": [
        {"date": "2026-08-21", "infos": [
            {"content": "5 股合并为 1 股", "counter_id": "ST/US/BTOG",
             "counter_name": "Bit Origin", "date": "2026.08.21 (美东)",
             "ext": {"announcement_date": "2026.08.19 (美东)", "industry": "应用软件"}},
            {"content": "1 股拆分为 2 股", "counter_id": "ST/US/SFBS",
             "counter_name": "ServisFirst", "date": "2026.08.21 (美东)", "ext": {}},
        ]},
    ],
}
CAL_MACRODATA = {
    "date": "2026-08-21",
    "list": [
        {"date": "2026-08-21", "infos": [
            {"content": "美国, 30年期 TIPS 竞拍 - 总金额", "counter_id": "",
             "counter_name": "", "date": "2026.08.21",
             "data_kv": [
                 {"key": "前值", "type": "previous", "value": "9000008600", "value_raw": ""},
                 {"key": "实际", "type": "actual", "value": "9028453400", "value_raw": ""},
             ]},
        ]},
    ],
}
CAL_CLOSED = {
    "date": "2026-08-21",
    "list": [
        {"date": "2026-09-07", "infos": [
            {"content": "劳动节", "date_type": "全日",
             "ext": {"holiday_date": "2026-09-07", "holiday_type": "full_day"}},
        ]},
    ],
}
CAL_IPO = {"date": "2026-08-21", "list": [], "next_date": "", "result": {}}

# ---- ipo ----
IPO_WAIT_LISTING = {
    "hk": [{
        "currency": "HKD", "description": "公司主要从事集成电路芯片产品的研发与销售",
        "ipo_date": "1787587200", "issue_price": "100.000", "market": "HK",
        "mart_status": "closed", "name": "君正股份", "symbol": "3223.HK",
    }],
    "us": [],
}
IPO_SUBSCRIPTIONS = {"hk": [], "us": []}
IPO_DETAIL = {
    "eligibility": {"can_subscribe": True},
    "holdings": {"current_amount": "0.00", "finance_fee_rate": "0.068",
                 "ipo_max_purchase": "0", "total_amount": "126.48"},
    "profile": {"hk": {
        "counter_id": "", "industry": "半导体",
        "investors": [{"capital_ratio": "0", "name": "Arrow Target Investment L.P.",
                       "subscribe_value": "0"}],
        "issue_price": "100.000",
        "profile": "研发、设计、销售半导体集成电路芯片",
    }},
}

# ---- macrodata ----
MACRO_LIST = {
    "count": 2, "has_more": False, "limit": 20,
    "list": [
        {"country": "EU", "describe": "HICP ...", "importance": "3",
         "indicator_code": "30771434", "name": "Euro Zone, CPI, Chg P/P",
         "periodicity": "month"},
        {"country": "US", "describe": "PCE ...", "importance": "1",
         "indicator_code": "30771936", "name": "US PCE, Chg P/P",
         "periodicity": "month"},
    ],
}
MACRO_HISTORY = {
    "count": 3,
    "data": [
        {"actual_value": "", "forecast_value": "0.2", "period": "2026-07-01",
         "previous_value": "-0.1", "release_at": 1787130000, "unit": "Percent"},
        {"actual_value": "0.3", "forecast_value": "0.3", "period": "2026-06-01",
         "previous_value": "0.7", "release_at": 1784278800, "unit": "Percent"},
        {"actual_value": "0.7", "forecast_value": "0.6", "period": "2026-05-01",
         "previous_value": "0.5", "release_at": 1781596800, "unit": "Percent"},
    ],
}

# ---- quant ----
QUANT_RESULT = {"series": {"EMA Fast": [10.0, 11.0, 12.5], "EMA Slow": [9.8, 10.1, 10.9]}}

# ---- fundamental ----
COMPARE = {"list": [
    {"assets": "383266000000", "bps": "7.359865", "counter_id": "ST/US/AAPL",
     "currency": "USD", "div_yld": "0.34", "eps": "8.717074", "market": "US",
     "market_value": "4540000000000", "name": "苹果", "net_margin": "27.6",
     "pe": "40.6", "pb": "42.25", "price_close": "311.3", "ps": "9.73",
     "roa": "28.5", "roe": "148.8", "volume": "50000000",
     "history": [{"date": "1630468800", "pb": "38.5", "pe": "46.0", "ps": "7.1"}]},
    {"assets": "512000000000", "bps": "30.5", "counter_id": "ST/US/MSFT",
     "currency": "USD", "div_yld": "0.76", "eps": "14.5", "market": "US",
     "market_value": "3570000000000", "name": "微软", "net_margin": "40.3",
     "pe": "26.7", "pb": "8.08", "price_close": "481.15", "ps": "10.77",
     "roa": "20.2", "roe": "34.0", "volume": "20000000",
     "history": []},
]}
SEGMENTS = {
    "bus_ids": ["117095"],
    "business": [
        {"id": "117095", "name": "美洲", "percent": "41.84",
         "value": "45781000000", "yoy": "1.52573570177189"},
        {"id": "116436", "name": "欧洲", "percent": "26.87",
         "value": "29395000000", "yoy": "4.77633220459811"},
    ],
}
INDUSTRY_RANK = {"items": [{
    "chg": "", "counter_id": "", "name": "板块涨幅榜",
    "lists": [
        {"chg": "0.1544", "counter_id": "BK/US/IN00362", "delay": False,
         "leading_chg": "0.1544", "leading_counter_id": "ST/US/SGLY",
         "leading_last_done": "3.440", "leading_name": "Singularity Future Tech",
         "leading_ticker": "SGLY", "name": "海运港口-运营商"},
        {"chg": "0.0637", "counter_id": "BK/US/IN00317", "delay": False,
         "leading_chg": "0.0694", "leading_name": "迪尔",
         "leading_ticker": "DE", "name": "农用机械"},
    ],
}]}
INDUSTRY_PEERS = {
    "chain": {"chg": "", "code": "3253000", "counter_id": "BK/US/IN00362",
              "level": 0, "market": "US", "name": "海运港口-运营商",
              "next": [], "stock_num": 1},
    "top": {"industry_id": "87068", "market": "US", "name": "工业"},
}
CONSENSUS = {
    "currency": "USD", "current_index": 3, "current_period": "qf",
    "list": [
        {"fiscal_period": "2", "fiscal_year": "2027", "period_text": "Q2 2027",
         "details": [
             {"actual": "", "estimate": "123287028540.0000", "is_released": False,
              "key": "revenue", "name": "营业收入"},
             {"actual": "1.9", "estimate": "2.2", "is_released": True,
              "key": "eps", "name": "每股收益"},
         ]},
    ],
}
CORP_ACTIONS = {"items": [
    {"act_desc": "每股派息 0.27 USD", "act_type": "分配方案",
     "action": "DividendExDate", "date": "20260813", "date_str": "08.13",
     "date_type": "派息日", "date_zone": "美东时间"},
    {"act_desc": "三季报", "act_type": "业绩披露", "action": "EarningReport",
     "date": "20260730", "date_str": "07.30", "date_type": "", "date_zone": ""},
]}
OPERATING = {"list": [
    {"financial": {"currency": "HKD", "indicators": [
        {"field_name": "operating_revenue", "indicator_name": "营业收入",
         "indicator_value": "4589 亿", "yoy": "16.27"},
        {"field_name": "net_profit", "indicator_name": "净利润",
         "indicator_value": "1305 亿", "yoy": "16.52"},
    ]},
     "period": "2026Q2"},
]}
COMPANY = {
    "company_name": "Apple Inc.", "employees": "166000", "founded": "1976",
    "address": "One Apple Park Way", "manager": "Timothy D. Cook",
    "listing_date": "", "issue_price": "",
}
EXECUTIVES = {"professional_list": [{
    "counter_id": "ST/US/AAPL",
    "professionals": [
        {"biography": "CEO since 2011", "name": "Timothy D. Cook", "title": "CEO & Director"},
        {"biography": "CFO", "name": "Luca Maestri", "title": "CFO"},
    ],
}]}

# ---- 信号源 ----
INSIDER_TRADES = [
    {"code": "M", "date": "2026-03-31", "filing_date": "2026-04-02",
     "owner": "Zhu Xiaotong", "price": 20.57, "shares": 20000.0,
     "shares_after": 20000.0, "title": "SVP", "type": "EXERCISE", "value": 411400.0},
    {"code": "S", "date": "2026-03-20", "filing_date": "2026-03-22",
     "owner": "Kimbal Musk", "price": 250.0, "shares": 5000.0,
     "shares_after": 100000.0, "title": "Director", "type": "SELL", "value": 1250000.0},
]
INVESTOR_RANKINGS = [
    {"aum_usd": 644560214942, "cik": "0001422848",
     "name": "Capital Research Global Investors", "period": "31-MAR-2026", "rank": 1},
    {"aum_usd": 426517500633, "cik": "0001562230",
     "name": "Capital International Investors", "period": "31-MAR-2026", "rank": 2},
]
INVESTOR_HOLDINGS = {
    "accession_number": "0001422848-26-000094", "cik": "0001422848",
    "filing_date": "2026-08-12", "firm": "Capital Research Global Investors",
    "holdings": [
        {"cusip": "11135F101", "name": "BROADCOM INC", "share_type": "SH",
         "shares": 113126312, "value_usd": 42731528140, "weight_pct": "5.96"},
        {"cusip": "67066G104", "name": "NVIDIA CORPORATION", "share_type": "SH",
         "shares": 202740420, "value_usd": 4056471879, "weight_pct": "0.56"},
    ],
}
INVESTOR_CHANGES = {
    "added": 2,
    "changes": [
        {"action": "NEW", "cusip": "84615Q103", "delta_pct": "NEW",
         "delta_usd": 1783463529, "name": "SPACE EXPLORATION TECHN CORP",
         "prev_shares": 0, "prev_value_usd": 0, "shares": 10438223,
         "value_usd": 1783463529},
        {"action": "ADDED", "cusip": "02079K404", "delta_pct": "12.5",
         "delta_usd": 500000000, "name": "ALPHABET INC", "prev_shares": 1000000,
         "prev_value_usd": 4000000000, "shares": 118330677,
         "value_usd": 4500000000},
    ],
}
FUND_HOLDERS = {"lists": [
    {"code": "AAPX", "counter_id": "ETF/US/AAPX", "currency": "USD",
     "name": "T-Rex 2X Long Apple", "position_ratio": "80.82941",
     "report_date": "2026.08.18"},
    {"code": "VGT", "counter_id": "ETF/US/VGT", "currency": "USD",
     "name": "信息科技 ETF", "position_ratio": "16.25",
     "report_date": "2026.07.31"},
]}
SHAREHOLDERS = {"shareholder_list": [
    {"institution_type": "", "percent_of_shares": "7.97", "report_date": "2026-06-30",
     "shareholder_id": "0", "shareholder_name": "BlackRock, Inc.",
     "shares_changed": "18301514",
     "stocks": [{"chg": "-1.65%", "code": "BLK", "counter_id": "ST/US/BLK", "market": "US"}]},
    {"institution_type": "", "percent_of_shares": "1.93", "report_date": "2026-06-30",
     "shareholder_id": "0", "shareholder_name": "FMR LLC",
     "shares_changed": "-5000000", "stocks": []},
]}

# ---- market / intraday ----
CONSTITUENT = {
    "rise_num": 0, "fall_num": 0, "flat_num": 0,
    "stocks": [
        {"amount": "15241452", "balance": "458002204", "chg": "0.0731",
         "counter_id": "ST/HK/12", "inflow": "201213880", "last_done": "30.240",
         "market": "HK", "name": "恒基地产", "prev_close": "28.180",
         "tags": ["领涨龙头"]},
        {"amount": "8000000", "balance": "100000000", "chg": "-0.0123",
         "counter_id": "ST/HK/16", "inflow": "-5000000", "last_done": "80.000",
         "market": "HK", "name": "新鸿基地产", "prev_close": "81.000", "tags": []},
    ],
}
TRADE_STATS = {
    "statistics": {"avgprice": "447.88", "buy": "3540400", "neutral": "1220718",
                   "preclose": "451.400", "sell": "4307300",
                   "timestamp": "1787282623", "total_amount": "9068418",
                   "trade_date": ["1787241600"], "trades_count": "8916"},
    "trades": [
        {"buy_amount": "0", "neutral_amount": "2100", "price": "456.106",
         "sell_amount": "0"},
        {"buy_amount": "3500", "neutral_amount": "0", "price": "452.600",
         "sell_amount": "2100"},
        {"buy_amount": "100", "neutral_amount": "0", "price": "449.200",
         "sell_amount": "300"},
    ],
}
AH_PREMIUM = {"klines": [
    {"ahpremium_rate": "-0.30", "apreclose": "10.19", "aprice": "10.24",
     "currency_rate": "0.8594", "hpreclose": "8.54", "hprice": "8.74",
     "timestamp": "1786636800"},
    {"ahpremium_rate": "-0.26", "apreclose": "10.19", "aprice": "10.30",
     "currency_rate": "0.8592", "hpreclose": "8.54", "hprice": "8.90",
     "timestamp": "1786723200"},
    {"ahpremium_rate": "-0.24", "apreclose": "10.19", "aprice": "10.40",
     "currency_rate": "0.8592", "hpreclose": "8.54", "hprice": "9.00",
     "timestamp": "1786809600"},
    {"ahpremium_rate": "-0.26", "apreclose": "10.19", "aprice": "10.50",
     "currency_rate": "0.8592", "hpreclose": "8.54", "hprice": "9.10",
     "timestamp": "1786896000"},
]}
AH_PREMIUM_INTRADAY = {"klines": [
    {"ahpremium_rate": "-0.253", "aprice": "10.640", "currency_rate": "0.8583",
     "hprice": "9.260", "timestamp": "1787275800"},
]}

# ---- industry-valuation dist ----
INDUSTRY_VALUATION_DIST = {
    "pe": {"high": "56.64", "low": "0.92", "median": "10.86",
           "rank_index": "15", "rank_total": "20",
           "ranking": "0.7368", "value": "35.24"},
    "pb": {"high": "87.90", "low": "0.057", "median": "2.375",
           "rank_index": "34", "rank_total": "35",
           "ranking": "0.9706", "value": "42.25"},
}

# ---- quant run(pine):pretty Series 表(含 ANSI 颜色码,实测 2026-08-21) ----
PRETTY_SERIES_OUTPUT = (
    "\x1b[2m────────\x1b[0m\n"
    "\x1b[1mSeries                │  Bars│     First│      Last│       Min│       Max"
    " Sparkline\x1b[0m\n"
    "\x1b[2m────────\x1b[0m\n"
    "\x1b[38;5;14mEMA20                 \x1b[0m│     4│   +479.45│   +480.05│"
    "   +479.45│   +480.05 \x1b[38;5;14m⣀⣀⣠⣤⣶⣿⣿\x1b[0m\n"
    "\x1b[38;5;14mRSI                   \x1b[0m│     4│    +55.10│    +62.15│"
    "    +50.02│    +62.15 \x1b[38;5;14m⣀⣠⣤⣤⣶⣿\x1b[0m\n"
    "\x1b[2m────────\x1b[0m\n"
    "\x1b[2m  2 series  ·  4 bars\x1b[0m\n"
)
# ---- quant run(pine) strategy 回测响应(report_json 是嵌套 JSON 字符串) ----
BACKTEST_RESPONSE = {
    "report_json": json.dumps({
        "config": {"initialCapital": 1000000.0, "commissionValue": 0.0},
        "performanceAll": {
            "netProfit": 41.73, "netProfitPercent": 0.0042,
            "maxDrawdown": 54.26, "maxDrawdownPercent": 0.0054,
            "sharpeRatio": 0.0558, "profitFactor": 1.4788,
            "numberOfWiningTrades": 7, "numberOfLosingTrades": 5,
            "buyHoldReturnPercent": 16.241,
        },
    }),
    "events_json": "[]",
    "chart_json": "",
}


def mock_run_cli(dispatch: Callable[[tuple], Any]) -> unittest.mock.MagicMock:
    """构造 run_cli 的 mock:dispatch(args 元组) → 夹具数据。"""
    return unittest.mock.MagicMock(side_effect=lambda *a, **k: dispatch(a))
