import os
import hmac
import hashlib
import base64
import json
import requests
from datetime import datetime
import pytz
from flask import Flask, request, abort
from gold_tracker_bot import (
    get_current_price,
    get_buy_back_price,
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


def build_portfolio_report(sell_price, buy_back_price):
    """計算並組合持倉報告（損益以本行買入價/回售價計算）"""
    data = load_data()
    purchases = data.get('purchases', [])

    if not purchases:
        return (
            "【持倉報告】\n"
            "─────────────────\n"
            "尚無進貨記錄。\n\n"
            "請使用以下指令新增：\n"
            "/buy [單價] [公克數]\n"
            "例：/buy 4500 10"
        )

    # 計算總持倉
    total_grams = sum(p['grams'] for p in purchases)
    total_cost = sum(p['price'] * p['grams'] for p in purchases)
    avg_cost = total_cost / total_grams if total_grams > 0 else 0

    # 損益以本行買入價（回售價）計算——代表現在賣出能拿到的金額
    buyback_value = buy_back_price * total_grams
    profit = buyback_value - total_cost
    profit_rate = (profit / total_cost * 100) if total_cost > 0 else 0

    tw_tz = pytz.timezone('Asia/Taipei')
    now_str = datetime.now(tw_tz).strftime("%Y/%m/%d %H:%M")

    msg = "【黃金持倉報告】\n"
    msg += f"更新時間：{now_str}\n"
    msg += "─────────────────\n"
    msg += f"持有總量：{total_grams:.2f} 公克\n"
    msg += f"平均成本：{avg_cost:,.0f} 元/公克\n"
    msg += f"總投入成本：{total_cost:,.0f} 元\n"
    msg += "─────────────────\n"
    msg += f"本行賣出價：{sell_price:,} 元/公克\n"
    msg += f"本行買入價：{buy_back_price:,} 元/公克\n"
    msg += f"回售市值：{buyback_value:,.0f} 元\n"
    msg += "─────────────────\n"

    if profit >= 0:
        msg += f"損益：+{profit:,.0f} 元\n"
        msg += f"投資報酬率：+{profit_rate:.2f}%"
    else:
        msg += f"損益：{profit:,.0f} 元\n"
        msg += f"投資報酬率：{profit_rate:.2f}%"

    return msg


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

    # 指令：記錄進貨
    elif text.startswith('/buy ') or text.startswith('進貨 '):
        try:
            parts = text.split()
            if len(parts) < 3:
                raise ValueError("參數不足")
            unit_price = float(parts[1])
            grams = float(parts[2])
            if unit_price <= 0 or grams <= 0:
                raise ValueError("數值需大於 0")

            tw_tz = pytz.timezone('Asia/Taipei')
            date_str = datetime.now(tw_tz).strftime("%Y-%m-%d")

            data = load_data()
            purchases = data.get('purchases', [])
            purchases.append({
                'date': date_str,
                'price': unit_price,
                'grams': grams,
                'total': unit_price * grams
            })
            data['purchases'] = purchases
            save_data(data)

            total_cost = unit_price * grams
            reply_text = (
                f"✅ 進貨記錄已新增！\n"
                f"─────────────────\n"
                f"日期：{date_str}\n"
                f"單價：{unit_price:,.0f} 元/公克\n"
                f"數量：{grams:.2f} 公克\n"
                f"總金額：{total_cost:,.0f} 元\n"
                f"─────────────────\n"
                f"輸入 /portfolio 查看持倉報告"
            )
        except (IndexError, ValueError) as e:
            reply_text = (
                "格式錯誤，請使用：\n"
                "/buy [單價] [公克數]\n\n"
                "範例：\n"
                "/buy 4500 10\n"
                "（以 4500 元/公克 買入 10 公克）"
            )

    # 指令：查詢持倉報告
    elif text in ['/portfolio', '持倉', '/持倉', '查詢持倉']:
        sell_price = get_current_price()
        buy_back_price = get_buy_back_price()
        if sell_price and buy_back_price:
            reply_text = build_portfolio_report(sell_price, buy_back_price)
        else:
            reply_text = "無法取得當前金價，請稍後再試。"

    # 指令：查詢進貨記錄
    elif text in ['/buys', '/進貨記錄', '進貨記錄']:
        data = load_data()
        purchases = data.get('purchases', [])
        if not purchases:
            reply_text = "尚無進貨記錄。\n\n使用 /buy [單價] [公克數] 新增。"
        else:
            reply_text = "【進貨記錄】\n─────────────────\n"
            for i, p in enumerate(purchases, 1):
                reply_text += (
                    f"{i}. {p['date']}\n"
                    f"   {p['price']:,.0f} 元/公克 × {p['grams']:.2f} 公克\n"
                    f"   = {p['price'] * p['grams']:,.0f} 元\n"
                )
            total_grams = sum(p['grams'] for p in purchases)
            total_cost = sum(p['price'] * p['grams'] for p in purchases)
            reply_text += f"─────────────────\n"
            reply_text += f"合計：{total_grams:.2f} 公克 / {total_cost:,.0f} 元"

    # 指令：刪除最後一筆進貨記錄
    elif text in ['/buy_undo', '/刪除進貨', '刪除最後進貨']:
        data = load_data()
        purchases = data.get('purchases', [])
        if not purchases:
            reply_text = "尚無進貨記錄可刪除。"
        else:
            removed = purchases.pop()
            data['purchases'] = purchases
            save_data(data)
            reply_text = (
                f"已刪除最後一筆進貨記錄：\n"
                f"{removed['date']} / "
                f"{removed['price']:,.0f} 元/公克 × {removed['grams']:.2f} 公克"
            )

    # 指令：說明
    elif text in ['/help', '說明', '/指令']:
        reply_text = (
            "【黃金追蹤小幫手指令說明】\n"
            "─────────────────\n"
            "/price　查詢即時賣出價\n"
            "/status　目標價與當前狀態\n"
            "/history　近 5 日收盤價\n"
            "/report　完整每日報告\n"
            "/set_price [數字]　設定目標價\n"
            "─────────────────\n"
            "【持倉管理】\n"
            "/buy [單價] [公克數]\n"
            "  → 記錄進貨\n"
            "  例：/buy 4500 10\n\n"
            "/portfolio　持倉獲利報告\n"
            "/buys　所有進貨記錄\n"
            "/buy_undo　刪除最後一筆\n"
            "─────────────────\n"
            "/help　顯示此說明"
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


@app.route("/notify", methods=['GET', 'POST'])
def notify():
    """每日通知端點，供 Railway Cron Job 呼叫"""
    # 簡單的安全驗證（可選）
    secret = request.args.get('secret', '') or request.headers.get('X-Notify-Secret', '')
    notify_secret = os.environ.get('NOTIFY_SECRET', '')
    if notify_secret and secret != notify_secret:
        return 'Unauthorized', 401

    try:
        from gold_tracker_bot import run_daily_notify
        run_daily_notify()
        return 'OK', 200
    except Exception as e:
        print(f"[錯誤] 執行每日通知失敗: {e}")
        return f'Error: {e}', 500


@app.route("/health", methods=['GET'])
def health():
    """健康檢查端點"""
    return 'OK', 200


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
