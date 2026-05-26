"""
LINE 特約商店 AI 智慧客服 - Webhook 主程式
=========================================
功能：取代純關鍵字回覆，透過 Claude AI 自動辨識用戶意圖，
提供個人化、有溫度的繁體中文回應。
支援 LINE Flex Message 卡片式呈現。

環境需求：Python 3.9+
"""

import os
import logging
from datetime import timedelta
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    FlexMessage,
    FlexBubble,
    FlexCarousel,
    FlexBox,
    FlexText,
    FlexButton,
    FlexSeparator,
    URIAction,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent
from dotenv import load_dotenv

from ai_handler import generate_ai_response
from store_data import (
    get_relevant_context,
    get_matched_store_card,
    is_list_request,
    STORE_CARDS,
)
from admin import admin_bp, log_interaction

# ── 初始化 ────────────────────────────────────────────────────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me-in-production")
app.permanent_session_lifetime = timedelta(days=7)

# 掛載後台 Blueprint
app.register_blueprint(admin_bp)

LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

if not LINE_CHANNEL_SECRET or not LINE_CHANNEL_ACCESS_TOKEN:
    raise EnvironmentError("請確認 .env 中已設定 LINE_CHANNEL_SECRET 與 LINE_CHANNEL_ACCESS_TOKEN")

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 無官網商店的預設連結（弈樂科技 LINE 官方帳號）
DEFAULT_STORE_URL = "https://line.me/R/ti/p/@310tjlvu"

# ── Flex Message 建構函式 ──────────────────────────────────────────────────────

def build_store_bubble(card: dict) -> FlexBubble:
    """建立單一商店的 Flex Bubble 卡片。"""
    url = card.get("url") or DEFAULT_STORE_URL
    return FlexBubble(
        body=FlexBox(
            layout="vertical",
            spacing="sm",
            contents=[
                FlexText(
                    text=card["category"],
                    size="xs",
                    color="#999999",
                ),
                FlexText(
                    text=card["name"],
                    weight="bold",
                    size="xl",
                    wrap=True,
                ),
                FlexText(
                    text=card["subtitle"],
                    size="sm",
                    color="#666666",
                    wrap=True,
                ),
                FlexSeparator(margin="md"),
                FlexText(
                    text=card["benefit"],
                    size="sm",
                    wrap=True,
                    margin="md",
                    color="#444444",
                ),
            ],
        ),
        footer=FlexBox(
            layout="vertical",
            spacing="sm",
            flex=0,
            contents=[
                FlexButton(
                    action=URIAction(label="更多資訊", uri=url),
                    style="primary",
                    color="#B22222",
                    height="sm",
                ),
            ],
        ),
    )

def build_single_flex(card: dict) -> FlexMessage:
    """建立單一商店的 FlexMessage。"""
    return FlexMessage(
        alt_text=f"{card['name']} 特約優惠",
        contents=build_store_bubble(card),
    )

def build_carousel_flex(cards: list, alt_text: str = "特約商店列表") -> FlexMessage:
    """建立多商店的 Flex Carousel（最多12個）。"""
    bubbles = [build_store_bubble(c) for c in cards[:12]]
    return FlexMessage(
        alt_text=alt_text,
        contents=FlexCarousel(contents=bubbles),
    )

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

def send_messages(reply_token: str, messages: list):
    """發送一或多則訊息（TextMessage / FlexMessage 皆可，上限5則）。"""
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=messages[:5],
            )
        )

def send_reply(reply_token: str, text: str):
    """發送純文字回覆給用戶。"""
    send_messages(reply_token, [TextMessage(text=text)])

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
    log_interaction(name, user_id, "[加入好友]", "follow", True)

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    """處理用戶文字訊息：支援 Flex Message 卡片及 AI 文字回覆"""
    import store_data as sd  # 重新讀取，以反映後台修改
    user_id = event.source.user_id
    user_message = event.message.text.strip()
    name = get_display_name(user_id)

    logger.info(f"用戶 [{name}] 傳訊：{user_message}")

    try:
        # ── 1. 偵測商店列表查詢 → 回傳各類別 Carousel ────────────────────────
        if sd.is_list_request(user_message):
            dining = [c for c in sd.STORE_CARDS if "餐飲" in c["category"]]
            others = [c for c in sd.STORE_CARDS if "餐飲" not in c["category"]]
            msgs = []
            if dining:
                msgs.append(build_carousel_flex(dining, "🍽️ 餐飲類特約商店"))
            if others:
                msgs.append(build_carousel_flex(others, "🛍️🎉🏥🏨 其他類特約商店"))
            if msgs:
                send_messages(event.reply_token, msgs)
                logger.info(f"送出商店列表 Carousel（{len(msgs)} 則）")
                log_interaction(name, user_id, user_message, "carousel", True)
            return

        # ── 2. 偵測特定商店 → 回傳 Flex 卡片 + AI 說明 ────────────────────────
        matched_card = sd.get_matched_store_card(user_message)
        store_context = sd.get_relevant_context(user_message)
        reply_text = generate_ai_response(
            user_name=name,
            user_message=user_message,
            store_context=store_context,
        )

        if matched_card:
            flex_msg = build_single_flex(matched_card)
            send_messages(event.reply_token, [flex_msg, TextMessage(text=reply_text)])
            logger.info(f"送出 Flex 卡片：{matched_card['name']} + AI 說明")
            log_interaction(name, user_id, user_message, f"flex:{matched_card['name']}", True)
        else:
            send_reply(event.reply_token, reply_text)
            logger.info(f"AI 回覆：{reply_text[:80]}...")
            log_interaction(name, user_id, user_message, "ai-text", True)

    except Exception as e:
        logger.error(f"處理訊息時發生錯誤：{e}", exc_info=True)
        log_interaction(name, user_id, user_message, "error", False)

# ── 啟動 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    logger.info(f"LINE AI 客服啟動，盡h�� port {port}")
    app.run(host="0.0.0.0", port=port)
