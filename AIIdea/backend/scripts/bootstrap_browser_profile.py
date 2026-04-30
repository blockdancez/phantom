# backend/scripts/bootstrap_browser_profile.py
"""一次性引导：以有头 Chrome 拉起 Playwright，让用户手动登录 Google。

跑法：
    cd backend && PYTHONPATH=. python scripts/bootstrap_browser_profile.py

脚本会打开真 Chrome 窗口，导航到 https://accounts.google.com。
用户手动登录完后，回到终端按 Enter 即可关闭浏览器，
profile 数据已经写到 backend/data/browser_profile。
"""
import asyncio
import sys

from src.product_experience.browser import DEFAULT_USER_DATA_DIR, BrowserSession


async def main() -> None:
    print(f"[bootstrap] user_data_dir = {DEFAULT_USER_DATA_DIR}")
    print("[bootstrap] 即将打开 Chrome 窗口，请在窗口里完成 Google 登录。")
    print("[bootstrap] 登录完成后请回到本终端按 Enter 退出。")

    session = BrowserSession(headless=False)
    async with session.open() as ctx:
        page = await ctx.new_page()
        await page.goto("https://accounts.google.com")
        # 阻塞等用户按 Enter
        await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
    print("[bootstrap] 已关闭浏览器，profile 已保存。")


if __name__ == "__main__":
    asyncio.run(main())
