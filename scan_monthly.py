"""
台股月MACD第一根紅柱掃描器 - GitHub Actions 排程版
條件：第一根紅柱 + 有發股利 + 殖利率 >= 3% + 輸出當月最低價
每月5號自動執行，結果寫入 scan_result.txt
"""

import pandas as pd
import yfinance as yf
from datetime import datetime
import warnings
import requests
from io import StringIO

warnings.filterwarnings('ignore')

MIN_DIVIDEND_YIELD = 3.0  # 最低殖利率 %
OUTPUT_FILE = 'scan_result.txt'


# ────────────────────────────────────────────
# 股票清單
# ────────────────────────────────────────────

def fetch_twse_stocks():
    """抓取上市股票清單"""
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        url = 'https://isin.twse.com.tw/isin/C_public.jsp?strMode=2'
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, verify=False, timeout=30)
        response.encoding = 'big5'
        tables = pd.read_html(StringIO(response.text))
        df = tables[0]
        df = df[df[0].str.contains('　', na=False)]
        df[['stock_code', 'stock_name']] = df[0].str.split('　', n=1, expand=True)
        df = df[df['stock_code'].str.match(r'^\d{4}$', na=False)]
        df['stock_name'] = df['stock_name'].str.strip()
        return {f"{r['stock_code']}.TW": r['stock_name'] for _, r in df.iterrows()}
    except Exception as e:
        print(f"⚠️  抓取上市股票失敗: {e}")
        return {}


def fetch_tpex_stocks():
    """抓取上櫃股票清單"""
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        url = 'https://isin.twse.com.tw/isin/C_public.jsp?strMode=4'
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, verify=False, timeout=30)
        response.encoding = 'big5'
        tables = pd.read_html(StringIO(response.text))
        df = tables[0]
        df = df[df[0].str.contains('　', na=False)]
        df[['stock_code', 'stock_name']] = df[0].str.split('　', n=1, expand=True)
        df = df[df['stock_code'].str.match(r'^\d{4}$', na=False)]
        df['stock_name'] = df['stock_name'].str.strip()
        return {f"{r['stock_code']}.TWO": r['stock_name'] for _, r in df.iterrows()}
    except Exception as e:
        print(f"⚠️  抓取上櫃股票失敗: {e}")
        return {}


def get_all_stocks():
    print("🔄 抓取股票清單...")
    twse = fetch_twse_stocks()
    tpex = fetch_tpex_stocks()
    all_stocks = {**twse, **tpex}
    print(f"✅ 上市 {len(twse)} 檔 + 上櫃 {len(tpex)} 檔 = 共 {len(all_stocks)} 檔")
    return all_stocks


# ────────────────────────────────────────────
# 技術指標計算
# ────────────────────────────────────────────

def fetch_monthly_data(stock_code):
    try:
        ticker = yf.Ticker(stock_code)
        data = ticker.history(period='2y', interval='1mo')
        if data.empty or len(data) < 12:
            return None
        return data
    except:
        return None


def calculate_macd(data, fast=12, slow=26, signal=9):
    ema_fast = data['Close'].ewm(span=fast, adjust=False).mean()
    ema_slow = data['Close'].ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    data['MACD'] = macd
    data['MACD_Signal'] = signal_line
    data['MACD_Histogram'] = macd - signal_line
    return data


def check_first_macd_red(data):
    """判斷是否為第一根紅柱（柱狀體從負轉正）"""
    if len(data) < 2:
        return False, {}
    curr_h = data['MACD_Histogram'].iloc[-1]
    prev_h = data['MACD_Histogram'].iloc[-2]
    if not (curr_h > 0 and prev_h <= 0):
        return False, {}
    return True, {
        '當月柱狀體': round(curr_h, 4),
        '前月柱狀體': round(prev_h, 4),
        'MACD位階': '多頭' if data['MACD'].iloc[-1] > 0 else '空頭',
    }


def get_dividend_info(stock_code):
    try:
        ticker = yf.Ticker(stock_code)
        dividends = ticker.dividends
        if dividends is None or len(dividends) == 0:
            return {'有發股利': False, '近年股利': 0, '殖利率': 0}
        dividends = dividends[~dividends.index.duplicated(keep='last')]
        one_year_ago = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=365)
        recent_div = dividends[dividends.index >= one_year_ago].sum()
        hist = ticker.history(period='5d')
        if hist.empty:
            return {'有發股利': False, '近年股利': 0, '殖利率': 0}
        current_price = hist['Close'].iloc[-1]
        dividend_yield = (recent_div / current_price * 100) if current_price > 0 else 0
        if dividend_yield > 20:
            dividend_yield = 0
        return {
            '有發股利': recent_div > 0,
            '近年股利': round(recent_div, 2),
            '殖利率': round(dividend_yield, 2),
        }
    except:
        return {'有發股利': False, '近年股利': 0, '殖利率': 0}


# ────────────────────────────────────────────
# 主掃描流程
# ────────────────────────────────────────────

def scan(stock_dict):
    results = []
    total = len(stock_dict)

    for idx, (stock_code, stock_name) in enumerate(stock_dict.items(), 1):
        print(f"\r進度 {idx}/{total}  {stock_code} {stock_name}", end='', flush=True)

        data = fetch_monthly_data(stock_code)
        if data is None:
            continue

        data = calculate_macd(data)
        is_signal, macd_info = check_first_macd_red(data)
        if not is_signal:
            continue

        div_info = get_dividend_info(stock_code)

        # 篩選條件
        if not div_info['有發股利']:
            continue
        if div_info['殖利率'] < MIN_DIVIDEND_YIELD:
            continue

        results.append({
            '股票代號': stock_code.replace('.TW', '').replace('.TWO', ''),
            '股票名稱': stock_name,
            '市場': '上市' if stock_code.endswith('.TW') else '上櫃',
            '現價': round(data['Close'].iloc[-1], 2),
            '當月最低價': round(data['Low'].iloc[-1], 2),
            '近年股利': div_info['近年股利'],
            '殖利率%': div_info['殖利率'],
            'MACD位階': macd_info['MACD位階'],
            '當月柱狀體': macd_info['當月柱狀體'],
            '前月柱狀體': macd_info['前月柱狀體'],
        })

    print()  # 換行
    return results


# ────────────────────────────────────────────
# 寫入文字檔
# ────────────────────────────────────────────

def write_result(results):
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    lines = []
    lines.append('=' * 60)
    lines.append(f'台股月MACD第一根紅柱掃描結果')
    lines.append(f'執行時間：{now}')
    lines.append(f'篩選條件：第一根紅柱 ＋ 有發股利 ＋ 殖利率 ≥ {MIN_DIVIDEND_YIELD}%')
    lines.append(f'共找到 {len(results)} 檔')
    lines.append('=' * 60)

    if not results:
        lines.append('本月無符合條件的股票')
    else:
        # 欄位標題
        lines.append(
            f"{'代號':<6} {'名稱':<10} {'市場':<4} {'現價':>7} {'當月最低價':>10} "
            f"{'股利':>6} {'殖利率':>7} {'MACD位階':<6} {'柱狀體(本/前月)'}"
        )
        lines.append('-' * 80)
        for r in sorted(results, key=lambda x: x['殖利率%'], reverse=True):
            lines.append(
                f"{r['股票代號']:<6} {r['股票名稱']:<10} {r['市場']:<4} "
                f"{r['現價']:>7.2f} {r['當月最低價']:>10.2f} "
                f"{r['近年股利']:>6.2f} {r['殖利率%']:>6.1f}% "
                f"{r['MACD位階']:<6} "
                f"{r['當月柱狀體']:>8.4f} / {r['前月柱狀體']:>8.4f}"
            )

    lines.append('=' * 60)
    content = '\n'.join(lines)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(content)

    print(content)
    print(f"\n📄 結果已寫入 {OUTPUT_FILE}")


# ────────────────────────────────────────────
# 入口
# ────────────────────────────────────────────

if __name__ == '__main__':
    print(f"🚀 開始掃描  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    stock_dict = get_all_stocks()
    results = scan(stock_dict)
    write_result(results)
    print("✅ 完成")
