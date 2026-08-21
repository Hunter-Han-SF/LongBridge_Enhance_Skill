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

        if proc.returncode != 0:
            # token 失效检测(仅在 CLI 报错时触发,避免成功返回的数据内容里
            # 出现 "access denied" 等字面量被误判为 token 失效)
            if check_auth and _looks_like_auth_error(stdout + stderr):
                raise LongbridgeCliError(
                    "Longbridge token 失效或未登录。请运行:\n"
                    "  longbridge auth login"
                )
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
            # 整体不是 JSON:可能 token 失效时 CLI 以退出码 0 输出错误文本
            if check_auth and _looks_like_auth_error(stripped):
                raise LongbridgeCliError(
                    "Longbridge token 失效或未登录。请运行:\n"
                    "  longbridge auth login"
                )
            raise LongbridgeCliError(f"JSON 解析失败。stdout 前 200 字: {stripped[:200]!r}")

    raise LongbridgeCliError(f"重试 {retries} 次后仍失败: {last_err}")


def _looks_like_auth_error(text: str) -> bool:
    """检测 CLI 输出是否像 token 失效。

    ⚠️ 不能用纯子串匹配:数据值里可能含 "401"(如 balance="30617440165")、
       "auth"(如 author 字段)等。改用带边界的短语匹配 + 仅在 CLI 报错(非 JSON 数据)时触发。
    """
    lower = text.lower()
    # 这些短语在真实错误信息里作为独立词出现,不会误命中数值/字段名
    strong_signals = (
        "not logged in", "unauthorized", "access denied",
        "login required", "please login", "please log in",
        "authentication failed", "authenticat",  # authenticate/authentication
        "invalid token", "token expired", "token is invalid", "no token",
    )
    for sig in strong_signals:
        if sig in lower:
            return True
    # "401"/"token" 单独出现不可靠,必须伴随明确的 HTTP 错误上下文。
    # ⚠️ "status" 不能作为上下文 —— quote 返回里有合法的 "status":"Normal" 字段。
    if "401" in lower and any(w in lower for w in ("unauthorized", "forbidden", "http error")):
        return True
    # "Token Status: ..." 行:注意 "invalid" 含子串 "valid",必须先判 invalid
    if "token status" in lower:
        return "invalid" in lower
    return False


# ---------------------------------------------------------------------------
# 环境预检(带缓存)
# ---------------------------------------------------------------------------

# 环境自检缓存放在用户主目录(固定文件名,不含任何动态拼接)
_ENV_CACHE = os.path.join(os.path.expanduser("~"), ".lbr_deriv_pro_env_ok")
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
        lower = auth_out.lower()
        # ⚠️ "invalid" 包含子串 "valid",必须先判失效信号,否则失效 token 会被误判为有效
        if any(sig in lower for sig in ("invalid", "expired", "not logged in", "unauthorized")):
            result["auth"] = "invalid"
        elif "valid" in lower:
            result["auth"] = "valid"
        else:
            result["auth"] = "invalid"
        result["auth_detail"] = auth_out.strip()
    except LongbridgeCliError:
        result["auth"] = "unknown"

    result["ok"] = result.get("auth") == "valid"
    if result["ok"]:
        try:
            # pathlib 写汇 + 固定文件名(主目录常量,不含动态拼接)
            import pathlib as _pl
            _pl.Path(_ENV_CACHE).write_text(str(time.time()), encoding="utf-8")
        except OSError:
            pass
    return result


# ---------------------------------------------------------------------------
# 数据类型转换工具(CLI 数值字段都是字符串)
# ---------------------------------------------------------------------------


def to_float(v: Any, default: float | None = None) -> float | None:
    """安全转 float。空值/无效值返回 default。"""
    if v is None or v == "":
        return default
    try:
        return float(v)
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
    """返回可用到期日列表 ['YYYY-MM-DD', ...](已过滤今天之前的过期日期)。

    实测 chain 返回的列表头部会带最近已到期的合约(如今天 08-20 仍返回 08-14/17/19),
    默认取 expirations[0] 的脚本会因此用过期数据,必须过滤。
    """
    data = run_cli("option", "chain", underlying)
    if is_empty(data):
        return []
    from datetime import datetime as _dt
    today = _dt.now().strftime("%Y-%m-%d")
    return [row["expiry_date"] for row in data
            if isinstance(row, dict) and row.get("expiry_date")
            and row["expiry_date"] >= today]


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


# ===========================================================================
# 多维度增强模块公共封装(异动 / 资金流 / 日历 / 情绪)
# ===========================================================================
# 以下函数对应 Longbridge CLI 的扁平命令(非文档的 REST 路径)。
# 已实测返回结构,字段名以真实输出为准(详见 references/new-modules-map.md)。


# ---- 工具:counter_id → 标准 symbol ----

# Longbridge 的异动/排行用 counter_id 标的,如 "ST/US/DASH"、"ETF/US/SPCH"。
# 各市场后缀不同,这里统一转成 "CODE.MARKET" 形式。
_COUNTER_MARKET_MAP = {
    "US": "US", "HK": "HK", "SH": "SH", "SZ": "SZ",
    "SG": "SG", "CN": "CN", "JP": "JP", "UK": "UK",
    "DE": "DE", "AU": "AU",
}


def counter_id_to_symbol(counter_id: str) -> str | None:
    """'ST/US/DASH' → 'DASH.US'。无法识别返回 None。

    支持格式: <类型>/<市场>/<代码>,如 ST/US/AAPL、ETF/HK/02800、WARRANT/HK/12345。
    """
    if not counter_id or not isinstance(counter_id, str):
        return None
    parts = counter_id.split("/")
    if len(parts) < 3:
        return None
    market = parts[-2].upper()
    code = parts[-1]
    suffix = _COUNTER_MARKET_MAP.get(market)
    if not suffix:
        return None
    return f"{code}.{suffix}"


# ---- 模块①异动追踪 ----

def get_anomaly(market: str = "HK", symbol: str | None = None, count: int = 50) -> dict:
    """获取异动信号(大单买卖/封板/放量等)。

    Args:
        market: HK | US | CN | SG
        symbol: 过滤特定标的(可选,需完整 symbol 如 AAPL.US)
        count: 返回条数(≤100)

    Returns:
        {all_off: bool, changes: [{alert_name, alert_type, emotion, counter_id,
                                   name, change_values, alert_time, ...}]}
        emotion: 1=利多, 2=利空
    """
    args = ["anomaly", "--market", market, "--count", str(count)]
    if symbol:
        args += ["--symbol", symbol]
    data = run_cli(*args)
    if is_empty(data) or not isinstance(data, dict):
        return {"all_off": True, "changes": []}
    return {
        "all_off": bool(data.get("all_off", False)),
        "changes": normalize_records(data.get("changes", [])),
    }


def get_top_movers(market: str | None = None, sort: str = "hot", count: int = 20) -> dict:
    """获取涨跌异动榜(含关联新闻)。

    Args:
        market: HK | US | CN | SG(传 None 表示全部市场)
        sort: hot | time | change
        count: 返回条数

    Returns:
        {events: [{alert_reason, alert_type, counter_id, post:{新闻对象}, ...}],
         next_params: dict/None, updated_at: str}
    """
    args = ["top-movers", "--sort", sort, "--count", str(count)]
    if market:
        args += ["--market", market]
    data = run_cli(*args)
    if is_empty(data) or not isinstance(data, dict):
        return {"events": [], "next_params": None, "updated_at": None}
    return {
        "events": normalize_records(data.get("events", [])),
        "next_params": data.get("next_params"),
        "updated_at": data.get("updated_at"),
    }


# ---- 模块③主力资金流 ----

def get_capital_flow_snapshot(symbol: str) -> dict:
    """获取日内大/中/小单资金分布快照。

    ⚠️ CLI 原始单位是"万"(实测:AAPL 原始值合计×1e4 ≈ 当日成交额的 20%;
       若按"元"解释则仅 0.002%,不合常理)。本函数统一 ×1e4 换算成
       当地货币完整单位(美股=美元,港股=港元)。

    Returns:
        {symbol, timestamp, capital_in:{large,medium,small},
         capital_out:{large,medium,small},
         net:{large,medium,small,total}, unit_note}(净额=流入-流出)
    """
    data = run_cli("capital", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return {}
    cap_in = data.get("capital_in", {}) or {}
    cap_out = data.get("capital_out", {}) or {}
    # 换算单位("万" → 完整货币单位)并算净流入
    def _conv(d: dict) -> dict:
        return {k: (to_float(d.get(k), 0) or 0) * 1e4
                for k in ("large", "medium", "small")}
    cap_in_c, cap_out_c = _conv(cap_in), _conv(cap_out)
    net = {k: round(cap_in_c[k] - cap_out_c[k], 2) for k in ("large", "medium", "small")}
    net["total"] = round(sum(net.values()), 2)
    return {
        "symbol": data.get("symbol", symbol),
        "timestamp": data.get("timestamp"),
        "capital_in": cap_in_c,
        "capital_out": cap_out_c,
        "net": net,
        "unit_note": "CLI 原始单位为万,已 ×1e4 换算为当地货币完整单位(US=USD / HK=HKD)",
    }


def get_capital_flow_series(symbol: str) -> list[dict]:
    """获取日内分钟级资金净流入时序。

    ⚠️ CLI 的 inflow 字段是"当日累计净流入"而非每分钟增量
       (实测:391 个点的末值与快照 net.total 完全一致)。
       本函数 ×1e4 换算为当地货币完整单位(CLI 原始单位为万),
       并附 minute_delta 字段(相邻分钟的增量)。

    Returns:
        [{inflow: 当日累计净流入(完整货币单位), minute_delta: 该分钟增量, time, ...}]
    """
    data = run_cli("capital", symbol, "--flow")
    if is_empty(data) or not isinstance(data, list):
        return []
    rows = normalize_records(data)
    prev = 0.0
    for r in rows:
        v = to_float(r.get("inflow"))
        cur = v * 1e4 if v is not None else None
        r["inflow"] = cur
        r["minute_delta"] = round(cur - prev, 2) if cur is not None else None
        if cur is not None:
            prev = cur
    return rows


def get_broker_holding_top(symbol: str, period: str = "rct_1") -> dict:
    """港股经纪商 top10 买/卖(⚠️仅港股)。

    Args:
        symbol: 如 700.HK
        period: rct_1 | rct_5 | rct_20 | rct_60(近1/5/20/60日)

    Returns:
        {buy:[{name, parti_number, chg, strong}], sell:[...], updated_at}
    """
    data = run_cli("broker-holding", symbol, "--period", period)
    if is_empty(data) or not isinstance(data, dict):
        return {"buy": [], "sell": [], "updated_at": None}
    return {
        "buy": normalize_records(data.get("buy", [])),
        "sell": normalize_records(data.get("sell", [])),
        "updated_at": data.get("updated_at"),
    }


def get_broker_holding_detail(symbol: str) -> dict:
    """港股经纪商全量持仓明细(含 1/5/20/60 日变动)。

    Returns:
        {list:[{name, parti_number, strong, ratio:{value,chg_1,...}, shares:{...}}],
         updated_at}
    """
    data = run_cli("broker-holding", "detail", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return {"list": [], "updated_at": None}
    return {
        "list": normalize_records(data.get("list", [])),
        "updated_at": data.get("updated_at"),
    }


def get_short_trades(symbol: str, count: int = 20) -> dict:
    """每日沽空成交量比率时序。

    美股字段: nus_amount/ny_amount/total_amount/rate/close
    港股字段: amount/balance/total_amount/rate/close

    Returns:
        {symbol, sources, data:[{...}], market: 'US'|'HK'(自动推断)}
    """
    data = run_cli("short-trades", symbol, "--count", str(count))
    if is_empty(data) or not isinstance(data, dict):
        return {"symbol": symbol, "data": [], "sources": None, "market": None}
    rows = normalize_records(data.get("data", []))
    market = "US" if rows and "nus_amount" in rows[0] else ("HK" if rows else None)
    return {"symbol": data.get("symbol", symbol), "sources": data.get("sources"),
            "data": rows, "market": market}


def get_short_positions(symbol: str, count: int = 20) -> dict:
    """沽空持仓(未平仓量)时序。

    美股字段(双周FINRA): current_shares_short/rate/days_to_cover/close
        ⚠️文档说 short_interest,实际字段名是 current_shares_short
    港股字段(日频HKEX): amount/balance/cost/rate/close

    Returns:
        {symbol, sources, data:[{...}], market, update_timestamp}
    """
    data = run_cli("short-positions", symbol, "--count", str(count))
    if is_empty(data) or not isinstance(data, dict):
        return {"symbol": symbol, "data": [], "sources": None,
                "market": None, "update_timestamp": None}
    rows = normalize_records(data.get("data", []))
    market = "US" if rows and "current_shares_short" in rows[0] else ("HK" if rows else None)
    return {"symbol": data.get("symbol", symbol), "sources": data.get("sources"),
            "data": rows, "market": market,
            "update_timestamp": data.get("update_timestamp")}


# ---- 模块④事件日历 ----

def get_finance_calendar(
    category: str = "report",
    market: str | None = None,
    symbol: str | list[str] | None = None,
    filter: str | None = None,
    start: str | None = None,
    end: str | None = None,
    count: int = 100,
) -> list[dict]:
    """获取事件日历(财报/分红/分拆/IPO/宏观)。

    Args:
        category: report | dividend | split | ipo | macrodata | closed
        market: HK|US|CN|SG|JP|UK|DE|AU(传 None 表示全部)
        symbol: 单个或列表(最多 10 个,传 symbol 会过滤到这些标的)
        filter: 'watchlist' 或 'positions'(与 symbol 互斥,过滤到自选/持仓)
        start/end: YYYY-MM-DD
        count: 返回条数

    Returns:
        [{date, count, infos:[{counter_id, counter_name, date, date_type,
           content, data_kv:[{type,value,value_raw}], ext:{...}}]}]
    """
    args = ["finance-calendar", category]
    if market:
        args += ["--market", market]
    if isinstance(symbol, str):
        args += ["--symbol", symbol]
    elif isinstance(symbol, list):
        for s in symbol[:10]:
            args += ["--symbol", s]
    if filter:
        args += ["--filter", filter]
    if start:
        args += ["--start", start]
    if end:
        args += ["--end", end]
    args += ["--count", str(count)]
    data = run_cli(*args)
    if is_empty(data) or not isinstance(data, dict):
        return []
    buckets = data.get("list", []) or []
    out = []
    for b in buckets:
        if not isinstance(b, dict):
            continue
        out.append({
            "date": b.get("date"),
            "count": b.get("count", 0),
            "infos": normalize_records(b.get("infos", [])),
        })
    return out


# ---- 模块⑤市场情绪 ----

def get_market_temp(market: str = "HK", history: bool = False,
                    start: str | None = None, end: str | None = None) -> dict | list[dict]:
    """市场温度指数(0-100,越高越乐观)。

    Args:
        market: HK | US | CN | SG
        history: True 返回时序(需配合 start/end),False 返回当前快照
        start/end: YYYY-MM-DD(仅 history 模式)

    Returns:
        快照模式: {market, temperature, description, valuation, sentiment}
        时序模式: [{date, temperature, valuation, sentiment, description}, ...]
    """
    args = ["market-temp", market]
    if history:
        args += ["--history"]
        if start:
            args += ["--start", start]
        if end:
            args += ["--end", end]
    data = run_cli(*args)
    if is_empty(data):
        return {} if not history else []

    # CLI 返回 [{field, value}, ...] 键值对形式,展平成 dict
    def _flatten(rows):
        out = {}
        for r in rows:
            if isinstance(r, dict) and "field" in r:
                out[str(r["field"]).lower()] = r.get("value")
        return out

    if history and isinstance(data, list):
        # 时序:每条记录是一组 field/value,带 date
        result = []
        for row in data:
            flat = _flatten(row) if isinstance(row, list) else (
                row if isinstance(row, dict) else {})
            result.append(flat)
        return result
    # 快照
    if isinstance(data, list):
        flat = _flatten(data)
        return {
            "market": flat.get("market", market),
            "temperature": to_float(flat.get("temperature")),
            "description": flat.get("description"),
            "valuation": to_float(flat.get("valuation")),
            "sentiment": to_float(flat.get("sentiment")),
        }
    return data


def get_heat_rank_keys(market: str = "US") -> list[dict]:
    """列出所有可用的热度榜 tab(先列 key 再拉具体榜)。

    Returns:
        [{key, market, name}, ...] 如 {key:'hot_all-us', market:'US', name:'总热度'}
    """
    data = run_cli("rank", "--market", market)
    if is_empty(data) or not isinstance(data, list):
        return []
    return normalize_records(data)


def get_heat_rank(key: str, count: int = 20) -> dict:
    """拉具体热度榜。

    Args:
        key: 来自 get_heat_rank_keys 的 key,如 'hot_all-us'
        count: 返回条数

    Returns:
        {bmp, updated_at, lists:[{symbol, name, last_done, chg, inflow, balance,
           volume_rate, five_day_chg, ...}]}(lists 是完整 quote+heat 对象)
    """
    data = run_cli("rank", "--key", key, "--count", str(count))
    if is_empty(data) or not isinstance(data, dict):
        return {"bmp": None, "updated_at": None, "lists": []}
    return {
        "bmp": data.get("bmp"),
        "updated_at": data.get("updated_at"),
        "lists": normalize_records(data.get("lists", [])),
    }


# ===========================================================================
# 增强模块公共封装(技术面 / 基本面 / 日内微观 / 期权补充)
# ===========================================================================
# 以下对应 Longbridge CLI 的扁平命令,字段结构均实测验证(2026-08,CLI 0.26.0)。


# ---- 日内微观(intraday / depth / trades) ----

def get_intraday(symbol: str, date: str | None = None, session: str = "intraday") -> list[dict]:
    """分钟线(自带 VWAP)。

    Returns:
        [{time, price, avg_price(即 VWAP), volume, turnover}, ...](按时间升序)
    """
    args = ["intraday", symbol, "--session", session]
    if date:
        args += ["--date", date]  # YYYYMMDD
    data = run_cli(*args)
    if is_empty(data) or not isinstance(data, list):
        return []
    return normalize_records(data)


def get_depth(symbol: str) -> dict:
    """L2 盘口买卖梯子。asks 按价格降序(卖一在前),bids 按价格降序(买一在前)。"""
    data = run_cli("depth", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return {"asks": [], "bids": []}
    return {
        "asks": normalize_records(data.get("asks", [])),
        "bids": normalize_records(data.get("bids", [])),
    }


def get_trades(symbol: str, count: int = 200) -> list[dict]:
    """最近逐笔成交(按时间倒序,最新在前)。

    direction: 'Up'=主动买(买方推动),'Down'=主动卖,'Flat'=平。
    """
    data = run_cli("trades", symbol, "--count", str(min(count, 1000)))
    if is_empty(data) or not isinstance(data, list):
        return []
    return normalize_records(data)


# ---- 基本面(valuation / rating / forecast / financial-report / dividend) ----

def get_valuation(symbol: str) -> dict:
    """估值分析:当前估值 + 5 年历史序列 + 行业同行对比。

    Returns:
        {overview: {metrics: {pe: {desc, circle...}, ...}},
         history: {metrics: {pe: {list: [{timestamp, value}], median, high, low}}},
         peers: {pe: {industry_median, list: [{counter_id, name, value}]}}}
        实测美股常见只有 pe;部分标的有 pb/ps 等,按实际返回的 metric 处理。
    """
    data = run_cli("valuation", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return {}
    return data


def get_institution_rating(symbol: str) -> dict:
    """机构/分析师评级。

    Returns:
        {analyst: {evaluate: {buy, over, hold, under, sell, no_opinion, total},
                   target: {highest_price, lowest_price, prev_close},
                   industry_name, industry_rank, industry_total},
         instratings: {...评级变动}}
    """
    data = run_cli("institution-rating", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return {}
    return data


def get_forecast_eps(symbol: str) -> list[dict]:
    """EPS 预测(分析师共识,按报告期)。

    Returns:
        [{forecast_eps_mean, forecast_eps_highest, forecast_eps_lowest,
          forecast_eps_median, forecast_start_date, forecast_end_date,
          institution_up, institution_down, institution_total}]
    """
    data = run_cli("forecast-eps", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return []
    return normalize_records(data.get("items", []))


def get_financial_report(symbol: str) -> dict:
    """三大报表关键指标(利润 IS / 资产负债 BS / 现金流 CF),含行业排名。

    Returns:
        {list: {IS: {indicators: [{accounts: [{name, ranking_code, ratio,
           values: [{period, year, value, yoy}]}]}]}, BS: ..., CF: ...}}
    """
    data = run_cli("financial-report", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return {}
    return data


def get_dividend_history(symbol: str) -> list[dict]:
    """分红历史(按除息日倒序)。

    Returns:
        [{symbol, ex_date('2026.08.10'), record_date, payment_date,
          desc('每股派息 0.27 USD'), amount, currency}](amount/currency 由 desc 解析)
    """
    data = run_cli("dividend", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return []
    rows = normalize_records(data.get("list", []))
    import re as _re
    for r in rows:
        m = _re.search(r"([\d.]+)\s*([A-Za-z]+)", str(r.get("desc", "")))
        if m:
            r["amount"] = to_float(m.group(1))
            r["currency"] = m.group(2).upper()
    return rows


# ---- K 线辅助 ----

def get_kline_adjusted(symbol: str, count: int = 260, period: str = "day") -> list[dict]:
    """前复权 K 线(--adjust forward),技术指标计算专用,避免除权跳空污染均线。"""
    data = run_cli("kline", symbol, "--period", period, "--count", str(count),
                   "--adjust", "forward")
    return normalize_records(data)


# ---- 期权合约级指标(calc-index:真实 OI + 服务端原生 Greeks) ----
# 实测(2026-08,CLI 0.26.0):calc-index 支持按单个期权合约查询 oi/iv/delta/gamma/
# theta/vega/rho/strike/exp/last_done,支持一次传多个合约(不存在的静默跳过)。
# 这是 chain 之外唯一的按行权价 OI 数据源,Wall/GEX/MaxPain/P-C OI 比率据此升级为真 OI 口径。

_LBR_OPTION_CACHE: dict[str, dict] = {}


def build_lbr_option_symbol(ticker: str, expiry: str, strike: float, option_type: str) -> str:
    """构造 Longbridge calc-index 使用的期权代码。

    ⚠️ 与 OCC 标准不同:行权价×1000 后不补零。
    例: MSFT 2026-08-21 485.0 Call → MSFT260821C485000.US(OCC 则是 MSFT260821C00485000)
    """
    ot = option_type.strip().upper()
    cp = "C" if ot in ("CALL", "C") else ("P" if ot in ("PUT", "P") else None)
    if cp is None:
        raise ValueError(f"option_type 必须是 CALL/PUT/C/P,收到 {option_type!r}")
    return f"{ticker.upper()}{expiry[2:4]}{expiry[5:7]}{expiry[8:10]}{cp}{int(round(strike * 1000))}.US"


def get_option_contract_metrics(
    contracts: list[str],
    fields: str = "oi,iv,delta,gamma,theta,vega,rho,strike,exp,last_done",
    batch_size: int = 10,
    use_cache: bool = True,
) -> dict[str, dict]:
    """批量查询期权合约的 OI / 原生 Greeks / IV。

    Args:
        contracts: build_lbr_option_symbol 构造的合约代码列表
        batch_size: 每次 calc-index 调用携带的合约数(实测多合约单调用可行)
        use_cache: 同进程内相同合约复用结果(进程级缓存)

    Returns:
        {合约代码: {oi:int, iv:小数, delta, gamma, theta, vega, rho, strike, exp, last_done}}
        无数据的合约不在返回 dict 中。iv 已从 "22.40%" 归一化为 0.224。
    """
    out: dict[str, dict] = {}
    todo = []
    for c in contracts:
        if use_cache and c in _LBR_OPTION_CACHE:
            out[c] = _LBR_OPTION_CACHE[c]
        else:
            todo.append(c)
    for i in range(0, len(todo), batch_size):
        chunk = todo[i:i + batch_size]
        data = run_cli("calc-index", *chunk, "--fields", fields)
        rows = data if isinstance(data, list) else []
        for r in normalize_records(rows):
            sym = r.get("symbol")
            if not sym:
                continue
            iv = r.get("iv")
            if isinstance(iv, str):
                is_pct = iv.endswith("%")
                f = to_float(iv[:-1] if is_pct else iv)
                if f is not None:
                    r["iv"] = f / 100 if is_pct else f
            if use_cache:
                _LBR_OPTION_CACHE[sym] = r
            out[sym] = r
    return out


def get_chain_oi(underlying: str, expiry: str, near_atm_pct: float = 0.25,
                 max_strikes: int = 60) -> dict:
    """按行权价拉取整条链的 call/put OI + 原生 Greeks(用于 Wall/GEX/MaxPain/P-C OI)。

    只查询现价 ±near_atm_pct 范围内、离 ATM 最近的 max_strikes 个行权价
    (控制 calc-index 调用量;限频 10 次/秒,60 档 × 2 边 = 12 次调用)。

    Returns:
        {oi_mode: bool, strikes: {strike: {call_oi, put_oi, call_iv, put_iv,
         call_gamma, put_gamma, call_delta, put_delta}},
         total_call_oi, total_put_oi, pc_oi_ratio, strikes_queried}
        oi_mode=False 表示拿不到 OI(调用方应回退成交量代理)。
    """
    chain = get_option_chain(underlying, expiry)
    price = get_underlying_price(underlying)
    ticker, _ = parse_underlying(underlying)
    strikes = sorted({to_float(r.get("strike")) for r in chain if to_float(r.get("strike"))})
    if not strikes:
        return {"oi_mode": False, "strikes": {}}
    if price:
        strikes = [s for s in strikes if abs(s - price) / price <= near_atm_pct]
    if len(strikes) > max_strikes:
        strikes = sorted(strikes, key=lambda s: abs(s - (price or strikes[0])))[:max_strikes]
        strikes.sort()

    contracts = []
    for s in strikes:
        contracts.append(build_lbr_option_symbol(ticker, expiry, s, "CALL"))
        contracts.append(build_lbr_option_symbol(ticker, expiry, s, "PUT"))
    metrics = get_option_contract_metrics(contracts, fields="oi,iv,delta,gamma")

    strike_map: dict[float, dict] = {}
    total_c = total_p = 0
    for s in strikes:
        cm = metrics.get(build_lbr_option_symbol(ticker, expiry, s, "CALL"), {})
        pm = metrics.get(build_lbr_option_symbol(ticker, expiry, s, "PUT"), {})
        c_oi = to_int(cm.get("oi")) or 0
        p_oi = to_int(pm.get("oi")) or 0
        strike_map[s] = {
            "call_oi": c_oi, "put_oi": p_oi,
            "call_iv": to_float(cm.get("iv")), "put_iv": to_float(pm.get("iv")),
            "call_gamma": to_float(cm.get("gamma")), "put_gamma": to_float(pm.get("gamma")),
            "call_delta": to_float(cm.get("delta")), "put_delta": to_float(pm.get("delta")),
        }
        total_c += c_oi
        total_p += p_oi
    has_oi = any(v["call_oi"] or v["put_oi"] for v in strike_map.values())
    return {
        "oi_mode": has_oi,
        "strikes": strike_map,
        "total_call_oi": total_c,
        "total_put_oi": total_p,
        "pc_oi_ratio": round(total_p / total_c, 3) if total_c else None,
        "strikes_queried": len(strikes),
    }


# ===========================================================================
# v0.4.0 新增封装(warrant / screener / brokers / ipo / macrodata / quant /
# compare / 行业 / 公司 / 内部人与机构 / 成分股 / trade-stats / ah-premium)
# ===========================================================================
# 字段结构均实测验证(2026-08-21,CLI 0.26.0),详见 references/new-modules-map.md。


# ---- 模块①补充:港股涡轮(warrant,仅 HK) ----

def get_warrant_list(underlying: str) -> list[dict]:
    """列出正股的全部涡轮/权证(⚠️仅港股)。

    Returns:
        [{symbol('61304.HK'), name('UB#TENCTRP2808D'), type, expiry('2028-08-02'),
          last, leverage_ratio}]
        ⚠️ 实测坑:list 的 type 字段不可信(700.HK 返回 712 条里 61304 标 Call,
        quote 却返回 Bear)。真实方向以 warrant quote 的 type 为准。
    """
    data = run_cli("warrant", underlying)
    return normalize_records(data) if isinstance(data, list) else []


def get_warrant_quote(symbols: str | list[str]) -> list[dict]:
    """涡轮合约实时报价(支持一次多个)。

    Returns:
        [{symbol, type, expiry, last, prev_close, implied_vol(小数,实测常见 0.000=无数据)}]
        ⚠️ type 词汇混用:'Call'/'Bull'=认购,'Bear'/'Put'=认沽(同一命令两种都见过)。
    """
    if isinstance(symbols, str):
        symbols = [symbols]
    data = run_cli("warrant", "quote", *symbols)
    return normalize_records(data) if isinstance(data, list) else []


def get_warrant_issuers() -> list[dict]:
    """涡轮发行商列表(HK)。[{id('8'), name_cn('法兴'), name_en('SG')}]"""
    data = run_cli("warrant", "issuers")
    return normalize_records(data) if isinstance(data, list) else []


# ---- 模块⑩选股器(screener) ----

def get_screener_strategies() -> list[dict]:
    """预设选股策略列表。[{id, name('低估值'), type('platform')}]"""
    data = run_cli("screener", "strategies")
    return normalize_records(data) if isinstance(data, list) else []


def run_screener_strategy(strategy_id: int) -> list[dict]:
    """按 ID 执行预设策略(ID 来自 get_screener_strategies)。

    Returns:
        [{symbol, name, industry, marketcap, pettm, pbmrq, prevchg,
          prevclose, salesgrowthyoy}](空值为空字符串)
    """
    data = run_cli("screener", "run", str(strategy_id))
    if is_empty(data) or not isinstance(data, dict):
        return []
    return normalize_records(data.get("items", []))


def screener_filter(conditions: list[str], market: str = "HK") -> list[dict]:
    """自定义指标条件选股。

    Args:
        conditions: ['pettm:10:50', 'roe:5:'](KEY:MIN:MAX,MIN/MAX 可省略一侧)
        market: HK | US | CN | SG

    可用 key 见 get_screener_indicators()(marketcap/pettm/pbmrq/roe/roa/
    netmargin/salesgrowthyoy/divyld/epsttm/leverage 等)。
    """
    data = run_cli("screener", "filter", *conditions, "--market", market)
    if is_empty(data) or not isinstance(data, dict):
        return []
    return normalize_records(data.get("items", []))


def get_screener_indicators() -> list[dict]:
    """全部可用筛选指标(key/名称/取值范围)。[{id, key, name, unit, min, max}]"""
    data = run_cli("screener", "indicators")
    return normalize_records(data) if isinstance(data, list) else []


# ---- 模块③补充:港股经纪商队列(brokers / participants,仅 HK) ----

def get_broker_queue(symbol: str) -> dict:
    """港股每档价位的经纪商队列(⚠️仅港股,与 depth 快照同源)。

    Returns:
        {asks: [{position, broker_ids:[int]}], bids: [...]}
        ⚠️ 无价格字段,价格需自行用 depth/quote 对齐(position=1 即卖一/买一档)。
    """
    data = run_cli("brokers", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return {"asks": [], "bids": []}
    return {
        "asks": normalize_records(data.get("asks", [])),
        "bids": normalize_records(data.get("bids", [])),
    }


def get_participants() -> list[dict]:
    """港股经纪商 ID → 名称映射表。

    Returns:
        [{broker_id('6596'), name_cn('维恩证券'), name_en('WE')}]
        ⚠️ broker_id 是字符串,且存在多值条目(如 '7707, 7708, 7709'),
        做 id→name 映射时需把多值条目拆开分别登记。
    """
    data = run_cli("participants")
    rows = normalize_records(data) if isinstance(data, list) else []
    out = []
    for r in rows:
        ids = str(r.get("broker_id", ""))
        for bid in [x.strip() for x in ids.split(",") if x.strip()]:
            out.append({"broker_id": bid, "name_cn": r.get("name_cn"),
                        "name_en": r.get("name_en")})
    return out


# ---- 模块④补充:IPO ----

def get_ipo_listings(stage: str = "wait-listing") -> dict:
    """按阶段列出 IPO(待上市暗盘/认购中/已上市,分 HK 与 US)。

    Args:
        stage: subscriptions | wait-listing | listed | us-subscriptions |
               us-wait-listing | us-listed

    Returns:
        双市场 stage(subscriptions/wait-listing/listed): {hk: [...], us: [...]}
        US 专属 stage: {us: [...]},HK 专属同理
        条目: {symbol, name, description, ipo_date(Unix秒), issue_price, currency,
               market, mart_begin/mart_end(暗盘时段), result_date, sub_state,
               tags, win_qty, one_lot_success, ...}
    """
    data = run_cli("ipo", stage)
    if is_empty(data) or not isinstance(data, dict):
        return {}
    return {k: normalize_records(v) for k, v in data.items() if isinstance(v, list)}


def get_ipo_detail(symbol: str) -> dict:
    """IPO 详情(公司档案 + 基石投资者 + 时间线 + 个人申购额度)。

    Returns:
        {profile: {hk: {industry, investors:[{name, capital_ratio, subscribe_value}],
                        list_date, issue_price, ...}, us: {...}},
         holdings: {ipo_max_purchase, total_amount, finance_fee_rate, ...},
         eligibility: {can_subscribe}, timeline: [...]}
    """
    data = run_cli("ipo", "detail", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return {}
    return data


# ---- 模块⑤补充:宏观指标(macrodata) ----

def get_macro_indicators(keyword: str | None = None, country: str | None = None,
                         page: int = 1, limit: int = 20) -> dict:
    """列出宏观指标(分页)。

    Args:
        keyword: 按指标名搜索,如 'CPI'
        country: HK | CN | US | EU | JP | SG
        page/limit: 分页(默认每页 20)

    Returns:
        {count, has_more, limit, list: [{indicator_code, name, country,
         importance('1'-'3'), periodicity('month'等), describe(长文)}]}
        ⚠️ 历史查询用 indicator_code(不是文档示例的 'US00175' 格式)。
    """
    args = ["macrodata"]
    if country:
        args += ["--country", country]
    if keyword:
        args += ["--keyword", keyword]
    args += ["--page", str(page), "--limit", str(limit)]
    data = run_cli(*args)
    if is_empty(data) or not isinstance(data, dict):
        return {"count": 0, "has_more": False, "list": []}
    data["list"] = normalize_records(data.get("list", []))
    return data


def get_macro_history(code: str, start: str | None = None, end: str | None = None,
                      limit: int = 20) -> list[dict]:
    """某宏观指标的历史发布数据(actual/forecast/previous)。

    Args:
        code: indicator_code,来自 get_macro_indicators 列表(如 '30771434')
        start/end: YYYY-MM-DD

    Returns:
        [{period('2026-07-01'), actual_value, forecast_value, previous_value,
          release_at(Unix秒), unit('Percent'等)}](按时间倒序)
    """
    args = ["macrodata", code, "--limit", str(limit)]
    if start:
        args += ["--start", start]
    if end:
        args += ["--end", end]
    data = run_cli(*args)
    if is_empty(data) or not isinstance(data, dict):
        return []
    return normalize_records(data.get("data", []))


# ---- 模块⑥补充:服务端指标脚本(quant run,Navi 语言) ----

def run_quant_script(
    symbol: str,
    start: str,
    end: str,
    period: str = "day",
    script: str | None = None,
    script_file: str | None = None,
    language: str | None = None,
    script_input: str | None = None,
    raw: bool = False,
) -> Any:
    """在服务端跑指标/回测脚本(pine 可用;navi 服务端故障)。

    Args:
        symbol: 如 AAPL.US / 700.HK
        start/end: YYYY-MM-DD(分钟级可带 HH:MM)
        period: 1m|5m|15m|30m|1h|day|week|month|year
        script: 内联脚本(indicator()/strategy() 开头)
        script_file: 脚本文件路径(与 script 二选一,内容经 --script 传入)
        language: pine(推荐,实测可用)| navi(实测 2026-08-21 服务端 500)
        script_input: 覆盖 input.*() 默认值的 JSON 数组,如 '[14, 2.0]'
        raw: True 返回 pretty stdout(指标序列值只在 pretty 表里,
             JSON 模式的 events_json 不含 plot 值 —— CLI 0.27.1 缺口)

    响应结构(pine,json 模式): {report_json(回测报告,indicator 时 'null'),
    events_json(K线 barStart/barEnd 流), chart_json}。
    脚本错误只返回不透明错误码。
    """
    args = ["quant", "run", symbol, "--start", start, "--end", end,
            "--period", period]
    if language:
        args += ["--language", language]
    if script_input:
        args += ["--input", script_input]
    if script is not None:
        args += ["--script", script]
        return run_cli(*args, fmt="raw" if raw else "json")
    if script_file:
        with open(script_file, "r", encoding="utf-8") as f:
            content = f.read()
        args += ["--script", content]
        return run_cli(*args, fmt="raw" if raw else "json")
    raise ValueError("必须提供 script 或 script_file")


# ---- 模块⑦补充:估值对比 / 业务分部 / 行业 / 共识 / 公司行动 / 经营数据 / 公司档案 ----

def compare_stocks(symbols: list[str], currency: str = "USD") -> list[dict]:
    """多股估值横向对比(≤5 只;单只时自动对比行业同行)。

    Args:
        symbols: ['AAPL.US', 'MSFT.US', ...](第一只为基准)
        currency: USD | HKD | CNY

    Returns:
        [{counter_id, name, market, currency, price_close, market_value, pe, pb,
          ps, roe, roa, net_margin, eps, bps, sales, sales_ps, net_income,
          assets, liabilities, leverage, liabilities_assets, turnover, volume,
          dps, div_yld, div_payout_ratio, five_y_avg_dps,
          history: [{date(Unix秒), pe, pb, ps}]}]
    """
    data = run_cli("compare", *symbols, "--currency", currency)
    if is_empty(data) or not isinstance(data, dict):
        return []
    return normalize_records(data.get("list", []))


def get_business_segments(symbol: str) -> list[dict]:
    """业务分部营收拆分(地区/产品维度)。

    Returns:
        [{id, name('美洲'), percent(41.84), value(营收,当地货币), yoy(%)}]
    """
    data = run_cli("business-segments", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return []
    return normalize_records(data.get("business", []))


def get_industry_rank(market: str = "US") -> list[dict]:
    """行业板块排行(按涨幅),每个分类下是行业列表。

    Args:
        market: US | HK | CN | SG

    Returns:
        [{name(分类名), chg, lists: [{counter_id('BK/US/IN00362'), name(行业名),
          chg, leading_ticker, leading_name, leading_chg, leading_last_done,
          prev_close, value_name, value_data, minutes, minutes_count}]}]
        ⚠️ 行业 BK counter_id 在 lists[].counter_id,不在顶层。
    """
    data = run_cli("industry-rank", "--market", market)
    if is_empty(data) or not isinstance(data, dict):
        return []
    rows = normalize_records(data.get("items", []))
    for r in rows:
        r["lists"] = normalize_records(r.get("lists", []))
    return rows


def get_industry_peers(counter_id: str) -> dict:
    """行业层级树(BK counter_id 来自 industry-rank 的 lists[].counter_id)。

    Returns:
        {chain: {counter_id, name, level, parent_code, stock_num, industry_id,
                 next: [子行业...], market}, top: {industry_id, name(一级行业)}}
    """
    data = run_cli("industry-peers", counter_id)
    if is_empty(data) or not isinstance(data, dict):
        return {"chain": None, "top": None}
    return data


def get_industry_valuation_dist(symbol: str) -> dict:
    """行业估值分布(当前值 vs 行业内排名,industry-valuation dist)。

    Returns:
        {pe: {value, median, high, low, rank_index, rank_total, ranking(0-1)},
         pb: {...}, ps: {...}}(部分标的只有 pe)
        ranking > 0.7 = 行业内偏贵,< 0.3 = 行业内便宜。
    """
    data = run_cli("industry-valuation", "dist", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return {}
    return {k: normalize_records([v])[0]
            for k, v in data.items() if isinstance(v, dict)}


def get_consensus(symbol: str) -> dict:
    """财务共识明细(按报告期,营收/EPS 等科目的预测 vs 实际)。

    Returns:
        {currency, current_index, current_period('qf'等),
         list: [{period, details: [{key('revenue'), name('营业收入'),
           estimate, actual, is_released, description}]}]}
    """
    data = run_cli("consensus", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return {}
    rows = normalize_records(data.get("list", []))
    for r in rows:
        r["details"] = normalize_records(r.get("details", []))
    data["list"] = rows
    return data


def get_corp_actions(symbol: str) -> list[dict]:
    """公司行动(分红/拆合股/配股等事件流)。

    Returns:
        [{id, action('DividendExDate'等), act_type('分配方案'), act_desc,
          date('20260813'), date_str, date_type('派息日'), date_zone, is_delay}]
    """
    data = run_cli("corp-action", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return []
    return normalize_records(data.get("items", []))


def get_operating(symbol: str) -> list[dict]:
    """经营回顾与财务指标(⚠️仅港股,按报告期)。

    Returns:
        [{financial: {currency, indicators: [{field_name, indicator_name,
           indicator_value('4589 亿'), yoy}]}, ...其他经营维度}]
    """
    data = run_cli("operating", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return []
    rows = normalize_records(data.get("list", []))
    for r in rows:
        fin = r.get("financial")
        if isinstance(fin, dict):
            fin["indicators"] = normalize_records(fin.get("indicators", []))
    return rows


def get_company_profile(symbol: str) -> dict:
    """公司概况(成立年份/员工数/地址/管理层/上市信息等,扁平 dict)。"""
    data = run_cli("company", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return {}
    return normalize_records([data])[0]


def get_executives(symbol: str) -> list[dict]:
    """高管与核心人员。

    Returns:
        [{counter_id, professionals: [{name, title, biography(长文), ...}]}]
    """
    data = run_cli("executive", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return []
    rows = normalize_records(data.get("professional_list", []))
    for r in rows:
        r["professionals"] = normalize_records(r.get("professionals", []))
    return rows


# ---- 模块⑦补充:内部人交易 / 机构持仓信号源 ----

def get_insider_trades(symbol: str, count: int = 20) -> list[dict]:
    """SEC Form 4 内部人交易(⚠️仅美股)。

    Returns:
        [{owner, title('SVP'), date, filing_date, type('EXERCISE'/'BUY'/'SELL'等),
          code('M'=授予/'S'=卖出/'A'=买入等 Form4 code), shares, price, value,
          shares_after}]
    """
    data = run_cli("insider-trades", symbol, "--count", str(count))
    return normalize_records(data) if isinstance(data, list) else []


def get_investor_rankings() -> list[dict]:
    """13F 机构 AUM 排名(顶层入口)。

    Returns:
        [{cik('0001422848'), name, aum_usd, rank, period('31-MAR-2026')}]
        ⚠️ cik 保留原始字符串(前导零有意义,不能被数值化)。
    """
    data = run_cli("investors")
    if not isinstance(data, list):
        return []
    rows = normalize_records(data)
    for raw, r in zip(data, rows):
        if isinstance(raw, dict) and raw.get("cik") is not None:
            r["cik"] = str(raw["cik"])
    return rows


def get_investor_holdings(cik: str) -> dict:
    """某机构(CIK)的最新 13F 持仓。

    Args:
        cik: 如 '0001422848'(前导零可选)

    Returns:
        {cik, firm, filing_date, accession_number,
         holdings: [{cusip, name, shares, value_usd, weight_pct, share_type}]}
    """
    data = run_cli("investors", cik)
    if is_empty(data) or not isinstance(data, dict):
        return {}
    data["holdings"] = normalize_records(data.get("holdings", []))
    return data


def get_investor_changes(cik: str) -> dict:
    """某机构最近两期 13F 的持仓变动(新建/加仓/减仓/清仓)。

    Returns:
        {added: 新建数量, changes: [{action('NEW'/'ADDED'/'REDUCED'/'EXITED'),
          cusip, name, shares, value_usd, prev_shares, prev_value_usd,
          delta_usd, delta_pct}]}
    """
    data = run_cli("investors", "changes", cik)
    if is_empty(data) or not isinstance(data, dict):
        return {"added": 0, "changes": []}
    data["changes"] = normalize_records(data.get("changes", []))
    return data


def get_fund_holders(symbol: str) -> list[dict]:
    """持有该股票的基金/ETF(做市资金面信号)。

    Returns:
        [{counter_id('ETF/US/AAPX'), code, name, position_ratio(%),
          report_date('2026.08.18'), currency}]
    """
    data = run_cli("fund-holder", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return []
    return normalize_records(data.get("lists", []))


def get_shareholders(symbol: str) -> list[dict]:
    """机构股东列表(含变动)。

    Returns:
        [{shareholder_name, percent_of_shares, report_date, shares_changed,
          institution_type, stocks: [{counter_id, code, market, chg}]}]
    """
    data = run_cli("shareholder", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return []
    rows = normalize_records(data.get("shareholder_list", []))
    for r in rows:
        r["stocks"] = normalize_records(r.get("stocks", []))
    return rows


# ---- 模块②/⑧补充:指数成分 / 成交量价分布 / A-H 溢价 ----

def get_constituent(index_symbol: str, limit: int = 50, sort: str = "change",
                    order: str = "desc") -> dict:
    """指数/ETF 成分股(板块轮动监控)。

    Args:
        index_symbol: 指数用 HSI.HK / .SPX.US(美指数前缀点);
                      ETF 用 IVV.US(美股 ETF 默认拉 SEC N-PORT 全持仓)
        sort: change | price | turnover | inflow | turnover-rate | market-cap
        order: desc | asc

    Returns:
        {rise_num, fall_num, flat_num, stocks: [{counter_id, name, market,
          last_done, prev_close, chg, turnover, amount, inflow, balance,
          total_shares, circulating_shares, tags(['领涨龙头']), ...}]}
    """
    data = run_cli("constituent", index_symbol, "--limit", str(limit),
                   "--sort", sort, "--order", order)
    if is_empty(data) or not isinstance(data, dict):
        return {"rise_num": 0, "fall_num": 0, "flat_num": 0, "stocks": []}
    data["stocks"] = normalize_records(data.get("stocks", []))
    return data


def get_trade_stats(symbol: str) -> dict:
    """成交量按价位分布(近 5 日,Volume Profile)。

    Returns:
        {statistics: {avgprice, preclose, buy, sell, neutral, total_amount,
                      trades_count, timestamp, trade_date[Unix秒]},
         trades: [{price, buy_amount, sell_amount, neutral_amount}](按价位分布)}
    """
    data = run_cli("trade-stats", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return {"statistics": {}, "trades": []}
    data["statistics"] = normalize_records([data.get("statistics", {})])[0] \
        if isinstance(data.get("statistics"), dict) else {}
    data["trades"] = normalize_records(data.get("trades", []))
    return data


def get_ah_premium(symbol: str, count: int = 100, kline_type: str = "day") -> list[dict]:
    """A/H 溢价 K 线(⚠️仅 A+H 两地上市股,如 939.HK/1398.HK)。

    Returns:
        [{ahpremium_rate(-0.266=H股比A股便宜26.6%), aprice, apreclose,
          hprice, hpreclose, currency_rate, timestamp}]
    """
    data = run_cli("ah-premium", symbol, "--kline-type", kline_type,
                   "--count", str(count))
    if is_empty(data) or not isinstance(data, dict):
        return []
    return normalize_records(data.get("klines", []))


def get_ah_premium_intraday(symbol: str) -> list[dict]:
    """A/H 溢价当日分时。结构同 get_ah_premium。"""
    data = run_cli("ah-premium", "intraday", symbol)
    if is_empty(data) or not isinstance(data, dict):
        return []
    return normalize_records(data.get("klines", []))


# ---------------------------------------------------------------------------
# 主入口:环境自检(被 import 时不触发,仅在直接运行 check_env.py 时)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print_json(check_env(force=True))
