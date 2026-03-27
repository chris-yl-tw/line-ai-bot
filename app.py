"""
LINE 特約商店 AI 智慧客服 - Webhook 主程式
=========================================
功能：取代純關鍵字回覆，透過 Claude AI 自動辨識用戶意圖，
      提供個人化、有溫度的繁體中文回應。

環境需求：Python 3.9+
"""

import os
import logging
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent
from dotenv import load_dotenv

from ai_handler import generate_ai_response
from store_data import get_relevant_context

# ── 初始化 ────────────────────────────────────────────────────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

if not LINE_CHANNEL_SECRET or not LINE_CHANNEL_ACCESS_TOKEN:
    raise EnvironmentError("請確認 .env 中已設定 LINE_CHANNEL_SECRET 與 LINE_CHANNEL_ACCESS_TOKEN")

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


# ── 工具函式 ──────────────────────────────────────────────────────────────────

def get_display_name(user_id: str) -> str:
    """從 LINE 取得用戶暱稱（如取得失敗則回傳通用稱謂）"""
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            profile = line_bot_api.get_profile(user_id)
            return profile.display_name
    except Exception as e:
        logger.warning(f"無法取得用戶暱稱 ({user_id}): {e}")
        return "您"


def send_reply(reply_token: str, text: str):
    """發送文字回覆給用戶"""
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)],
            )
        )


# ── Webhook 路由 ──────────────────────────────────────────────────────────────

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    logger.info(f"收到 Webhook 請求，body 長度={len(body)}")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.error("簽章驗證失敗，請檢查 LINE_CHANNEL_SECRET")
        abort(400)

    return "OK"


# ── 事件處理 ──────────────────────────────────────────────────────────────────

@handler.add(FollowEvent)
def handle_follow(event):
    """新用戶加入時送出歡迎訊息"""
    user_id = event.source.user_id
    name = get_display_name(user_id)
    welcome = (
        f"嗨，{name}！👋 很高興認識您！\n\n"
        "我是特約商店專屬智慧助理，您可以直接問我：\n"
        "• 想查哪間商店的地址、電話或營業時間\n"
        "• 目前有哪些優惠或折扣活動\n\n"
        "請用自然的方式輸入問題就好，我會盡力幫您找到答案 😊"
    )
    send_reply(event.reply_token, welcome)


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    """處理用戶文字訊息：呼叫 AI 辨識意圖並回覆"""
    user_id = event.source.user_id
    user_message = event.message.text.strip()
    name = get_display_name(user_id)

    logger.info(f"用戶 [{name}] 傳訊：{user_message}")

    # 智慧選取相關商店資訊（只傳相關段落，大幅減少 token 用量）
    store_context = get_relevant_context(user_message)

    # 呼叫 AI 生成個人化回覆
    reply_text = generate_ai_response(
        user_name=name,
        user_message=user_message,
        store_context=store_context,
    )

    logger.info(f"AI 回覆：{reply_text[:80]}...")
    send_reply(event.reply_token, reply_text)


# ── 啟動 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    logger.info(f"LINE AI 客服啟動，監聽 port {port}")
    app.run(host="0.0.0.0", port=port)
