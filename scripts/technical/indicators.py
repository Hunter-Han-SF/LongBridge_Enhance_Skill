"""技术指标数学库(纯函数,无 CLI 依赖)。

所有函数输入按时间正序(旧→新)的价格/成交量序列,返回最新值或序列。
实现遵循业界标准约定:
  - EMA: α=2/(n+1),首值用前 n 个的 SMA 做种子
  - RSI/ATR: Wilder 平滑(递归式)
  - Bollinger: 总体标准差(ddof=0)
  - KDJ: RSV=9日,(K,D)=(3,3) 平滑,种子 K=D=50
"""
from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# 均线族
# ---------------------------------------------------------------------------


def sma(vals: list[float], n: int) -> float | None:
    """简单均线(最新值)。数据不足返回 None。"""
    if len(vals) < n or n <= 0:
        return None
    return sum(vals[-n:]) / n


def sma_series(vals: list[float], n: int) -> list[float | None]:
    """SMA 序列,与 vals 等长,前方不足处为 None。"""
    out: list[float | None] = [None] * len(vals)
    if n <= 0:
        return out
    acc = 0.0
    for i, v in enumerate(vals):
        acc += v
        if i >= n:
            acc -= vals[i - n]
        if i >= n - 1:
            out[i] = acc / n
    return out


def ema_series(vals: list[float], n: int) -> list[float | None]:
    """EMA 序列。首值用前 n 个数据的 SMA 做种子(标准图表软件做法)。"""
    out: list[float | None] = [None] * len(vals)
    if n <= 0 or len(vals) < n:
        return out
    alpha = 2.0 / (n + 1)
    out[n - 1] = sum(vals[:n]) / n
    for i in range(n, len(vals)):
        out[i] = alpha * vals[i] + (1 - alpha) * out[i - 1]  # type: ignore[operator]
    return out


def ema(vals: list[float], n: int) -> float | None:
    """EMA 最新值。"""
    s = ema_series(vals, n)
    return s[-1] if s and s[-1] is not None else None


def macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """MACD(12,26,9)。

    Returns:
        {dif, dea, hist, cross: 'golden'|'death'|None(近 3 根内发生),
         hist_rising: bool}
    """
    empty = {"dif": None, "dea": None, "hist": None, "cross": None, "hist_rising": None}
    if len(closes) < slow + signal:
        return empty
    ef = ema_series(closes, fast)
    es = ema_series(closes, slow)
    dif = [a - b for a, b in zip(ef, es) if a is not None and b is not None]
    dea = [d for d in ema_series(dif, signal) if d is not None]
    if not dif or not dea:
        return empty
    hist = [d - s for d, s in zip(dif[-len(dea):], dea)]
    # 检测近 3 根内 DIF 与 DEA 的交叉(长度可能差 1,用末段对齐)
    n_cmp = min(len(dif), len(dea))
    cross = None
    for k in range(max(1, n_cmp - 3), n_cmp):
        d0, s0 = dif[k - 1], dea[k - 1]
        d1, s1 = dif[k], dea[k]
        if d0 <= s0 and d1 > s1:
            cross = "golden"
        elif d0 >= s0 and d1 < s1:
            cross = "death"
    hist_rising = len(hist) >= 2 and hist[-1] > hist[-2]
    return {"dif": dif[-1], "dea": dea[-1], "hist": hist[-1] if hist else None,
            "cross": cross, "hist_rising": hist_rising}


# ---------------------------------------------------------------------------
# 动量族
# ---------------------------------------------------------------------------


def rsi(closes: list[float], n: int = 14) -> float | None:
    """RSI(Wilder 平滑)。"""
    if len(closes) < n + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    avg_g = sum(gains[:n]) / n
    avg_l = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        avg_g = (avg_g * (n - 1) + gains[i]) / n
        avg_l = (avg_l * (n - 1) + losses[i]) / n
    if avg_l == 0:
        return 100.0 if avg_g > 0 else 50.0
    rs = avg_g / avg_l
    return 100.0 - 100.0 / (1.0 + rs)


def kdj(highs: list[float], lows: list[float], closes: list[float],
        n: int = 9, k_p: int = 3, d_p: int = 3) -> dict:
    """KDJ(9,3,3)。种子 K=D=50。

    Returns:
        {k, d, j, cross: 'golden'|'death'|None(近 3 根内 K/D 交叉)}
    """
    if len(closes) < n or not (len(highs) == len(lows) == len(closes)):
        return {"k": None, "d": None, "j": None, "cross": None}
    k, d = 50.0, 50.0
    k_hist: list[float] = []
    d_hist: list[float] = []
    for i in range(n - 1, len(closes)):
        hh = max(highs[i - n + 1: i + 1])
        ll = min(lows[i - n + 1: i + 1])
        rsv = 50.0 if hh == ll else (closes[i] - ll) / (hh - ll) * 100.0
        k = (k * (k_p - 1) + rsv) / k_p
        d = (d * (d_p - 1) + k) / d_p
        k_hist.append(k)
        d_hist.append(d)
    cross = None
    for i in range(max(1, len(k_hist) - 3), len(k_hist)):
        if k_hist[i - 1] <= d_hist[i - 1] and k_hist[i] > d_hist[i]:
            cross = "golden"
        elif k_hist[i - 1] >= d_hist[i - 1] and k_hist[i] < d_hist[i]:
            cross = "death"
    return {"k": k, "d": d, "j": 3 * k - 2 * d, "cross": cross}


def roc(closes: list[float], n: int = 20) -> float | None:
    """变动率 ROC(n)%,最新收盘 vs n 期前。"""
    if len(closes) <= n or closes[-n - 1] == 0:
        return None
    return (closes[-1] / closes[-n - 1] - 1) * 100


def williams_r(highs: list[float], lows: list[float], closes: list[float],
               n: int = 14) -> float | None:
    """威廉指标 %R(0 到 -100,0=最强)。"""
    if len(closes) < n:
        return None
    hh = max(highs[-n:])
    ll = min(lows[-n:])
    if hh == ll:
        return -50.0
    return (hh - closes[-1]) / (hh - ll) * -100


def cci(highs: list[float], lows: list[float], closes: list[float],
        n: int = 20) -> float | None:
    """CCI(20)。"""
    if len(closes) < n:
        return None
    tps = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    tp_n = tps[-n:]
    m = sum(tp_n) / n
    md = sum(abs(tp - m) for tp in tp_n) / n
    if md == 0:
        return 0.0
    return (tps[-1] - m) / (0.015 * md)


# ---------------------------------------------------------------------------
# 波动/通道族
# ---------------------------------------------------------------------------


def bollinger(closes: list[float], n: int = 20, k: float = 2.0) -> dict:
    """布林带(总体标准差)。

    Returns:
        {upper, mid, lower, bandwidth%(带宽), percent_b(0=下轨,1=上轨,0.5=中轨)}
    """
    if len(closes) < n:
        return {"upper": None, "mid": None, "lower": None, "bandwidth": None, "percent_b": None}
    window = closes[-n:]
    mid = sum(window) / n
    var = sum((c - mid) ** 2 for c in window) / n  # 总体方差(ddof=0)
    sd = math.sqrt(var)
    upper, lower = mid + k * sd, mid - k * sd
    bandwidth = (upper - lower) / mid * 100 if mid else None
    percent_b = (closes[-1] - lower) / (upper - lower) if upper > lower else 0.5
    return {"upper": upper, "mid": mid, "lower": lower,
            "bandwidth": bandwidth, "percent_b": percent_b}


def atr(highs: list[float], lows: list[float], closes: list[float],
        n: int = 14) -> float | None:
    """ATR(Wilder 平滑)。"""
    if len(closes) < n + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    a = sum(trs[:n]) / n
    for i in range(n, len(trs)):
        a = (a * (n - 1) + trs[i]) / n
    return a


def donchian(highs: list[float], lows: list[float], n: int = 20) -> dict:
    """唐奇安通道(N 日高低)。"""
    if len(highs) < n:
        return {"upper": None, "lower": None}
    return {"upper": max(highs[-n:]), "lower": min(lows[-n:])}


# ---------------------------------------------------------------------------
# 量能族
# ---------------------------------------------------------------------------


def obv(closes: list[float], volumes: list[float]) -> dict:
    """能量潮 OBV。

    Returns:
        {obv: 最新累计值, slope_20: 近 20 期一元回归斜率(每期增量), rising_20: bool}
    """
    if len(closes) < 2 or len(closes) != len(volumes):
        return {"obv": None, "slope_20": None, "rising_20": None}
    total = 0.0
    series: list[float] = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            total += volumes[i]
        elif closes[i] < closes[i - 1]:
            total -= volumes[i]
        series.append(total)
    # 近 20 期最小二乘斜率
    win = series[-20:]
    slope = None
    if len(win) >= 5:
        nn = len(win)
        x_mean = (nn - 1) / 2
        y_mean = sum(win) / nn
        num = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(win))
        den = sum((i - x_mean) ** 2 for i in range(nn))
        slope = num / den if den else None
    return {"obv": total, "slope_20": slope,
            "rising_20": bool(slope and slope > 0)}


def mfi(highs: list[float], lows: list[float], closes: list[float],
        volumes: list[float], n: int = 14) -> float | None:
    """资金流量指标 MFI(0-100)。"""
    if len(closes) < n + 1:
        return None
    pos, neg = 0.0, 0.0
    for i in range(len(closes) - n, len(closes)):
        tp_cur = (highs[i] + lows[i] + closes[i]) / 3
        tp_prev = (highs[i - 1] + lows[i - 1] + closes[i - 1]) / 3
        mf = tp_cur * volumes[i]
        if tp_cur > tp_prev:
            pos += mf
        elif tp_cur < tp_prev:
            neg += mf
    if neg == 0:
        return 100.0 if pos > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + pos / neg)


def volume_ratio(volumes: list[float], n: int = 5) -> float | None:
    """量比 = 最新成交量 / 近 n 日均量。"""
    if len(volumes) < n + 1:
        return None
    avg = sum(volumes[-(n + 1):-1]) / n
    return volumes[-1] / avg if avg else None


# ---------------------------------------------------------------------------
# 统计族
# ---------------------------------------------------------------------------


def position_in_range(highs: list[float], lows: list[float],
                      closes: list[float], n: int = 252) -> dict:
    """价格在近 n 日(默认 252≈52周)区间的位置百分比。

    Returns:
        {high, low, position(0-100), near_high: bool(距最高点<2%), near_low: bool}
    """
    window = min(n, len(closes))
    if window < 10:
        return {"high": None, "low": None, "position": None, "near_high": None, "near_low": None}
    hh = max(highs[-window:])
    ll = min(lows[-window:])
    if hh == ll:
        pos = 50.0
    else:
        pos = (closes[-1] - ll) / (hh - ll) * 100
    return {"high": hh, "low": ll, "position": pos,
            "near_high": (hh - closes[-1]) / hh < 0.02 if hh else None,
            "near_low": (closes[-1] - ll) / ll < 0.02 if ll else None}


def max_drawdown(closes: list[float]) -> float:
    """最大回撤(正的小数,如 0.35=35%)。"""
    peak = -float("inf")
    mdd = 0.0
    for c in closes:
        peak = max(peak, c)
        if peak > 0:
            mdd = max(mdd, (peak - c) / peak)
    return mdd


def daily_returns(closes: list[float]) -> list[float]:
    """日收益率序列(比输入少一个元素)。"""
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1]]


def beta(asset_rets: list[float], market_rets: list[float]) -> float | None:
    """Beta = cov(asset, market) / var(market)(基于同期日收益,需先按日期对齐)。"""
    n = min(len(asset_rets), len(market_rets))
    if n < 30:
        return None
    a = asset_rets[-n:]
    m = market_rets[-n:]
    ma, mm = sum(a) / n, sum(m) / n
    cov = sum((x - ma) * (y - mm) for x, y in zip(a, m)) / (n - 1)
    var = sum((y - mm) ** 2 for y in m) / (n - 1)
    return cov / var if var else None


def total_return(closes: list[float]) -> float:
    """区间累计收益率(%)。"""
    if len(closes) < 2 or not closes[0]:
        return 0.0
    return (closes[-1] / closes[0] - 1) * 100
