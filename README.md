# 每月自动购买入门精灵球套餐

本项目已从 “ClawCloud Run 自动登录保活” 改为：每月访问 `https://web3.52pokemon66.cc/plan/8`，等待你通过 Telegram 发送当月优惠码，然后购买「入门精灵球」套餐。

> 安全边界：脚本只走网站正常购买流程，不绕过付款、不伪造订单。只有检测到优惠码把应付金额降为 `0` 时才会提交订单；如果仍需付款、出现滑块/人机验证、验证码或页面结构变化，脚本会停止并通知。

## 功能

- 每月自动打开套餐页。
- 支持账号密码登录，或使用已登录 Cookie。
- 每次运行时通过 Telegram 等待你发送当月优惠码。
- 自动填入优惠码并点击应用。
- 仅在确认应付金额为 `0` 时提交订单。
- 支持 Telegram 通知和失败截图上传。
- 原 ClawCloud 自动登录 workflow 已停用。

## GitHub Secrets 配置

在 Fork 后的仓库中进入：`Settings` → `Secrets and variables` → `Actions` → `New repository secret`。

| Secret 名称 | 是否必须 | 描述 |
| --- | --- | --- |
| `TG_BOT_TOKEN` | 是 | Telegram Bot Token，用于请求你发送当月优惠码和通知结果。 |
| `TG_CHAT_ID` | 是 | 你的 Telegram User ID 或接收消息的 Chat ID。脚本只接受这个 Chat ID 发来的优惠码。 |
| `COUPON_CODE` | 否 | 固定优惠码兜底。每月都不同的话留空，脚本会等 Telegram 输入。 |
| `WEB3_USERNAME` | 二选一 | 网站登录账号/邮箱。若配置 Cookie 可不填。 |
| `WEB3_PASSWORD` | 二选一 | 网站登录密码。若配置 Cookie 可不填。 |
| `WEB3_COOKIE_JSON` | 二选一 | 浏览器导出的 Cookie JSON。推荐用于需要人机验证/验证码的网站。 |
| `WEB3_COOKIE_STRING` | 二选一 | Cookie 字符串，例如 `a=1; b=2`。 |
| `PROXY_DSN` | 否 | 代理，例如 `socks5://user:pass@host:port` 或 `http://host:port`。 |

## Telegram 发送优惠码

GitHub Actions 每月启动后，机器人会给你发：

```text
请发送本月优惠码
```

你可以回复任意一种格式：

```text
/coupon ABCD1234
优惠码 ABCD1234
ABCD1234
```

默认等待 `900` 秒，也就是 15 分钟。要改等待时间，编辑 `.github/workflows/monthly-purchase.yml` 里的：

```yaml
COUPON_WAIT_SECONDS: '900'
```

## Cookie 登录建议

目标站当前直接访问会返回安全滑块验证页面。脚本不会绕过此类验证。更稳的做法是：

1. 在本地浏览器手动打开 `https://web3.52pokemon66.cc/plan/8`。
2. 手动完成登录和安全验证。
3. 用浏览器插件或开发者工具导出该站 Cookie。
4. 将 Cookie 保存到 `WEB3_COOKIE_JSON` 或 `WEB3_COOKIE_STRING`。

## 运行方式

### 自动运行

`.github/workflows/monthly-purchase.yml` 默认每月 1 日 UTC 02:15 运行，也就是北京时间 10:15。

如需修改时间，编辑：

```yaml
schedule:
  - cron: '15 2 1 * *'
```

### 手动运行

进入 GitHub 仓库 → `Actions` → `每月购买入门精灵球套餐` → `Run workflow`。

## 本地测试

```bash
pip install playwright requests
playwright install chromium

export TG_BOT_TOKEN='你的 Telegram Bot Token'
export TG_CHAT_ID='你的 Telegram Chat ID'
export WEB3_USERNAME='你的账号'
export WEB3_PASSWORD='你的密码'
# 或：export WEB3_COOKIE_STRING='a=1; b=2'
python scripts/monthly_purchase.py
```

如果只想验证优惠码后是否为 0 元、不提交订单：

```bash
AUTO_CONFIRM_ZERO_ORDER=false python scripts/monthly_purchase.py
```

## 页面结构变化时

如果网站的金额字段不易自动识别，可以用 `ZERO_AMOUNT_SELECTOR` 指定应付金额的 CSS 选择器。脚本在该选择器内容显示 `0` 且没有非零应付金额时才提交。

```bash
export ZERO_AMOUNT_SELECTOR='.order-total'
```
