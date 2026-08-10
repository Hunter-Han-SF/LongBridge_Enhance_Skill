"""环境预检脚本:检查 longbridge CLI + token 状态 + Python 版本。

用法:
    python check_env.py            # 完整检查
    python check_env.py --force    # 强制刷新,忽略缓存
"""
from __future__ import annotations

import argparse
import sys

# 让脚本能从 scripts/ 目录直接运行时导入 common.py
import os
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)))))

from common import check_env, print_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="longbridge-derivatives-pro 环境预检")
    parser.add_argument("--force", action="store_true", help="强制刷新,忽略 1 小时缓存")
    args = parser.parse_args()

    result = check_env(force=args.force)

    # 脱敏:auth_detail 含 member id / token 过期时间等个人信息,不对外输出
    result.pop("auth_detail", None)

    print_json(result)

    if not result.get("ok"):
        if "error" in result:
            print(f"\n❌ 环境检查未通过: {result['error']}", file=sys.stderr)
        elif result.get("auth") != "valid":
            print("\n❌ Token 无效。请运行: longbridge auth login", file=sys.stderr)
        return 1

    print("\n✅ 环境就绪,可以运行期权脚本。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
