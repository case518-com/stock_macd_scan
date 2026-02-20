"""
盤中股價監控器 - GitHub Actions 版
讀取 scan_result.txt，若即時股價低於當月最低價
則呼叫 https://project.acsite.org/insert.php?num=股票代號
"""

import yfinance as yf
import requests
import re
from datetime import datetime, time as dtime

SCAN_RESULT_FILE = 'scan_result.txt'
NOTIFY_URL       = 'https://project.acsite.org/insert.php?num='

# ────────────────────────────────────────────
# 交易時間判斷（UTC+8 台灣時間）
# ────────────────────────────────────────────

def is_trading_time():
    from datetime import timezone, timedelta
    tz_tw = timezone(timedelta(hours=8))
    now = datetime.now(tz_tw)
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dtime(9, 0) <= t <= dtime(13, 30)


# ────────────────────────────────────────────
# 解析 scan_result.txt
# ────────────────────────────────────────────

def parse_scan_result(filepath):
    stocks = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for line in lines:
            if not line.strip():
                continue
            if line.startswith('=') or line.startswith('-'):
                continue
            if any(k in line for k in ['代號', '執行時間', '篩選條件', '共找到', '台股月MACD', '結果已寫入', '完成']):
                continue

            parts = re.split(r'\s{2,}', line.strip())
            if len(parts) < 5:
                continue

            try:
                code   = parts[0].strip()
                name   = parts[1].strip()
                market = parts[2].strip()
                low    = float(parts[4].strip())
                clean_code = code.replace('O', '')
                stocks.append({
                    '代號':      clean_code,
                    '名稱':      name,
                    '市場':      market,
                    '當月最低價': low,
                })
            except (ValueError, IndexError):
                continue

    except FileNotFoundError:
        print(f"❌ 找不到 {filepath}")

    return stocks


# ────────────────────────────────────────────
# 抓延遲報價
# ────────────────────────────────────────────

def get_current_price(code, market):
    try:
        suffix = '.TW' if market == '上市' else '.TWO'
        ticker = yf.Ticker(f"{code}{suffix}")
        hist = ticker.history(period='1d', interval='1m')
        if hist.empty:
            return None
        return round(hist['Close'].iloc[-1], 2)
    except:
        return None


# ────────────────────────────────────────────
# 觸價通知
# ────────────────────────────────────────────

def notify(code, name, current_price, monthly_low):
    url = f"{NOTIFY_URL}{code}"
    try:
        resp = requests.get(url, timeout=10)
        print(f"  🔔 觸價通知 {code} {name}  即時:{current_price} < 月低:{monthly_low}")
        print(f"     呼叫網址：{url}")
        print(f"     回應狀態：HTTP {resp.status_code}  內容：{resp.text[:100]}")
    except Exception as e:
        print(f"  ❌ 通知失敗 {code} {name}：{e}")


# ────────────────────────────────────────────
# 主流程
# ────────────────────────────────────────────

def main():
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    print(f"🚀 監控啟動  {now_str}")

    if not is_trading_time():
        print("⏸️  非台股交易時間（週一至週五 09:00~13:30），本次不執行")
        return

    stocks = parse_scan_result(SCAN_RESULT_FILE)
    if not stocks:
        print("⚠️  股票清單為空，結束")
        return

    print(f"📋 共監控 {len(stocks)} 檔股票")
    print("-" * 50)

    triggered = 0
    for s in stocks:
        price = get_current_price(s['代號'], s['市場'])
        if price is None:
            print(f"  ⚠️  {s['代號']} {s['名稱']} 無法取得報價")
            continue

        if price < s['當月最低價']:
            notify(s['代號'], s['名稱'], price, s['當月最低價'])
            triggered += 1
        else:
            print(f"  ✅ {s['代號']} {s['名稱']}  即時:{price}  月低:{s['當月最低價']}")

    print("-" * 50)
    print(f"✅ 完成，共觸價 {triggered} 檔")


if __name__ == '__main__':
    main()
