"""
本地手动登录/过滑块后导出 web3.52pokemon66.cc 的 Playwright Storage State。

用途：页面禁用 F12 或无法直接导出 Cookie 时，在本机打开真实浏览器，手动完成验证，
然后把生成的 web3_storage_state.json 内容复制到 GitHub Secret: WEB3_STORAGE_STATE_JSON。
"""

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

TARGET_URL = os.environ.get("TARGET_URL", "https://web3.52pokemon66.cc/plan/8").strip()
PROFILE_DIR = Path(os.environ.get("WEB3_PROFILE_DIR", ".web3-profile")).resolve()
OUTPUT = Path(os.environ.get("WEB3_STORAGE_STATE_OUT", "web3_storage_state.json")).resolve()
HEADLESS = os.environ.get("HEADLESS", "false").strip().lower() in {"1", "true", "yes"}


def main():
    print("=" * 60)
    print("手动采集 WEB3_STORAGE_STATE_JSON")
    print("=" * 60)
    print(f"目标页面: {TARGET_URL}")
    print(f"浏览器资料目录: {PROFILE_DIR}")
    print(f"输出文件: {OUTPUT}")
    print()
    print("接下来会打开浏览器。请在浏览器里手动完成：")
    print("1. 滑块/安全验证")
    print("2. 登录账号")
    print("3. 确认能正常进入套餐页或用户中心")
    print("完成后回到这个终端按 Enter。")
    print()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=HEADLESS,
            viewport={"width": 1440, "height": 1100},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
        input("手动验证/登录完成后，按 Enter 导出登录状态...")
        state = context.storage_state(path=str(OUTPUT))
        context.close()

    compact = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    print()
    print(f"已保存: {OUTPUT}")
    print()
    print("把下面这一整行复制到 GitHub Secret: WEB3_STORAGE_STATE_JSON")
    print("-" * 60)
    print(compact)
    print("-" * 60)
    print("注意：这段内容等同登录凭据，不要发到聊天、不要提交进仓库。")


if __name__ == "__main__":
    main()
