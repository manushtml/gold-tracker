import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz

# Line Bot API 設定（從環境變數讀取）
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '')
LINE_GROUP_ID = os.environ.get('LINE_GROUP_ID', '')

# 資料儲存檔案（記錄目標價格與群組 ID）
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data.json')


def load_data():
    """讀取本地設定資料"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'target_price': 2600, 'group_ids': []}


def save_data(data):
    """儲存設定資料"""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def get_current_price():
    """爬取台銀黃金存摺當前賣出價（新台幣/公克）"""
    url = "https://rate.bot.com.tw/gold?Lang=zh-TW"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        prices = soup.find_all("td", class_="text-right")
        if len(prices) >= 2:
            return int(prices[1].text.replace(',', '').strip())
    except Exception as e:
        print(f"[錯誤] 抓取即時價格失敗: {e}")
    return None


def get_previous_close():
    """爬取台銀黃金存摺前一營業日收盤賣出價"""
    url = "https://rate.bot.com.tw/gold/history/TWD/30"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        tbody = soup.find("tbody")
        if tbody:
            rows = tbody.find_all("tr")
            if rows:
                cols = rows[0].find_all("td")
                if len(cols) >= 5:
                    date_str = cols[0].text.strip()
                    sell_price = int(cols[4].text.replace(',', '').strip())
                    return date_str, sell_price
    except Exception as e:
        print(f"[錯誤] 抓取歷史價格失敗: {e}")
    return None, None


def get_history_prices(days=5):
    """爬取台銀黃金存摺近幾日歷史收盤賣出價"""
    url = "https://rate.bot.com.tw/gold/history/TWD/30"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    results = []
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        tbody = soup.find("tbody")
        if tbody:
            rows = tbody.find_all("tr")[:days]
            for row in rows:
                cols = row.find_all("td")
                if len(cols) >= 5:
                    date_str = cols[0].text.strip()
                    sell_price = int(cols[4].text.replace(',', '').strip())
                    results.append((date_str, sell_price))
    except Exception as e:
        print(f"[錯誤] 抓取歷史資料失敗: {e}")
    return results


def send_line_message(to_id, text):
    """透過 Line Bot API 發送訊息"""
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    payload = {
        "to": to_id,
        "messages": [{"type": "text", "text": text}]
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        if resp.status_code == 200:
            print(f"[成功] 訊息已發送至 {to_id}")
        else:
            print(f"[失敗] 發送訊息失敗 ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"[錯誤] 發送訊息時發生例外: {e}")


def build_daily_report():
    """組合每日金價報告訊息"""
    current_price = get_current_price()
    prev_date, prev_price = get_previous_close()
    data = load_data()
    target_price = data.get('target_price', 2600)

    if not current_price or not prev_price:
        return "無法取得金價資料，請稍後再試。"

    diff = current_price - prev_price
    diff_percent = (diff / prev_price) * 100

    if diff > 0:
        trend = f"漲 {abs(diff)} 元 ({diff_percent:+.2f}%)"
    elif diff < 0:
        trend = f"跌 {abs(diff)} 元 ({diff_percent:+.2f}%)"
    else:
        trend = f"持平 (0.00%)"

    tw_tz = pytz.timezone('Asia/Taipei')
    now_str = datetime.now(tw_tz).strftime("%Y/%m/%d %H:%M")

    msg = "【台銀黃金每日報價】\n"
    msg += f"時間：{now_str}\n"
    msg += "─────────────────\n"
    msg += f"當前賣出價：{current_price} 元/公克\n"
    msg += f"昨日收盤價：{prev_price} 元/公克 ({prev_date})\n"
    msg += f"今日走勢：{trend}\n"
    msg += f"目標買進價：{target_price} 元/公克\n"
    msg += "─────────────────\n"

    if current_price <= target_price:
        gap = abs(target_price - current_price)
        msg += f"已達標！低於目標價 {gap} 元\n建議登入網銀評估買進！"
    else:
        gap = current_price - target_price
        msg += f"未達標，距目標價還差 {gap} 元\n持續觀望中。"

    return msg


def run_daily_notify():
    """執行每日下午 3 點的通知（由 GitHub Actions 呼叫）"""
    print("[開始] 執行每日黃金價格通知...")

    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("[錯誤] 未設定 LINE_CHANNEL_ACCESS_TOKEN")
        return

    msg = build_daily_report()
    print(msg)

    data = load_data()
    group_ids = data.get('group_ids', [])

    # 若有設定環境變數中的 Group ID，也加入推播清單
    if LINE_GROUP_ID and LINE_GROUP_ID not in group_ids:
        group_ids.append(LINE_GROUP_ID)

    if not group_ids:
        print("[警告] 尚未設定任何群組 ID，無法推播通知。")
        print("[提示] 請先在 Line 群組中對 Bot 傳送任意訊息，系統將自動記錄群組 ID。")
        return

    for gid in group_ids:
        send_line_message(gid, msg)

    print(f"[完成] 已推播至 {len(group_ids)} 個群組/用戶")


if __name__ == "__main__":
    run_daily_notify()
