import os
import hmac
import hashlib
import base64
import json
import requests
from flask import Flask, request, abort
from gold_tracker_bot import (
    get_current_price,
    get_previous_close,
    get_history_prices,
    load_data,
    save_data,
    send_line_message,
    build_daily_report
)

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', '')


def verify_signature(body: bytes, signature: str) -> bool:
    """驗證 Line Webhook 簽名"""
    hash_val = hmac.new(
        LINE_CHANNEL_SECRET.encode('utf-8'),
        body,
        hashlib.sha256
    ).digest()
    expected = base64.b64encode(hash_val).decode('utf-8')
    return hmac.compare_digest(expected, signature)


def reply_message(reply_token: str, text: str):
    """使用 reply token 回覆訊息"""
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}]
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"[失敗] 回覆訊息失敗 ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"[錯誤] 回覆訊息例外: {e}")


def handle_text_message(event: dict):
    """處理文字訊息指令"""
    text = event.get('message', {}).get('text', '').strip()
    reply_token = event.get('replyToken', '')
    source = event.get('source', {})
    source_type = source.get('type', '')

    # 取得來源 ID（群組優先，其次是用戶）
    if source_type == 'group':
        source_id = source.get('groupId', '')
    elif source_type == 'room':
        source_id = source.get('roomId', '')
    else:
        source_id = source.get('userId', '')

    # 自動記錄群組 ID，供每日推播使用
    if source_id:
        data = load_data()
        group_ids = data.get('group_ids', [])
        if source_id not in group_ids:
            group_ids.append(source_id)
            data['group_ids'] = group_ids
            save_data(data)
            print(f"[記錄] 已新增群組/用戶 ID: {source_id}")

    reply_text = ""

    # 指令：查詢狀態
    if text in ['/status', '查詢狀態', '/狀態']:
        data = load_data()
        target_price = data.get('target_price', 3500)
        current_price = get_current_price()
        reply_text = "【目前狀態】\n"
        reply_text += f"目標買進價：{target_price} 元/公克\n"
        if current_price:
            diff = current_price - target_price
            reply_text += f"當前即時賣出價：{current_price} 元/公克\n"
            if diff <= 0:
                reply_text += f"已達標！低於目標價 {abs(diff)} 元"
            else:
                reply_text += f"距目標價還差 {diff} 元"
        else:
            reply_text += "（無法取得即時價格）"

    # 指令：設定目標價格
    elif text.startswith('/set_price ') or text.startswith('設定目標價格 '):
        try:
            parts = text.split()
            new_price = int(parts[-1])
            if new_price < 100 or new_price > 99999:
                reply_text = "價格設定範圍需在 100 ~ 99999 元之間，請重新輸入。"
            else:
                data = load_data()
                old_price = data.get('target_price', 3500)
                data['target_price'] = new_price
                save_data(data)
                reply_text = f"目標買進價格已更新！\n{old_price} 元 → {new_price} 元/公克"
        except (IndexError, ValueError):
            reply_text = "格式錯誤，請使用：\n/set_price 2600\n或\n設定目標價格 2600"

    # 指令：查詢即時金價
    elif text in ['/price', '查詢金價', '/金價']:
        current_price = get_current_price()
        if current_price:
            data = load_data()
            target_price = data.get('target_price', 3500)
            diff = current_price - target_price
            reply_text = f"台銀黃金存摺即時賣出價\n{current_price} 元/公克\n"
            if diff <= 0:
                reply_text += f"已達目標價！低於目標 {abs(diff)} 元"
            else:
                reply_text += f"距目標價還差 {diff} 元"
        else:
            reply_text = "無法取得當前金價，請稍後再試。"

    # 指令：查詢歷史金價
    elif text in ['/history', '查詢歷史', '/歷史']:
        history = get_history_prices(days=5)
        if history:
            reply_text = "【近 5 日台銀黃金收盤賣出價】\n"
            for date_str, price in history:
                reply_text += f"{date_str}：{price} 元/公克\n"
            reply_text = reply_text.strip()
        else:
            reply_text = "無法取得歷史金價，請稍後再試。"

    # 指令：今日完整報告
    elif text in ['/report', '今日報告', '/報告']:
        reply_text = build_daily_report()

    # 指令：說明
    elif text in ['/help', '說明', '/指令']:
        reply_text = (
            "【黃金追蹤小幫手指令說明】\n"
            "─────────────────\n"
            "/price 或 查詢金價\n"
            "  → 查詢台銀即時賣出價\n\n"
            "/status 或 查詢狀態\n"
            "  → 查詢目標價與當前狀態\n\n"
            "/history 或 查詢歷史\n"
            "  → 查詢近 5 日收盤價\n\n"
            "/report 或 今日報告\n"
            "  → 取得完整每日報告\n\n"
            "/set_price [數字]\n"
            "  → 設定目標買進價格\n"
            "  例：/set_price 2550\n\n"
            "/help 或 說明\n"
            "  → 顯示此說明"
        )

    if reply_text:
        reply_message(reply_token, reply_text)


@app.route("/callback", methods=['POST'])
def callback():
    """接收 Line Webhook 事件"""
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data()

    if LINE_CHANNEL_SECRET and not verify_signature(body, signature):
        abort(400)

    try:
        payload = json.loads(body.decode('utf-8'))
        events = payload.get('events', [])
        for event in events:
            if event.get('type') == 'message':
                msg_type = event.get('message', {}).get('type', '')
                if msg_type == 'text':
                    handle_text_message(event)
    except Exception as e:
        print(f"[錯誤] 處理 Webhook 事件失敗: {e}")

    return 'OK', 200


@app.route("/health", methods=['GET'])
def health():
    """健康檢查端點"""
    return 'OK', 200


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
