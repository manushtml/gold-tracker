import os
import json
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from gold_tracker_bot import get_current_price, get_previous_close, load_data, save_data

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')

if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    print("警告：未設定 LINE_CHANNEL_ACCESS_TOKEN 或 LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN) if LINE_CHANNEL_ACCESS_TOKEN else None
handler = WebhookHandler(LINE_CHANNEL_SECRET) if LINE_CHANNEL_SECRET else None

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    
    try:
        if handler:
            handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    reply_text = ""
    
    # 取得來源 ID (User ID 或 Group ID)
    source_id = event.source.group_id if hasattr(event.source, 'group_id') else event.source.user_id
    
    if text in ['/status', '查詢狀態']:
        data = load_data()
        target_price = data.get('target_price', 2600)
        current_price = get_current_price()
        reply_text = f"【目前狀態】\n設定的目標買進價為：{target_price} 元/公克\n"
        if current_price:
            reply_text += f"當前即時賣出價為：{current_price} 元/公克"
        
        # 記錄這個群組 ID，方便之後主動推播
        print(f"收到來自 {source_id} 的狀態查詢")
        
    elif text.startswith('/set_price ') or text.startswith('設定目標價格 '):
        try:
            parts = text.split()
            new_price = int(parts[1])
            data = load_data()
            data['target_price'] = new_price
            save_data(data)
            reply_text = f"✅ 已成功將目標買進價格更新為：{new_price} 元/公克"
        except (IndexError, ValueError):
            reply_text = "❌ 格式錯誤。請使用：\n/set_price 2600\n或\n設定目標價格 2600"
            
    elif text in ['/price', '查詢金價']:
        current_price = get_current_price()
        if current_price:
            reply_text = f"💰 當前台銀黃金存摺賣出價：{current_price} 元/公克"
        else:
            reply_text = "❌ 無法取得當前金價，請稍後再試。"
            
    elif text in ['/history', '查詢歷史']:
        prev_date, prev_price = get_previous_close()
        if prev_price:
            reply_text = f"📊 昨日收盤價 ({prev_date})：{prev_price} 元/公克"
        else:
            reply_text = "❌ 無法取得歷史金價，請稍後再試。"
            
    elif text == '/help':
        reply_text = "【黃金追蹤小幫手指令】\n" \
                     "1. /status 或 查詢狀態\n" \
                     "2. /price 或 查詢金價\n" \
                     "3. /history 或 查詢歷史\n" \
                     "4. /set_price [價格] 或 設定目標價格 [價格]"

    if reply_text:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
