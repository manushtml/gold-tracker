import os
import sys
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz

# Line Bot API 設定
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_GROUP_ID = os.environ.get('LINE_GROUP_ID') # 如果要主動推播到群組，需要知道 Group ID 或 User ID

# 資料儲存檔案 (用於記錄目標價格)
DATA_FILE = 'data.json'

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'target_price': 2600} # 預設目標價

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def get_current_price():
    url = "https://rate.bot.com.tw/gold?Lang=zh-TW"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        prices = soup.find_all("td", class_="text-right")
        if len(prices) >= 2:
            return int(prices[1].text.replace(',', '').strip())
    except Exception as e:
        print(f"抓取即時價格錯誤: {e}")
    return None

def get_previous_close():
    url = "https://rate.bot.com.tw/gold/history/TWD/30"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        tbody = soup.find("tbody")
        if tbody:
            first_row = tbody.find_all("tr")[0]
            cols = first_row.find_all("td")
            date_str = cols[0].text.strip()
            sell_price = int(cols[4].text.replace(',', '').strip())
            return date_str, sell_price
    except Exception as e:
        print(f"抓取歷史價格錯誤: {e}")
    return None, None

def send_line_message(to, text):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    data = {
        "to": to,
        "messages": [{"type": "text", "text": text}]
    }
    response = requests.post(url, headers=headers, json=data)
    print(f"發送訊息狀態碼: {response.status_code}")
    if response.status_code != 200:
        print(f"發送訊息失敗: {response.text}")

def check_and_notify():
    current_price = get_current_price()
    prev_date, prev_price = get_previous_close()
    data = load_data()
    target_price = data.get('target_price', 2600)
    
    if not current_price or not prev_price:
        print("無法取得價格資料。")
        return
        
    diff = current_price - prev_price
    diff_percent = (diff / prev_price) * 100
    sign = "漲" if diff > 0 else "跌" if diff < 0 else "平"
    diff_str = f"{sign} {abs(diff)} 元 ({diff_percent:+.2f}%)"
    
    tw_tz = pytz.timezone('Asia/Taipei')
    now_str = datetime.now(tw_tz).strftime("%Y/%m/%d %H:%M")
    
    msg = f"【台銀黃金每日報價】\n"
    msg += f"時間：{now_str}\n"
    msg += f"----------------------\n"
    msg += f"當前賣出價：{current_price} 元/公克\n"
    msg += f"昨日收盤價：{prev_price} 元/公克 ({prev_date})\n"
    msg += f"今日走勢：{diff_str}\n"
    msg += f"目標買進價：{target_price} 元/公克\n"
    msg += f"----------------------\n"
    
    if current_price <= target_price:
        msg += f"💡 狀態：已達標！低於目標價，建議登入網銀評估買進。"
    else:
        msg += f"💡 狀態：未達標，持續觀望。"
        
    if LINE_GROUP_ID:
        send_line_message(LINE_GROUP_ID, msg)
    else:
        print("未設定 LINE_GROUP_ID，無法發送通知。")
        print(msg)

if __name__ == "__main__":
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("請設定 LINE_CHANNEL_ACCESS_TOKEN 環境變數")
        sys.exit(1)
    check_and_notify()
