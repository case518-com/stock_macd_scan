"""
盤中股價監控器 - GitHub Actions 版
讀取 scan_result.txt，若即時股價低於當月最低價則呼叫通知網址
頻率：第一次觸價立即通知，之後每小時最多一次
通知紀錄存在 alert_log.json（會 commit 回 GitHub）
"""

import yfinance as yf
import requests
import re
import json
import os
from datetime import datetime, time as dtime, timezone, timedelta

SCAN_RESULT_FILE = 'scan_result.txt'
ALERT_LOG_FILE   = 'alert_log.json'
NOTIFY_URL       = 'https://case.acsite.org/arduino2/insert.php?num='
COOLDOWN_HOURS   = 1   # 同一檔股票最少間隔幾小時才再通知

TZ_TW = timezone(timedelta(hours=8))


# ────────────────────────────────────────────
# 交易時間判斷
# ────────────────────────────────────────────

#def is_trading_time():
#    now = datetime.now(TZ_TW)
#    if now.weekday() >= 5:
#        return False
#    t = now.time()
#    return dtime(9, 0) <= t <= dtime(13, 30)

# 測試用，直接回傳 True
def is_trading_time():
    return True


# ────────────────────────────────────────────
# 通知紀錄讀寫（alert_log.json）
# 格式：{ "2371": "2026-02-20T10:30:00+08:00", ... }
# ────────────────────────────────────────────

def load_alert_log():
    if not os.path.exists(ALERT_LOG_FILE):
        return {}
    try:
        with open(ALERT_LOG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}


def save_alert_log(log):
    with open(ALERT_LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def should_notify(code, log):
    """
    判斷這檔股票現在是否該發通知：
    - 從未通知過 → 發
    - 距離上次通知超過 COOLDOWN_HOURS 小時 → 發
    - 否則跳過
    """
    if code not in log:
        return True
    last_str = log[code]
    try:
        last_time = datetime.fromisoformat(last_str)
        now = datetime.now(TZ_TW)
        diff_hours = (now - last_time).total_seconds() / 3600
        return diff_hours >= COOLDOWN_HOURS
    except:
        return True


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
            if any(k in line for k in ['代號', '執行時間', '篩選條件', '共找到',
                                        '台股月MACD', '結果已寫入', '完成']):
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
        print(f"     網址：{url}")
        print(f"     回應：HTTP {resp.status_code}  {resp.text[:100]}")
        return True
    except Exception as e:
        print(f"  ❌ 通知失敗 {code} {name}：{e}")
        return False


# ────────────────────────────────────────────
# 主流程
# ────────────────────────────────────────────

def main():
    now_tw  = datetime.now(TZ_TW)
    now_str = now_tw.strftime('%Y-%m-%d %H:%M')
    print(f"🚀 監控啟動  {now_str} (台灣時間)")

    if not is_trading_time():
        print("⏸️  非台股交易時間（週一至週五 09:00~13:30），結束")
        return

    stocks = parse_scan_result(SCAN_RESULT_FILE)
    if not stocks:
        print("⚠️  股票清單為空，結束")
        return

    print(f"📋 共監控 {len(stocks)} 檔股票")
    print("-" * 55)

    log = load_alert_log()
    log_updated = False
    triggered = 0

    for s in stocks:
        price = get_current_price(s['代號'], s['市場'])
        if price is None:
            print(f"  ⚠️  {s['代號']} {s['名稱']} 無法取得報價")
            continue

        if price < s['當月最低價']:
            if should_notify(s['代號'], log):
                success = notify(s['代號'], s['名稱'], price, s['當月最低價'])
                if success:
                    # 記錄本次通知時間
                    log[s['代號']] = now_tw.isoformat()
                    log_updated = True
                    triggered += 1
            else:
                last = log.get(s['代號'], '')
                print(f"  ⏳ 冷卻中 {s['代號']} {s['名稱']}  即時:{price} < 月低:{s['當月最低價']}  (上次通知:{last[:16]})")
        else:
            print(f"  ✅ {s['代號']} {s['名稱']}  即時:{price}  月低:{s['當月最低價']}")

    # 儲存更新後的通知紀錄
    if log_updated:
        save_alert_log(log)
        print(f"\n  💾 通知紀錄已更新 → {ALERT_LOG_FILE}")

    print("-" * 55)
    print(f"✅ 完成，本次觸價通知 {triggered} 檔")


if __name__ == '__main__':
    main()
