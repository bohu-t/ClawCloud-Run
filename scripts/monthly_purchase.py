"""
每月自动购买 web3.52pokemon66.cc 入门精灵球套餐。

安全边界：
- 只使用站点正常页面和当月通过 Telegram 发送/环境变量配置的优惠码。
- 只有检测到优惠码把应付金额降为 0 时才提交订单。
- 如果页面进入付款流程、金额不为 0、出现滑块/人机验证或找不到关键按钮，会停止并通知。
"""

import json
import os
import random
import re
import sys
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlparse

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

TARGET_URL = os.environ.get("TARGET_URL", "https://web3.52pokemon66.cc/plan/8").strip()
LOGIN_URL = os.environ.get("LOGIN_URL", "https://web3.52pokemon66.cc/login").strip()
USERNAME = os.environ.get("WEB3_USERNAME", "").strip()
PASSWORD = os.environ.get("WEB3_PASSWORD", "").strip()
COUPON_CODE = os.environ.get("COUPON_CODE", "").strip()
COUPON_WAIT_SECONDS = int(os.environ.get("COUPON_WAIT_SECONDS", "900"))
TELEGRAM_DELETE_WEBHOOK = os.environ.get("TELEGRAM_DELETE_WEBHOOK", "true").strip().lower() not in {"0", "false", "no"}
COOKIE_JSON = os.environ.get("WEB3_COOKIE_JSON", "").strip()
COOKIE_STRING = os.environ.get("WEB3_COOKIE_STRING", "").strip()
PROXY_DSN = os.environ.get("PROXY_DSN", "").strip()
HEADLESS = os.environ.get("HEADLESS", "true").strip().lower() not in {"0", "false", "no"}
AUTO_CONFIRM_ZERO_ORDER = os.environ.get("AUTO_CONFIRM_ZERO_ORDER", "true").strip().lower() not in {"0", "false", "no"}
POST_PURCHASE_WAIT_SECONDS = int(os.environ.get("POST_PURCHASE_WAIT_SECONDS", "8"))
ZERO_AMOUNT_SELECTOR = os.environ.get("ZERO_AMOUNT_SELECTOR", "").strip()

SCREENSHOT_DIR = Path(os.environ.get("SCREENSHOT_DIR", ".")).resolve()
DEVICE_SCALE_FACTOR = float(os.environ.get("DEVICE_SCALE_FACTOR", "1"))


class Telegram:
    def __init__(self):
        self.token = os.environ.get("TG_BOT_TOKEN", "").strip()
        self.chat_id = os.environ.get("TG_CHAT_ID", "").strip()
        self.ok = bool(self.token and self.chat_id)

    def send(self, msg):
        if not self.ok:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                data={"chat_id": self.chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=30,
            )
        except Exception:
            pass

    def photo(self, path, caption=""):
        if not self.ok or not path or not os.path.exists(path):
            return
        try:
            with open(path, "rb") as f:
                requests.post(
                    f"https://api.telegram.org/bot{self.token}/sendPhoto",
                    data={"chat_id": self.chat_id, "caption": caption[:1024]},
                    files={"photo": f},
                    timeout=60,
                )
        except Exception:
            pass

    def delete_webhook(self):
        """轮询 getUpdates 前清理 webhook；否则 Telegram 会拒绝 getUpdates。"""
        if not self.ok or not TELEGRAM_DELETE_WEBHOOK:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{self.token}/deleteWebhook",
                data={"drop_pending_updates": "false"},
                timeout=10,
            )
        except Exception:
            pass

    def flush_updates(self):
        """把 Telegram update offset 刷到最新，避免读到上个月旧优惠码。"""
        if not self.ok:
            return 0
        self.delete_webhook()
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{self.token}/getUpdates",
                params={"timeout": 0},
                timeout=10,
            )
            data = r.json()
            if data.get("ok") and data.get("result"):
                return data["result"][-1]["update_id"] + 1
        except Exception:
            pass
        return 0

    def wait_coupon(self, timeout=900):
        """
        等待你在 Telegram 发送当月优惠码。

        支持格式：
        - /coupon ABCD1234
        - /coupon@你的机器人 ABCD1234
        - 优惠码 ABCD1234
        - 直接发送 ABCD1234
        """
        if not self.ok:
            return None

        offset = self.flush_updates()
        deadline = time.time() + timeout
        self.send(
            "🔐 <b>请发送本月优惠码</b>\n\n"
            "支持格式：\n"
            "<code>/coupon 优惠码</code>\n"
            "<code>优惠码 ABCD1234</code>\n"
            "或直接发送优惠码。\n\n"
            f"等待时间：{timeout} 秒"
        )

        while time.time() < deadline:
            try:
                r = requests.get(
                    f"https://api.telegram.org/bot{self.token}/getUpdates",
                    params={"timeout": 20, "offset": offset, "allowed_updates": json.dumps(["message", "edited_message", "channel_post", "edited_channel_post"])},
                    timeout=30,
                )
                data = r.json()
                if not data.get("ok"):
                    description = data.get("description") or "未知错误"
                    # 最常见：bot 配了 webhook，getUpdates 会报 409 Conflict。
                    if "webhook" in description.lower():
                        self.delete_webhook()
                        self.send("⚠️ Telegram webhook 与轮询冲突，已尝试清理 webhook，请重新发送优惠码。")
                    time.sleep(2)
                    continue

                for upd in data.get("result", []):
                    offset = upd["update_id"] + 1
                    msg = (
                        upd.get("message")
                        or upd.get("edited_message")
                        or upd.get("channel_post")
                        or upd.get("edited_channel_post")
                        or {}
                    )
                    chat = msg.get("chat") or {}
                    chat_id = chat.get("id")
                    if str(chat_id) != str(self.chat_id):
                        self.send(f"⚠️ 收到来自其他 chat_id={chat_id} 的消息，已忽略。请确认 TG_CHAT_ID 是否填对。")
                        continue

                    text = (msg.get("text") or msg.get("caption") or "").strip()
                    coupon = self.extract_coupon(text)
                    if coupon:
                        self.send("✅ 已识别优惠码，开始执行购买流程。")
                        return coupon

                    if text:
                        self.send(
                            "⚠️ 没识别出优惠码。请发送：\n"
                            "<code>/coupon ABCD1234</code>\n"
                            "或直接发送不带空格的优惠码。"
                        )
            except Exception as e:
                self.send(f"⚠️ 读取 Telegram 消息时出错：{type(e).__name__}")

            time.sleep(2)

        return None

    @staticmethod
    def extract_coupon(text):
        if not text:
            return None
        text = text.strip()
        patterns = [
            r"^/coupon(?:@[A-Za-z0-9_]+)?\s+(.+)$",
            r"^(?:优惠码|折扣码|兑换码)[:：\s]+(.+)$",
            r"^([^\s]{2,128})$",
        ]
        for pattern in patterns:
            m = re.match(pattern, text, re.IGNORECASE)
            if not m:
                continue
            coupon = m.group(1).strip()
            coupon = coupon.split()[0].strip("'\"`，,。；;")
            # 优惠码允许常见可打印符号，但不允许空白、控制字符或过长内容。
            if 2 <= len(coupon) <= 128 and not re.search(r"\s", coupon):
                return coupon
        return None


class MonthlyPurchase:
    def __init__(self):
        self.tg = Telegram()
        self.logs = []
        self.shots = []
        self.n = 0
        self.coupon_code = COUPON_CODE
        parsed = urlparse(TARGET_URL)
        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
        self.cookie_domain = parsed.hostname or "web3.52pokemon66.cc"

    def log(self, msg, level="INFO"):
        icons = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "WARN": "⚠️", "STEP": "🔹"}
        line = f"{icons.get(level, '•')} {msg}"
        print(line, flush=True)
        self.logs.append(line)

    def shot(self, page, name):
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        self.n += 1
        safe = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", name).strip("_") or "shot"
        path = SCREENSHOT_DIR / f"{self.n:02d}_{safe}.png"
        try:
            page.screenshot(path=str(path), full_page=True)
            self.shots.append(str(path))
            return str(path)
        except Exception:
            return ""

    def notify(self, ok, err=""):
        if not self.tg.ok:
            return
        status = "✅ 成功" if ok else "❌ 失败"
        msg = f"""<b>🤖 每月套餐自动购买</b>

<b>状态:</b> {status}
<b>套餐:</b> {TARGET_URL}
<b>优惠码:</b> {'已收到/已配置' if self.coupon_code else '未收到'}
<b>时间:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}"""
        if err:
            msg += f"\n<b>原因:</b> {err}"
        msg += "\n\n<b>最近日志:</b>\n" + "\n".join(self.logs[-8:])
        self.tg.send(msg)
        if self.shots:
            self.tg.photo(self.shots[-1], "最后页面截图")

    def human_delay(self, a=0.3, b=0.9):
        time.sleep(random.uniform(a, b))

    def add_cookies(self, context):
        cookies = []
        if COOKIE_JSON:
            try:
                data = json.loads(COOKIE_JSON)
                if isinstance(data, dict):
                    data = data.get("cookies", [])
                if not isinstance(data, list):
                    raise ValueError("WEB3_COOKIE_JSON 必须是 cookie 数组，或包含 cookies 字段的对象")
                for item in data:
                    if not isinstance(item, dict) or not item.get("name") or item.get("value") is None:
                        continue
                    cookie = dict(item)
                    cookie.setdefault("domain", self.cookie_domain)
                    cookie.setdefault("path", "/")
                    cookies.append(cookie)
            except Exception as e:
                raise RuntimeError(f"解析 WEB3_COOKIE_JSON 失败: {e}") from e

        if COOKIE_STRING:
            jar = SimpleCookie()
            try:
                jar.load(COOKIE_STRING)
                for name, morsel in jar.items():
                    cookies.append({
                        "name": name,
                        "value": morsel.value,
                        "domain": self.cookie_domain,
                        "path": "/",
                    })
            except Exception as e:
                raise RuntimeError(f"解析 WEB3_COOKIE_STRING 失败: {e}") from e

        if cookies:
            context.add_cookies(cookies)
            self.log(f"已加载 {len(cookies)} 个站点 Cookie", "SUCCESS")

    def launch_options(self):
        opts = {
            "headless": HEADLESS,
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
            ],
        }
        if PROXY_DSN:
            p_url = urlparse(PROXY_DSN)
            if not p_url.scheme or not p_url.hostname or not p_url.port:
                raise RuntimeError("PROXY_DSN 格式错误，应类似 socks5://user:pass@host:port 或 http://host:port")
            proxy = {"server": f"{p_url.scheme}://{p_url.hostname}:{p_url.port}"}
            if p_url.username:
                proxy["username"] = p_url.username
            if p_url.password:
                proxy["password"] = p_url.password
            opts["proxy"] = proxy
            self.log(f"启用代理: {proxy['server']}")
        return opts

    def page_text(self, page):
        try:
            return page.locator("body").inner_text(timeout=5000)
        except Exception:
            return ""

    def is_guard_page(self, page):
        url = page.url.lower()
        text = self.page_text(page).lower()
        title = ""
        try:
            title = page.title().lower()
        except Exception:
            pass
        guard_signs = [
            "/_guard/" in url,
            "security verification" in title,
            "security verification" in text,
            "slide to complete" in text,
            "向右滑动完成拼图" in text,
            page.locator(".slider-handle, .puzzle-piece").count() > 0,
        ]
        return any(guard_signs)

    def assert_no_guard(self, page):
        if self.is_guard_page(page):
            self.shot(page, "人机验证")
            raise RuntimeError("页面出现滑块/人机验证。脚本不会绕过验证；请先在浏览器手动登录/验证后导出 WEB3_COOKIE_JSON 或 WEB3_COOKIE_STRING 再运行。")

    def first_visible(self, page, selectors, timeout=1500):
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.is_visible(timeout=timeout):
                    return locator, selector
            except Exception:
                continue
        return None, ""

    def click_first(self, page, selectors, desc, timeout=1500, required=False):
        locator, selector = self.first_visible(page, selectors, timeout=timeout)
        if not locator:
            if required:
                raise RuntimeError(f"找不到按钮/链接: {desc}")
            return False
        locator.scroll_into_view_if_needed(timeout=5000)
        self.human_delay()
        locator.click(timeout=10000)
        self.log(f"已点击: {desc} ({selector})", "SUCCESS")
        return True

    def fill_first(self, page, selectors, value, desc, timeout=1500, required=False):
        locator, selector = self.first_visible(page, selectors, timeout=timeout)
        if not locator:
            if required:
                raise RuntimeError(f"找不到输入框: {desc}")
            return False
        locator.scroll_into_view_if_needed(timeout=5000)
        self.human_delay()
        locator.click(timeout=10000)
        try:
            locator.fill("")
        except Exception:
            pass
        locator.type(value, delay=random.randint(20, 80), timeout=30000)
        self.log(f"已填写: {desc} ({selector})", "SUCCESS")
        return True

    def goto(self, page, url, desc):
        self.log(f"打开 {desc}: {url}", "STEP")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except PlaywrightTimeoutError:
            pass
        self.human_delay(1, 2)
        self.assert_no_guard(page)
        self.shot(page, desc)

    def looks_logged_in(self, page):
        text = self.page_text(page)
        login_words = ["登录", "登入", "Login", "Sign in", "邮箱", "密码", "password", "email"]
        account_words = ["退出", "注销", "用户中心", "个人中心", "我的", "订单", "余额", "Dashboard", "Logout"]
        has_account = any(w.lower() in text.lower() for w in account_words)
        has_login_form = page.locator('input[type="password"], input[name*="password" i]').count() > 0
        if has_login_form:
            return False
        return has_account or not any(w.lower() in text.lower() for w in login_words)

    def login_if_needed(self, page):
        if self.looks_logged_in(page):
            self.log("当前看起来已登录", "SUCCESS")
            return
        if not USERNAME or not PASSWORD:
            raise RuntimeError("需要登录，但未配置 WEB3_USERNAME/WEB3_PASSWORD；也可以改用 WEB3_COOKIE_JSON/WEB3_COOKIE_STRING。")

        self.log("检测到未登录，尝试登录", "STEP")
        if page.locator('input[type="password"], input[name*="password" i]').count() == 0:
            # 先从当前页找登录入口，不行再打开 LOGIN_URL。
            clicked = self.click_first(page, [
                'a:has-text("登录")',
                'button:has-text("登录")',
                'a:has-text("登入")',
                'button:has-text("登入")',
                'a:has-text("Login")',
                'button:has-text("Login")',
                'a[href*="login"]',
            ], "登录入口", timeout=1000)
            if clicked:
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except PlaywrightTimeoutError:
                    pass
            if page.locator('input[type="password"], input[name*="password" i]').count() == 0:
                self.goto(page, LOGIN_URL, "登录页")

        self.assert_no_guard(page)
        self.fill_first(page, [
            'input[name="email"]',
            'input[name="username"]',
            'input[name="account"]',
            'input[type="email"]',
            'input[placeholder*="邮箱"]',
            'input[placeholder*="账号"]',
            'input[placeholder*="用户名"]',
            'input[placeholder*="Email" i]',
            'input[placeholder*="Account" i]',
        ], USERNAME, "账号/邮箱", required=True)
        self.fill_first(page, [
            'input[name="password"]',
            'input[type="password"]',
            'input[placeholder*="密码"]',
            'input[placeholder*="Password" i]',
        ], PASSWORD, "密码", required=True)
        self.click_first(page, [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("登录")',
            'button:has-text("登入")',
            'button:has-text("Login")',
            'button:has-text("Sign in")',
        ], "提交登录", required=True)
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except PlaywrightTimeoutError:
            pass
        self.human_delay(2, 4)
        self.assert_no_guard(page)
        self.shot(page, "登录后")
        if not self.looks_logged_in(page):
            raise RuntimeError("登录后仍未检测到已登录状态，请检查账号密码或是否需要验证码。")
        self.log("登录完成", "SUCCESS")

    def ensure_coupon_input(self, page):
        coupon_selectors = self.coupon_selectors()
        locator, selector = self.first_visible(page, coupon_selectors, timeout=1000)
        if locator:
            return True
        # 可能需要先点套餐页的购买按钮进入订单页。
        self.click_first(page, [
            'button:has-text("立即购买")',
            'a:has-text("立即购买")',
            'button:has-text("购买")',
            'a:has-text("购买")',
            'button:has-text("订阅")',
            'a:has-text("订阅")',
            'button:has-text("Buy")',
            'a:has-text("Buy")',
            'button:has-text("Subscribe")',
            'a:has-text("Subscribe")',
            'button:has-text("Get Started")',
            'a:has-text("Get Started")',
        ], "进入订单/购买页", timeout=1500, required=False)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except PlaywrightTimeoutError:
            pass
        self.human_delay(1, 2)
        self.assert_no_guard(page)
        self.shot(page, "订单页")
        return self.first_visible(page, coupon_selectors, timeout=3000)[0] is not None

    @staticmethod
    def coupon_selectors():
        return [
            'input[name*="coupon" i]',
            'input[name*="promo" i]',
            'input[name*="discount" i]',
            'input[id*="coupon" i]',
            'input[id*="promo" i]',
            'input[placeholder*="优惠码"]',
            'input[placeholder*="折扣码"]',
            'input[placeholder*="兑换码"]',
            'input[placeholder*="优惠券"]',
            'input[placeholder*="Coupon" i]',
            'input[placeholder*="Promo" i]',
            'input[placeholder*="Discount" i]',
        ]

    def apply_coupon(self, page):
        if not self.coupon_code:
            raise RuntimeError("缺少优惠码。")
        if not self.ensure_coupon_input(page):
            raise RuntimeError("未找到优惠码输入框；可能页面结构变化，或需要先手动登录/进入订单页。")
        self.fill_first(page, self.coupon_selectors(), self.coupon_code, "优惠码", timeout=3000, required=True)
        self.click_first(page, [
            'button:has-text("使用")',
            'button:has-text("应用")',
            'button:has-text("兑换")',
            'button:has-text("确认")',
            'button:has-text("Apply")',
            'button:has-text("Redeem")',
            'button:has-text("Use")',
            'button[type="submit"]',
        ], "应用优惠码", timeout=1500, required=False)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except PlaywrightTimeoutError:
            pass
        self.human_delay(2, 4)
        self.assert_no_guard(page)
        self.shot(page, "应用优惠码后")

    def amount_texts(self, page):
        texts = []
        selectors = [
            ZERO_AMOUNT_SELECTOR,
            '[class*="total" i]',
            '[class*="amount" i]',
            '[class*="price" i]',
            '[class*="pay" i]',
            '[id*="total" i]',
            '[id*="amount" i]',
            '[id*="price" i]',
            '[id*="pay" i]',
        ]
        for selector in [s for s in selectors if s]:
            try:
                loc = page.locator(selector)
                count = min(loc.count(), 20)
                for i in range(count):
                    try:
                        txt = loc.nth(i).inner_text(timeout=1000).strip()
                        if txt:
                            texts.append(txt)
                    except Exception:
                        pass
            except Exception:
                pass
        body = self.page_text(page)
        if body:
            texts.append(body)
        return texts

    def payable_is_zero(self, page):
        texts = self.amount_texts(page)
        joined = "\n".join(texts)
        if ZERO_AMOUNT_SELECTOR:
            # 用户指定了精确金额选择器时，只信这个选择器里的 0 元结果。
            exact = "\n".join(texts[:-1] or texts)
            if self.has_zero_amount(exact) and not self.has_non_zero_payable(exact):
                self.log(f"ZERO_AMOUNT_SELECTOR 检测到 0 元: {ZERO_AMOUNT_SELECTOR}", "SUCCESS")
                return True
            return False

        # 常见“应付/合计/总计/Total/Amount due”等字段附近出现 0 元。
        zero_context = re.compile(
            r"(应付|需付|实付|合计|总计|总额|待支付|付款金额|支付金额|amount\s*due|total|payable)[\s\S]{0,80}"
            r"(¥|￥|CNY|RMB|USD|US\$|\$)?\s*0(?:\.00)?\b|"
            r"(¥|￥)\s*0(?:\.00)?\b|\b0(?:\.00)?\s*(元|CNY|RMB)",
            re.IGNORECASE,
        )
        if zero_context.search(joined) and not self.has_non_zero_payable(joined):
            self.log("检测到应付金额为 0", "SUCCESS")
            return True
        self.log("未能确认应付金额为 0", "WARN")
        return False

    @staticmethod
    def has_zero_amount(text):
        return bool(re.search(r"(¥|￥|CNY|RMB|USD|US\$|\$)?\s*0(?:\.00)?\b|\b0(?:\.00)?\s*(元|CNY|RMB|USD)", text, re.I))

    @staticmethod
    def has_non_zero_payable(text):
        # 只把“应付/合计/总计/付款金额”等关键上下文里的非零价格视为风险，避免套餐原价干扰。
        pattern = re.compile(
            r"(应付|需付|实付|合计|总计|总额|待支付|付款金额|支付金额|amount\s*due|total|payable)[\s\S]{0,80}"
            r"(¥|￥|CNY|RMB|USD|US\$|\$)?\s*([1-9]\d*(?:\.\d{1,2})?)\b",
            re.IGNORECASE,
        )
        return bool(pattern.search(text))

    def submit_zero_order(self, page):
        if not self.payable_is_zero(page):
            raise RuntimeError("优惠码后未确认应付金额为 0，已停止，避免进入付款流程。")
        if not AUTO_CONFIRM_ZERO_ORDER:
            self.log("AUTO_CONFIRM_ZERO_ORDER=false，仅验证 0 元，不提交订单", "WARN")
            return
        self.click_first(page, [
            'button:has-text("确认购买")',
            'button:has-text("立即购买")',
            'button:has-text("提交订单")',
            'button:has-text("创建订单")',
            'button:has-text("确认订单")',
            'button:has-text("购买")',
            'button:has-text("订阅")',
            'button:has-text("Confirm")',
            'button:has-text("Submit")',
            'button:has-text("Place order")',
            'button:has-text("Buy")',
            'button:has-text("Subscribe")',
            'button[type="submit"]',
        ], "提交 0 元订单", timeout=2000, required=True)
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except PlaywrightTimeoutError:
            pass
        time.sleep(POST_PURCHASE_WAIT_SECONDS)
        self.assert_no_guard(page)
        self.shot(page, "提交订单后")
        text = self.page_text(page)
        current_url = page.url.lower()
        payment_words = ["alipay", "wechat", "stripe", "paypal", "checkout", "pay", "付款", "支付"]
        success_words = ["购买成功", "订阅成功", "订单成功", "开通成功", "成功", "Success", "Completed", "Paid"]
        if any(w in current_url for w in payment_words) and not any(w.lower() in text.lower() for w in success_words):
            raise RuntimeError("提交后进入了付款页面，未继续操作。请检查优惠码是否仍可 0 元购买。")
        if not any(w.lower() in text.lower() for w in success_words):
            self.log("未看到明确成功文案，请根据截图确认订单状态", "WARN")
        else:
            self.log("检测到成功文案", "SUCCESS")

    def run(self):
        print("\n" + "=" * 54)
        print("🚀 每月入门精灵球套餐自动购买")
        print("=" * 54 + "\n")
        self.log(f"套餐 URL: {TARGET_URL}")
        self.log(f"账号: {'有' if USERNAME else '无'}")
        self.log(f"密码: {'有' if PASSWORD else '无'}")
        self.log(f"Cookie: {'有' if (COOKIE_JSON or COOKIE_STRING) else '无'}")
        self.log(f"优惠码: {'环境变量已有' if self.coupon_code else '等待 Telegram 发送'}")
        if not self.coupon_code:
            if not self.tg.ok:
                raise RuntimeError("未配置 COUPON_CODE，且 TG_BOT_TOKEN/TG_CHAT_ID 不完整，无法通过 Telegram 接收优惠码。")
            self.log(f"等待 Telegram 发送当月优惠码（{COUPON_WAIT_SECONDS} 秒）...", "STEP")
            coupon = self.tg.wait_coupon(timeout=COUPON_WAIT_SECONDS)
            if not coupon:
                raise RuntimeError("等待 Telegram 优惠码超时。")
            self.coupon_code = coupon
            self.log("已收到 Telegram 优惠码", "SUCCESS")
            self.tg.send("✅ 已收到优惠码，开始购买流程。")

        with sync_playwright() as p:
            browser = p.chromium.launch(**self.launch_options())
            context = browser.new_context(
                viewport={"width": 1440, "height": 1100},
                device_scale_factor=DEVICE_SCALE_FACTOR,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/128.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
                window.chrome = { runtime: {} };
            """)
            self.add_cookies(context)
            page = context.new_page()
            try:
                self.goto(page, TARGET_URL, "套餐页")
                self.login_if_needed(page)
                # 登录后回到套餐页，避免登录流程跳到用户中心。
                self.goto(page, TARGET_URL, "套餐页_登录后")
                self.apply_coupon(page)
                self.submit_zero_order(page)
                self.notify(True)
                print("\n✅ 完成。\n")
            except Exception as e:
                self.log(str(e), "ERROR")
                self.shot(page, "失败")
                self.notify(False, str(e))
                raise
            finally:
                browser.close()


if __name__ == "__main__":
    try:
        MonthlyPurchase().run()
    except Exception:
        sys.exit(1)
