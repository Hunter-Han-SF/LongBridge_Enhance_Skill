"""longbridge-derivatives-pro 公共模块

提供:
  - find_longbridge_cli(): 探测 longbridge.exe 全路径
  - run_cli(): 调用 CLI 并解析 JSON,内置速率限制 + token 失效检测
  - check_env(): 环境预检(CLI + token),带 1 小时缓存
  - 数值字符串自动转换、表格输出、空数据判断等工具

设计对齐 futuapi skill 的 common.py,降低学习成本。
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# CLI 探测
# ---------------------------------------------------------------------------

# 常见安装位置(Windows 优先,也兼容 macOS/Linux)
_CANDIDATE_PATHS = [
    # Windows 单用户安装
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\longbridge\longbridge.exe"),
    # Windows 系统 Program Files
    r"C:\Program Files\longbridge\longbridge.exe",
    r"C:\Program Files (x86)\longbridge\longbridge.exe",
]

_CACHED_EXE: str | None = None


def find_longbridge_cli() -> str:
    """返回 longbridge 可执行文件全路径。找不到时抛 FileNotFoundError。"""
    global _CACHED_EXE
    if _CACHED_EXE:
        return _CACHED_EXE

    # 1. PATH 里找(跨平台)
    found = shutil.which("longbridge") or shutil.which("longbridge.exe")
    if found:
        _CACHED_EXE = found
        return found

    # 2. 候选路径
    for p in _CANDIDATE_PATHS:
        if p and os.path.isfile(p):
            _CACHED_EXE = p
            return p

    # 3. macOS .app
    if platform.system() == "Darwin":
        app_cli = "/Applications/Longbridge.app/Contents/MacOS/longbridge"
        if os.path.isfile(app_cli):
            _CACHED_EXE = app_cli
            return app_cli

    raise FileNotFoundError(
        "找不到 longbridge CLI。请安装 longbridge-terminal:\n"
        "  macOS/Linux: brew tap longbridge/tap && brew install longbridge/tap/longbridge-terminal\n"
        "  Windows: 从 https://longbridge.com/download 下载安装\n"
        "安装后若不在 PATH,本模块会自动探测常见安装目录。"
    )


# ---------------------------------------------------------------------------
# 速率限制(Longbridge: 1 秒最多 10 次,并发不超过 5)
# ---------------------------------------------------------------------------

_MIN_INTERVAL = 0.11  # ≈ 9 次/秒,留余量
_last_call_ts = 0.0


def _throttle() -> None:
    global _last_call_ts
    now = time.monotonic()
    wait = _MIN_INTERVAL - (now - _last_call_ts)
    if wait > 0:
        time.sleep(wait)
    _last_call_ts = time.monotonic()


# ---------------------------------------------------------------------------
# CLI 调用核心
# ---------------------------------------------------------------------------


class LongbridgeCliError(RuntimeError):
    """CLI 调用失败(非零退出、JSON 解析失败、token 失效等)。"""


def run_cli(
    *args: str,
    fmt: str = "json",
    check_auth: bool = True,
    retries: int = 2,
) -> Any:
    """调用 longbridge CLI,返回解析后的 Python 对象。

    Args:
        *args: CLI 子命令及参数,如 ("option", "chain", "AAPL.US", "--date", "2026-08-14")
        fmt: 输出格式,"json"(默认,返回解析后的对象)或 "raw"(返回原始 stdout 字符串)
        check_auth: 是否在 token 失效时提示重新登录
        retries: 遇到瞬时错误时的重试次数

    Returns:
        json 模式返回 dict/list/None;raw 模式返回字符串

    Raises:
        LongbridgeCliError: 调用失败
    """
    exe = find_longbridge_cli()
    full_args = [exe, *args]
    if fmt == "json" and "--format" not in args and "-o" not in args:
        full_args += ["--format", "json"]

    last_err: str | None = None
    for attempt in range(retries + 1):
        _throttle()
        try:
            proc = subprocess.run(
                full_args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            last_err = "CLI 超时(60s)"
            time.sleep(0.5 * (attempt + 1))
            continue

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""

        # token 失效检测
        if check_auth and _looks_like_auth_error(stdout + stderr):
            raise LongbridgeCliError(
                "Longbridge token 失效或未登录。请运行:\n"
                "  longbridge auth login"
            )

        if proc.returncode != 0:
            last_err = f"CLI 退出码 {proc.returncode}: {stderr.strip() or stdout.strip()}"
            # 限频类错误退避重试
            if "rate" in (stdout + stderr).lower() or "429" in (stdout + stderr):
                time.sleep(1.0 * (attempt + 1))
                continue
            raise LongbridgeCliError(last_err)

        if fmt == "raw":
            return stdout

        # JSON 解析
        stripped = stdout.strip()
        if not stripped:
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            # 有时 CLI 会把非 JSON 内容(进度条/警告)混在前面,尝试提取首个 JSON 结构
            for i, ch in enumerate(stripped):
                if ch in "[{":
                    try:
                        return json.loads(stripped[i:])
                    except json.JSONDecodeError:
                        break
            raise LongbridgeCliError(f"JSON 解析失败。stdout 前 200 字: {stripped[:200]!r}")

    raise LongbridgeCliError(f"重试 {retries} 次后仍失败: {last_err}")


def _looks_like_auth_error(text: str) -> bool:
    lower = text.lower()
    return any(
        kw in lower
        for kw in ("not logged in", "unauthorized", "token", "auth", "401", "access denied")
    ) and "valid" not in lower  # "Token Status: valid" 不是错误


# ---------------------------------------------------------------------------
# 环境预检(带缓存)
# ---------------------------------------------------------------------------

_ENV_CACHE = os.path.join(tempfile.gettempdir(), ".lbr_deriv_pro_env_ok")
_ENV_TTL = 3600  # 1 小时


def check_env(force: bool = False) -> dict[str, Any]:
    """检查 CLI 可用性 + token 状态。通过则写缓存文件,1 小时内跳过。

    Returns:
        {"cli": "...", "version": "...", "auth": "valid"/"invalid", "ok": bool}
    """
    if not force and os.path.isfile(_ENV_CACHE):
        if time.time() - os.path.getmtime(_ENV_CACHE) < _ENV_TTL:
            return {"cached": True, "ok": True}

    result: dict[str, Any] = {"ok": False}
    try:
        exe = find_longbridge_cli()
        result["cli"] = exe
    except FileNotFoundError as e:
        result["error"] = str(e)
        return result

    try:
        version_out = run_cli("--version", fmt="raw", check_auth=False, retries=0)
        result["version"] = version_out.strip()
    except LongbridgeCliError as e:
        result["error"] = f"无法执行 CLI: {e}"
        return result

    try:
        auth_out = run_cli("auth", "status", fmt="raw", check_auth=False, retries=0)
        result["auth"] = "valid" if "valid" in auth_out.lower() else "invalid"
        result["auth_detail"] = auth_out.strip()
    except LongbridgeCliError:
        result["auth"] = "unknown"

    result["ok"] = result.get("auth") == "valid"
    if result["ok"]:
        try:
            with open(_ENV_CACHE, "w", encoding="utf-8") as f:
                f.write(str(time.time()))
        except OSError:
            pass
    return result


# ---------------------------------------------------------------------------
# 数据类型转换工具(CLI 数值字段都是字符串)
# ---------------------------------------------------------------------------


def to_float(v: Any, default: float | None = None) -> float | None:
    """安全转 float。空值/无效值返回 default。"""
    if v is None or v == "" or v == "0" and default is not None:
        pass
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return f
    except (ValueError, TypeError):
        return default


def to_int(v: Any, default: int | None = None) -> int | None:
    f = to_float(v, None)
    if f is None:
        return default
    return int(f)


def normalize_records(data: Any) -> list[dict]:
    """把 CLI 返回的 list[dict] 里的数值字符串转成 float。返回新 list。"""
    if not data:
        return []
    if isinstance(data, dict):
        data = [data]
    out = []
    for row in data:
        if not isinstance(row, dict):
            continue
        new_row = {}
        for k, v in row.items():
            new_row[k] = _coerce(v)
        out.append(new_row)
    return out


_NUM_KEYS_HINT = {
    "strike", "last", "close", "open", "high", "low",
    "call_iv", "put_iv", "call_last", "put_last", "call_vol", "put_vol",
    "delta", "gamma", "theta", "vega", "rho",
    "implied_volatility", "open_interest", "volume",
    "c", "p", "call_vol", "put_vol",
    "total_call_volume", "total_put_volume", "total_volume",
    "total_call_open_interest", "total_put_open_interest", "total_open_interest",
    "put_call_volume_ratio", "put_call_open_interest_ratio",
}


def _coerce(v: Any) -> Any:
    if isinstance(v, str):
        # 尝试 float
        try:
            if "." in v or "e" in v.lower():
                return float(v)
            return int(v)
        except ValueError:
            return v
    if isinstance(v, dict):
        return {k: _coerce(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_coerce(x) for x in v]
    return v


# ---------------------------------------------------------------------------
# 空数据判断(对齐 futu common.is_empty)
# ---------------------------------------------------------------------------


def is_empty(data: Any) -> bool:
    if data is None:
        return True
    if isinstance(data, (list, dict, str)):
        return len(data) == 0
    return False


# ---------------------------------------------------------------------------
# 输出工具
# ---------------------------------------------------------------------------


def print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, default=str, indent=2))


def print_error(action: str, error: str, hint: str = "") -> None:
    """统一错误输出格式(对齐 futu 的 check_ret 错误格式)。"""
    out = {"action": action, "error": error}
    if hint:
        out["hint"] = hint
    print_json(out)


def print_display_table(rows: list[dict], columns: list[str] | None = None) -> None:
    """简易表格输出(终端友好)。rows 为空时打印提示。"""
    if not rows:
        print("无数据")
        return
    if columns is None:
        columns = list(rows[0].keys())
    # 计算列宽(兼容中文)
    def display_width(s: str) -> int:
        return sum(2 if ord(c) > 127 else 1 for c in str(s))

    widths = []
    for col in columns:
        w = display_width(col)
        for row in rows:
            w = max(w, display_width(str(row.get(col, ""))))
        widths.append(w)

    def pad(s: str, w: int) -> str:
        s = str(s)
        return s + " " * (w - display_width(s))

    # 表头
    header = " | ".join(pad(col, widths[i]) for i, col in enumerate(columns))
    sep = "-+-".join("-" * widths[i] for i in range(len(columns)))
    print(header)
    print(sep)
    for row in rows:
        print(" | ".join(pad(row.get(col, ""), widths[i]) for i, col in enumerate(columns)))


# ---------------------------------------------------------------------------
# 高频封装:B 档脚本共用
# ---------------------------------------------------------------------------


def get_kline(symbol: str, count: int = 60, period: str = "day") -> list[dict]:
    """拉取 K 线,返回 normalize 后的 list[{open,close,high,low,volume,time}]。"""
    data = run_cli("kline", symbol, "--period", period, "--count", str(count))
    return normalize_records(data)


def get_option_expirations(underlying: str) -> list[str]:
    """返回可用到期日列表 ['YYYY-MM-DD', ...]。"""
    data = run_cli("option", "chain", underlying)
    if is_empty(data):
        return []
    return [row["expiry_date"] for row in data if isinstance(row, dict) and "expiry_date" in row]


def get_option_chain(underlying: str, expiry: str) -> list[dict]:
    """返回某到期日的期权链(normalize 后,含 strike/call_iv/put_iv 等)。

    注意:Longbridge CLI 的 chain 不返回 OCC 代码(call_symbol/put_symbol),
    仅返回价格/IV/成交量。需要 OCC 代码时用 build_occ_code() 构造。
    """
    data = run_cli("option", "chain", underlying, "--date", expiry)
    return normalize_records(data)


def get_option_volume_daily(underlying: str, count: int = 20) -> list[dict]:
    """返回每日 P/C 比率 + 成交量/持仓量时间序列(仅美股)。"""
    data = run_cli("option", "volume", "daily", underlying, "--count", str(count))
    if is_empty(data) or not isinstance(data, dict):
        return []
    return normalize_records(data.get("stats", []))


def get_option_volume_realtime(underlying: str) -> dict:
    """返回实时 Call/Put 成交量快照 {call_volume, put_volume, pc_ratio}。"""
    data = run_cli("option", "volume", underlying)
    if is_empty(data) or not isinstance(data, dict):
        return {}
    c = to_float(data.get("c"), 0) or 0
    p = to_float(data.get("p"), 0) or 0
    pc = (p / c) if c > 0 else None
    return {"call_volume": c, "put_volume": p, "pc_ratio": pc}


# ---------------------------------------------------------------------------
# OCC 期权代码构造(chain 不返回 symbol 时的 fallback)
# ---------------------------------------------------------------------------


def build_occ_code(
    ticker: str,
    expiry: str,
    strike: float,
    option_type: str,
) -> str:
    """构造 OCC 期权代码。

    格式: <TICKER><YYMMDD><C|P><STRIKE×1000, 8位整数,不足前补0>
    例: AAPL 2026-09-18 strike 200.0 Call → AAPL260918C00200000

    Args:
        ticker: 正股代码(不含市场后缀),如 AAPL / TSLA
        expiry: YYYY-MM-DD
        strike: 行权价
        option_type: 'CALL'/'PUT'/'C'/'P'
    """
    ot = option_type.strip().upper()
    if ot in ("CALL", "C"):
        cp = "C"
    elif ot in ("PUT", "P"):
        cp = "P"
    else:
        raise ValueError(f"option_type 必须是 CALL/PUT/C/P,收到 {option_type!r}")

    yy = expiry[2:4]
    mm = expiry[5:7]
    dd = expiry[8:10]
    strike_int = int(round(strike * 1000))
    return f"{ticker.upper()}{yy}{mm}{dd}{cp}{strike_int:08d}"


def parse_underlying(symbol: str) -> tuple[str, str]:
    """'AAPL.US' → ('AAPL', 'US')。无后缀时尝试推断。"""
    if "." in symbol:
        ticker, market = symbol.rsplit(".", 1)
        return ticker.upper(), market.upper()
    return symbol.upper(), "US"


# ---------------------------------------------------------------------------
# B 档计算工具(Black-Scholes / HV / ATM 定位)
# ---------------------------------------------------------------------------
# Longbridge 的 IV 字段是小数形式(0.214 = 21.4%),与 Futu 的百分比形式不同。
# 本模块统一用小数形式,输出时再转百分比。

import math


def calc_hv(closes: list[float], annualize: int = 252) -> float | None:
    """计算历史波动率(年化)。

    HV = std(ln(close_i / close_{i-1})) × √annualize

    Args:
        closes: 收盘价序列(按时间正序,旧→新)
        annualize: 年化因子,美股 252

    Returns:
        年化 HV(小数形式,如 0.23 = 23%),数据不足返回 None
    """
    if len(closes) < 2:
        return None
    log_rets = []
    for i in range(1, len(closes)):
        prev, cur = closes[i - 1], closes[i]
        if prev > 0 and cur > 0:
            log_rets.append(math.log(cur / prev))
    if len(log_rets) < 2:
        return None
    mean = sum(log_rets) / len(log_rets)
    var = sum((r - mean) ** 2 for r in log_rets) / (len(log_rets) - 1)
    return math.sqrt(var) * math.sqrt(annualize)


def find_atm_strike(chain: list[dict], underlying_price: float) -> float | None:
    """从 chain 中找最接近现价的行权价(ATM)。"""
    best = None
    best_diff = float("inf")
    for row in chain:
        s = to_float(row.get("strike"))
        if s is None:
            continue
        diff = abs(s - underlying_price)
        if diff < best_diff:
            best_diff = diff
            best = s
    return best


def get_underlying_price(symbol: str) -> float | None:
    """获取正股最新价。"""
    data = run_cli("quote", symbol)
    if is_empty(data) or not isinstance(data, list):
        return None
    if not data:
        return None
    return to_float(data[0].get("last"))


def get_atm_iv(chain: list[dict], underlying_price: float, option_type: str = "CALL") -> float | None:
    """从 chain 提取 ATM 合约的 IV。

    option_type: 'CALL' 或 'PUT'。ATM 附近 call/put IV 应接近(put-call parity),
    默认用 CALL。
    """
    atm = find_atm_strike(chain, underlying_price)
    if atm is None:
        return None
    key = "call_iv" if option_type.upper() in ("CALL", "C") else "put_iv"
    for row in chain:
        s = to_float(row.get("strike"))
        if s is not None and abs(s - atm) < 0.001:
            return to_float(row.get(key))
    return None


# ---- Black-Scholes(当 option quote 拿不到 Greeks 时的 fallback) ----
# 标准正态分布的 PDF 与 CDF(不依赖 scipy)


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def _norm_cdf(x: float) -> float:
    """标准正态 CDF,用 math.erf 精确实现(误差 0,非近似)。"""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_price(S: float, K: float, T: float, r: float, sigma: float, cp: str = "C") -> float:
    """Black-Scholes 期权理论价。

    Args:
        S: 标的现价
        K: 行权价
        T: 剩余时间(年),到期日按 365 日折算
        r: 无风险利率(小数,如 0.045)
        sigma: 波动率(小数,如 0.23)
        cp: 'C' Call / 'P' Put
    """
    if T <= 0 or sigma <= 0:
        intrinsic = max(S - K, 0) if cp == "C" else max(K - S, 0)
        return intrinsic
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if cp == "C":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def bs_greeks(S: float, K: float, T: float, r: float, sigma: float, cp: str = "C") -> dict:
    """计算 BS 全套 Greeks。

    Returns:
        {delta, gamma, theta, vega, rho}(theta/vega 已换算为常用单位:
        theta 为每日,vega 为每 1% 波动率变化)
    """
    if T <= 0 or sigma <= 0:
        delta = 1.0 if (cp == "C" and S > K) else (0.0 if cp == "C" else (-1.0 if S < K else 0.0))
        return {"delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    pdf_d1 = _norm_pdf(d1)

    gamma = pdf_d1 / (S * sigma * math.sqrt(T))
    vega = S * pdf_d1 * math.sqrt(T) / 100  # 每 1% IV 变化

    if cp == "C":
        delta = _norm_cdf(d1)
        theta = (-(S * pdf_d1 * sigma) / (2 * math.sqrt(T))
                 - r * K * math.exp(-r * T) * _norm_cdf(d2)) / 365
        rho = K * T * math.exp(-r * T) * _norm_cdf(d2) / 100
    else:
        delta = _norm_cdf(d1) - 1
        theta = (-(S * pdf_d1 * sigma) / (2 * math.sqrt(T))
                 + r * K * math.exp(-r * T) * _norm_cdf(-d2)) / 365
        rho = -K * T * math.exp(-r * T) * _norm_cdf(-d2) / 100

    # rho 原始值表示"利率每变化 1.0(100%) 的价格变化",业界习惯转成"每 1%(0.01)"。
    # 上面公式已除以 100,得到的是每 1% 利率变化的价格变动(标准约定)。

    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega, "rho": rho}


def days_to_years(expiry: str, today: str | None = None) -> float:
    """到期日剩余时间(年)。expiry/today 格式 YYYY-MM-DD。"""
    from datetime import datetime as _dt
    t = _dt.strptime(today or _dt.now().strftime("%Y-%m-%d"), "%Y-%m-%d")
    e = _dt.strptime(expiry, "%Y-%m-%d")
    return max((e - t).days, 0) / 365.0


# ---------------------------------------------------------------------------
# 主入口:环境自检(被 import 时不触发,仅在直接运行 check_env.py 时)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print_json(check_env(force=True))
