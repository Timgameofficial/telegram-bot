# Улучшённая и отлаженная версия бота (исправлены ошибки с datetime и мелкие правки).
# Сохраняйте как bott_enhanced_fixed.py и запускайте вместо предыдущего файла.
# Основные правки:
# - Исправлены все некорректные обращения к datetime (убрано datetime.datetime.datetime).
# - Немного улучшено логирование старта при отсутствии TOKEN/ADMIN_ID.
# - Небольшие защитные проверки (TOKEN) в местах отправки.
#
# Примечание: оставил прежнюю архитектуру (init-once в before_request и буфер media_group).
# Если используете gunicorn с >1 workers — рекомендую настроить Redis/shared state или WEB_CONCURRENCY=1 при тестах.

import os
import time
import json
import requests
import threading
import traceback
import datetime
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, request, abort
from html import escape
from typing import Dict, Any, Tuple, Optional, List

# ----- Логи -----
logger = logging.getLogger("bot")
logger.setLevel(logging.INFO)
log_handler = RotatingFileHandler("bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
log_formatter = logging.Formatter("%(asctime)s\t%(levelname)s\t%(message)s")
log_handler.setFormatter(log_formatter)
logger.addHandler(log_handler)

# Диагностика (отдельные файлы)
STARTUP_LOG = "debug_startup.log"
UPDATES_LOG = "debug_updates.log"
WEBHOOK_INFO_LOG = "debug_webhook_info.log"

def _write_file(path: str, content: str):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(content + "\n")
    except Exception:
        logger.exception("Failed to write diagnostics file: %s", path)

def _mask_token(t: str) -> str:
    if not t:
        return "<EMPTY>"
    if len(t) <= 10:
        return t[:3] + "..." + t[-3:]
    return t[:4] + "..." + t[-4:]

def log_startup_info():
    try:
        token = os.getenv("API_TOKEN", "")
        admin = os.getenv("ADMIN_ID", "")
        webhook = os.getenv("WEBHOOK_URL", "")
        lines = [
            f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"API_TOKEN present: {'yes' if token else 'no'}",
            f"API_TOKEN: {_mask_token(token)}",
            f"ADMIN_ID: {admin}",
            f"WEBHOOK_URL: {webhook}",
            "-"*60
        ]
        _write_file(STARTUP_LOG, "\n".join(lines))
        logger.info("Diagnostics: startup info logged")
    except Exception:
        logger.exception("Diagnostics: failed to log startup info")

def log_raw_update(data_raw: str, src_ip: Optional[str] = None):
    try:
        now = time.strftime('%Y-%m-%d %H:%M:%S')
        header = f"--- {now} from {src_ip or '-'} ---"
        try:
            parsed = json.loads(data_raw)
            body = json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception:
            body = data_raw
        _write_file(UPDATES_LOG, header + "\n" + body + "\n")
    except Exception:
        logger.exception("Diagnostics: failed to log raw update")

def log_get_webhook_info():
    try:
        token = os.getenv("API_TOKEN", "")
        if not token:
            logger.warning("Diagnostics: API_TOKEN not set; cannot call getWebhookInfo")
            return
        r = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=6)
        txt = r.text if r is not None else "<no response>"
        _write_file(WEBHOOK_INFO_LOG, f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}\nAPI_TOKEN: {_mask_token(token)}\nresponse:\n{txt}\n" + ("-"*60))
        logger.info("Diagnostics: getWebhookInfo written")
    except Exception:
        logger.exception("Diagnostics: failed to call getWebhookInfo")

# ----- Конфигурация -----
TOKEN = os.getenv("API_TOKEN", "").strip()
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
except Exception:
    ADMIN_ID = 0
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
PORT = int(os.getenv("PORT", "5000"))

if not TOKEN:
    logger.warning("API_TOKEN is not set. Bot will not be able to send messages.")
if not ADMIN_ID:
    logger.warning("ADMIN_ID is not set or zero. Reply flows will not work until ADMIN_ID is configured.")

# ----- Настройки HTTP -----
HTTP_TIMEOUT = 6
RETRY_DELAY = 0.5
RETRIES = 2

def _post_with_retries(url: str, data: dict = None, files: dict = None, json_body: dict = None):
    for attempt in range(RETRIES + 1):
        try:
            if json_body is not None:
                resp = requests.post(url, json=json_body, timeout=HTTP_TIMEOUT)
            else:
                resp = requests.post(url, data=data, files=files, timeout=HTTP_TIMEOUT)
            return resp
        except Exception as e:
            logger.exception("HTTP request failed on attempt %s: %s", attempt, e)
            if attempt < RETRIES:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                return None

def send_message(chat_id: int, text: str, reply_markup: dict = None, parse_mode: Optional[str] = None):
    if not TOKEN:
        logger.warning("send_message called but TOKEN is not set")
        return None
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    if parse_mode:
        payload['parse_mode'] = parse_mode
    resp = _post_with_retries(url, data=payload)
    if resp is None:
        logger.warning("send_message request failed")
        return None
    if not resp.ok:
        logger.warning("send_message not OK: %s", resp.text)
    return resp

def send_chat_action(chat_id: int, action: str = 'typing'):
    if not TOKEN:
        return
    try:
        _post_with_retries(f"https://api.telegram.org/bot{TOKEN}/sendChatAction", data={'chat_id': chat_id, 'action': action})
    except Exception:
        logger.exception("send_chat_action failed")

# ----- Меню и состояния -----
MAIN_MENU = [
    "✨ Головне",
    "📢 Про нас",
    "🕰️ Графік роботи",
    "📝 Повідомити про подію",
    "📊 Статистика подій",
    "📣 Реклама"
]

ADMIN_SUBCATEGORIES = [
    "🏗️ Техногенні",
    "🌪️ Природні",
    "👥 Соціальні",
    "⚔️ Воєнні",
    "🕵️‍♂️ Розшук",
    "📦 Інше"
]

def get_reply_buttons():
    return {
        "keyboard": [
            [{"text": "📣 Реклама"}],
            [{"text": "📢 Про нас"}, {"text": "🕰️ Графік роботи"}],
            [{"text": "📝 Повідомити про подію"}, {"text": "📊 Статистика подій"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

def get_admin_subcategory_buttons():
    return {"keyboard": [[{"text": cat}] for cat in ADMIN_SUBCATEGORIES], "resize_keyboard": True, "one_time_keyboard": True}

state_lock = threading.Lock()
waiting_for_admin_message = set()      # user_chat_id -> waiting for admin message flow
user_admin_category: Dict[int, str] = {}
waiting_for_ad_message = set()        # user_chat_id -> waiting for ad message flow
waiting_for_admin: Dict[int, int] = {}  # admin_id -> user_id to reply

# ----- DB (из прошлых версий) -----
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL:
    db_url = DATABASE_URL
else:
    default_sqlite = os.path.join(os.path.dirname(os.path.abspath(__file__)), "events.db")
    db_url = f"sqlite:///{default_sqlite}"
_engine: Engine = None

def get_engine():
    global _engine
    if _engine is None:
        try:
            if db_url.startswith("sqlite:///"):
                _engine = create_engine(db_url, connect_args={"check_same_thread": False}, future=True)
            else:
                _engine = create_engine(db_url, future=True)
            logger.info("[db] using %s", db_url)
        except Exception:
            logger.exception("get_engine failed")
            raise
    return _engine

def init_db():
    try:
        engine = get_engine()
        create_sql = """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            dt TEXT NOT NULL
        );
        """
        with engine.begin() as conn:
            conn.execute(text(create_sql))
        logger.info("DB initialized")
    except Exception:
        logger.exception("init_db failed")

def save_event(category: str):
    try:
        engine = get_engine()
        now = datetime.datetime.utcnow().isoformat()
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO events (category, dt) VALUES (:cat, :dt)"), {"cat": category, "dt": now})
    except Exception:
        logger.exception("save_event failed")

def get_stats():
    # minimal safe stats: return zeros if any failure
    try:
        engine = get_engine()
        now = datetime.datetime.utcnow()
        week_threshold = (now - datetime.timedelta(days=7)).isoformat()
        month_threshold = (now - datetime.timedelta(days=30)).isoformat()
        res = {cat: {'week': 0, 'month': 0} for cat in ADMIN_SUBCATEGORIES}
        with engine.connect() as conn:
            wk = conn.execute(text("SELECT category, COUNT(*) as cnt FROM events WHERE dt >= :week GROUP BY category"), {"week": week_threshold}).all()
            mo = conn.execute(text("SELECT category, COUNT(*) as cnt FROM events WHERE dt >= :month GROUP BY category"), {"month": month_threshold}).all()
            for row in wk:
                if row[0] in res:
                    res[row[0]]['week'] = int(row[1])
            for row in mo:
                if row[0] in res:
                    res[row[0]]['month'] = int(row[1])
        return res
    except Exception:
        logger.exception("get_stats failed")
        return {cat: {'week': 0, 'month': 0} for cat in ADMIN_SUBCATEGORIES}

# ----- Helpers build_admin_info simplified -----
def build_admin_info(message: dict, category: Optional[str] = None) -> str:
    try:
        user = message.get('from', {})
        first = user.get('first_name', '') or ""
        last = user.get('last_name', '') or ""
        username = user.get('username')
        user_id = user.get('id')
        text = message.get('text') or message.get('caption') or ''
        parts = ["<pre>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</pre>", "<b>📩 Нове повідомлення від користувача</b>", ""]
        if category:
            parts.append(f"<b>Категорія:</b> {escape(category)}")
        display_name = (first + (" " + last if last else "")).strip() or "Без імені"
        parts += [f"<b>Ім'я:</b> {escape(display_name)}", f"<b>ID:</b> {escape(str(user_id)) if user_id is not None else '-'}"]
        if username:
            parts.append(f"<b>Username:</b> @{escape(username)}")
        parts += [
            f"<b>Текст / Опис:</b>",
            "<pre>{}</pre>".format(escape(text)) if text else "<i>Немає тексту</i>",
            "<pre>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</pre>"
        ]
        return "\n".join(parts)
    except Exception:
        logger.exception("build_admin_info failed")
        return "Нове повідомлення."

# ----- Media group buffering -----
MEDIA_GROUP_COLLECT_DELAY = 1.5  # seconds to wait for album parts

# key = (chat_id, media_group_id)
media_group_buffers: Dict[Tuple[int, str], Dict[str, Any]] = {}

def _buffer_media_group(chat_id: int, media_group_id: str, message: Dict[str, Any], origin: str, target_user: Optional[int] = None, purpose: Optional[str] = None):
    key = (chat_id, media_group_id)
    with state_lock:
        entry = media_group_buffers.get(key)
        if entry is None:
            entry = {'messages': [], 'timer': None, 'origin': origin, 'target_user': target_user, 'purpose': purpose}
            media_group_buffers[key] = entry
            t = threading.Timer(MEDIA_GROUP_COLLECT_DELAY, _process_media_group, args=(key,))
            entry['timer'] = t
            t.start()
        entry['messages'].append(message)
        if target_user:
            entry['target_user'] = target_user
        if purpose:
            entry['purpose'] = purpose
        logger.debug("Buffered media_group %s from %s (purpose=%s) count=%d", media_group_id, chat_id, purpose, len(entry['messages']))

def _process_media_group(key: Tuple[int, str]):
    try:
        with state_lock:
            entry = media_group_buffers.pop(key, None)
        if not entry:
            return
        messages = entry.get('messages', [])
        origin = entry.get('origin')
        target_user = entry.get('target_user')
        purpose = entry.get('purpose')
        messages.sort(key=lambda m: m.get('message_id', 0))
        if origin == 'user':
            first = messages[0]
            user_chat_id = first['chat']['id']
            admin_info = build_admin_info(first, category=None if purpose == 'ad' else user_admin_category.get(user_chat_id))
            reply_markup = {"inline_keyboard": [[{"text": "✉️ Відповісти", "callback_data": f"reply_{user_chat_id}"}]]}
            ok = _send_media_group_to_admin(ADMIN_ID, messages, admin_info, reply_markup)
            if not ok:
                send_message(ADMIN_ID, admin_info, reply_markup=reply_markup, parse_mode='HTML')
            # cleanup wait flags
            with state_lock:
                if purpose != 'ad' and user_chat_id in waiting_for_admin_message:
                    waiting_for_admin_message.discard(user_chat_id)
                    user_admin_category.pop(user_chat_id, None)
                if purpose == 'ad' and user_chat_id in waiting_for_ad_message:
                    waiting_for_ad_message.discard(user_chat_id)
            try:
                send_message(user_chat_id, "✅ Дякуємо! Ваше повідомлення надіслано адміністратору.")
            except Exception:
                pass
        elif origin == 'admin':
            if not target_user:
                logger.warning("admin origin but no target_user")
                return
            caption_text = None
            try:
                caption_text = messages[0].get('caption') or messages[0].get('text') or None
            except Exception:
                caption_text = None
            ok = _send_media_group_to_user(target_user, messages, caption_text=caption_text)
            try:
                if not ok:
                    send_message(target_user, "💬 Відповідь адміністратора.")
                send_message(ADMIN_ID, f"✅ Відповідь надіслано користувачу {target_user}")
            except Exception:
                pass
        else:
            logger.warning("Unknown media_group origin: %s", origin)
    except Exception:
        logger.exception("_process_media_group failed")

def _extract_media_type_and_file_id(msg: Dict[str, Any]):
    if 'photo' in msg and isinstance(msg['photo'], list) and msg['photo']:
        last = msg['photo'][-1]
        return 'photo', last.get('file_id')
    for k in ('video', 'document', 'audio', 'voice', 'animation', 'sticker'):
        if k in msg:
            obj = msg[k]
            if isinstance(obj, dict):
                return k, obj.get('file_id')
    return None, None

def _send_media_group_to_admin(admin_id: int, messages: List[Dict[str, Any]], admin_info_html: str, reply_markup: Optional[dict] = None) -> bool:
    if not admin_id or not TOKEN:
        return False
    base = f"https://api.telegram.org/bot{TOKEN}"
    media = []
    for idx, m in enumerate(messages[:10]):  # Telegram limit 10
        mtype, fid = _extract_media_type_and_file_id(m)
        if not mtype or not fid:
            continue
        item_type = "photo" if mtype == 'photo' else ("video" if mtype == 'video' else "photo")
        item = {"type": item_type, "media": fid}
        if idx == 0 and admin_info_html:
            caption = admin_info_html
            if len(caption) > 1000:
                caption = caption[:997] + "..."
            item['caption'] = caption
            item['parse_mode'] = 'HTML'
        media.append(item)
    if not media:
        return False
    try:
        resp = _post_with_retries(f"{base}/sendMediaGroup", json_body={'chat_id': admin_id, 'media': media})
        if resp and resp.ok:
            try:
                cnt = len(media)
                short = f"📩 Нове повідомлення від користувача (альбом: {cnt} елемент(ів)).\nНатисніть «✉️ Відповісти», щоб відповісти."
                send_message(admin_id, short, reply_markup=reply_markup)
            except Exception:
                logger.exception("Failed to send short notification")
            return True
        else:
            if resp is not None:
                logger.warning("_send_media_group_to_admin failure: %s %s", resp.status_code, resp.text)
            return False
    except Exception:
        logger.exception("_send_media_group_to_admin exception")
        return False

def _send_media_group_to_user(user_id: int, messages: List[Dict[str, Any]], caption_text: Optional[str] = None) -> bool:
    if not user_id or not TOKEN:
        return False
    base = f"https://api.telegram.org/bot{TOKEN}"
    media = []
    for idx, m in enumerate(messages[:10]):
        mtype, fid = _extract_media_type_and_file_id(m)
        if not mtype or not fid:
            continue
        item_type = "photo" if mtype == 'photo' else ("video" if mtype == 'video' else "photo")
        item = {"type": item_type, "media": fid}
        if idx == 0 and caption_text:
            caption = caption_text
            if len(caption) > 1000:
                caption = caption[:997] + "..."
            item['caption'] = caption
            item['parse_mode'] = 'HTML'
        media.append(item)
    if not media:
        return False
    try:
        resp = _post_with_retries(f"{base}/sendMediaGroup", json_body={'chat_id': user_id, 'media': media})
        if resp and resp.ok:
            return True
        else:
            if resp is not None:
                logger.warning("_send_media_group_to_user failed: %s %s", resp.status_code, resp.text)
            return False
    except Exception:
        logger.exception("_send_media_group_to_user exception")
        return False

# ----- Flask app & initialization -----
app = Flask(__name__)

def set_webhook_if_needed():
    if not TOKEN:
        logger.info("No TOKEN, skip set_webhook")
        return
    if not WEBHOOK_URL:
        logger.info("No WEBHOOK_URL, skip set_webhook")
        return
    try:
        r = requests.get(f"https://api.telegram.org/bot{TOKEN}/setWebhook", params={"url": WEBHOOK_URL}, timeout=6)
        if r.ok:
            logger.info("Webhook set to %s", WEBHOOK_URL)
        else:
            logger.warning("setWebhook returned %s", r.text)
    except Exception:
        logger.exception("set_webhook_if_needed failed")

_initialized = False
_init_lock = threading.Lock()

def start_background_once():
    init_db()
    log_startup_info()
    try:
        set_webhook_if_needed()
    except Exception:
        logger.exception("set_webhook_if_needed failed in background")

def ensure_initialized():
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        t = threading.Thread(target=start_background_once, daemon=True, name="init-once")
        t.start()
        _initialized = True
        logger.info("Initialization started in background")

@app.before_request
def before_any_request():
    try:
        ensure_initialized()
    except Exception:
        logger.exception("Initialization hook error")

@app.route("/health", methods=["GET"])
def health():
    return "ok", 200

@app.route("/webhook/<token>", methods=["POST"])
def webhook(token):
    try:
        data_raw = request.get_data(as_text=True)
        # diagnostics
        try:
            log_raw_update(data_raw, request.remote_addr if request else None)
        except Exception:
            logger.exception("Failed to log update")

        # verify token
        if not TOKEN or token != TOKEN:
            logger.warning("Invalid webhook token received")
            abort(403)

        update = json.loads(data_raw)
        # callback_query handling
        if 'callback_query' in update:
            call = update['callback_query']
            chat_id = call['from']['id']
            data = call.get('data', '')
            if data.startswith("reply_") and chat_id == ADMIN_ID:
                try:
                    user_id = int(data.split("_", 1)[1])
                    with state_lock:
                        waiting_for_admin[ADMIN_ID] = user_id
                    send_message(ADMIN_ID, f"✍️ Введіть відповідь для користувача {user_id}:")
                except Exception:
                    logger.exception("callback reply handling failed")
            return "ok", 200

        if 'message' not in update:
            return "ok", 200

        message = update['message']
        chat_id = message['chat']['id']
        from_id = message['from']['id']
        text = message.get('text', '')

        # admin replying to user
        with state_lock:
            admin_waiting_user = waiting_for_admin.get(ADMIN_ID)
        if from_id == ADMIN_ID and admin_waiting_user:
            mgid = message.get('media_group_id')
            if mgid:
                _buffer_media_group(from_id, mgid, message, origin='admin', target_user=admin_waiting_user)
                return "ok", 200
            # single message reply
            try:
                with state_lock:
                    waiting_for_admin.pop(ADMIN_ID, None)
                media_sent = send_media_to_user(admin_waiting_user, message, caption_text=text)
                if not media_sent:
                    send_message(admin_waiting_user, f"💬 Відповідь адміністратора:\n{text}")
                send_message(ADMIN_ID, f"✅ Відповідь надіслано користувачу {admin_waiting_user}")
            except Exception:
                logger.exception("admin reply send failed")
            return "ok", 200

        # Commands and menu
        if text == '/start':
            send_chat_action(chat_id, 'typing')
            time.sleep(0.25)
            send_message(chat_id, "✨ Ласкаво просимо!\n\nОберіть дію в меню нижче:", reply_markup=get_reply_buttons())
            return "ok", 200

        if text and text.strip().lower() == '/done':
            send_message(chat_id, "✅ Отримано. Якщо ви відправляли альбом — він скоро буде оброблений.")
            with state_lock:
                waiting_for_ad_message.discard(chat_id)
            return "ok", 200

        # Menu buttons
        if text in MAIN_MENU:
            if text == "✨ Головне":
                send_message(chat_id, "✨ Ви в головному меню.", reply_markup=get_reply_buttons())
            elif text == "📢 Про нас":
                send_message(chat_id, "Ми створюємо телеграм-ботів та сервіси для вашого бізнесу і життя.")
            elif text == "🕰️ Графік роботи":
                send_message(chat_id, "Ми працюємо цілодобово. Звертайтесь у будь-який час.")
            elif text == "📝 Повідомити про подію":
                send_message(chat_id, "Оберіть тип події:", reply_markup=get_admin_subcategory_buttons())
            elif text == "📊 Статистика подій":
                stats = get_stats()
                # simplified output
                out = ["<pre>Статистика подій:</pre>"]
                for cat in ADMIN_SUBCATEGORIES:
                    out.append(f"{cat}: week={stats[cat]['week']} month={stats[cat]['month']}")
                send_message(chat_id, "\n".join(out), parse_mode='HTML')
            elif text == "📣 Реклама":
                with state_lock:
                    waiting_for_ad_message.add(chat_id)
                send_message(chat_id, "📣 Ви обрали «Реклама». Надішліть текст та/або медіа (можна кілька фото/відео як альбом).", reply_markup=get_reply_buttons())
            return "ok", 200

        if text in ADMIN_SUBCATEGORIES:
            with state_lock:
                user_admin_category[chat_id] = text
                waiting_for_admin_message.add(chat_id)
            send_message(chat_id, f"Опишіть деталі події «{text}» (можна прикріпити фото/альбом):")
            return "ok", 200

        # If message is part of album
        mgid = message.get('media_group_id')
        with state_lock:
            in_ad = chat_id in waiting_for_ad_message
            in_event_flow = chat_id in waiting_for_admin_message

        if mgid and (in_ad or in_event_flow):
            purpose = 'ad' if in_ad else 'event'
            _buffer_media_group(chat_id, mgid, message, origin='user', purpose=purpose)
            if purpose == 'ad':
                with state_lock:
                    waiting_for_ad_message.discard(chat_id)
            return "ok", 200

        # If in ad flow and single message -> forward ad
        if in_ad:
            forward_ad_to_admin(message)
            with state_lock:
                waiting_for_ad_message.discard(chat_id)
            send_message(chat_id, "✅ Ваша рекламна заявка успішно надіслана. Дякуємо!", reply_markup=get_reply_buttons())
            return "ok", 200

        # If in event flow and single message -> forward event
        if in_event_flow:
            forward_user_message_to_admin(message)
            with state_lock:
                waiting_for_admin_message.discard(chat_id)
                user_admin_category.pop(chat_id, None)
            send_message(chat_id, "Ваша інформація передана. Дякуємо!", reply_markup=get_reply_buttons())
            return "ok", 200

        # default
        send_message(chat_id, "Щоб повідомити адміна або надіслати рекламу, скористайтесь меню.", reply_markup=get_reply_buttons())
        return "ok", 200

    except Exception:
        logger.exception("webhook outer exception")
        return "ok", 200

# ----- Forward helpers and single-media senders -----
def forward_user_message_to_admin(message: Dict[str, Any]):
    try:
        if not ADMIN_ID:
            send_message(message['chat']['id'], "⚠️ Адміністратор не налаштований.")
            return
        user_chat_id = message['chat']['id']
        category = user_admin_category.get(user_chat_id)
        admin_info = build_admin_info(message, category=category)
        reply_markup = {"inline_keyboard": [[{"text": "✉️ Відповісти", "callback_data": f"reply_{user_chat_id}"}]]}
        try:
            if category:
                save_event(category)
        except Exception:
            logger.exception("save_event failed")
        media_ok = send_media_to_admin(ADMIN_ID, message, admin_info, reply_markup=reply_markup)
        if not media_ok:
            send_message(ADMIN_ID, admin_info, reply_markup=reply_markup, parse_mode='HTML')
        send_message(user_chat_id, "✅ Дякуємо! Ваше повідомлення надіслано адміністратору.")
    except Exception:
        logger.exception("forward_user_message_to_admin failed")

def forward_ad_to_admin(message: Dict[str, Any]):
    try:
        if not ADMIN_ID:
            send_message(message['chat']['id'], "⚠️ Адміністратор не налаштований.")
            return
        user_chat_id = message['chat']['id']
        admin_info = build_admin_info(message, category=None)
        reply_markup = {"inline_keyboard": [[{"text": "✉️ Відповісти", "callback_data": f"reply_{user_chat_id}"}]]}
        media_ok = send_media_to_admin(ADMIN_ID, message, admin_info, reply_markup=reply_markup)
        if not media_ok:
            send_message(ADMIN_ID, admin_info, reply_markup=reply_markup, parse_mode='HTML')
        send_message(user_chat_id, "✅ Дякуємо! Ваша заявка надіслана.")
    except Exception:
        logger.exception("forward_ad_to_admin failed")

def send_media_to_admin(admin_id: int, message: Dict[str, Any], admin_info_html: str, reply_markup: dict = None) -> bool:
    try:
        if not TOKEN:
            return False
        base = f"https://api.telegram.org/bot{TOKEN}"
        caption = admin_info_html if admin_info_html else ""
        # photo
        if 'photo' in message and isinstance(message['photo'], list) and message['photo']:
            file_id = message['photo'][-1].get('file_id')
            if file_id:
                resp = _post_with_retries(f"{base}/sendPhoto", data={'chat_id': admin_id, 'photo': file_id, 'caption': caption, 'parse_mode': 'HTML'})
                if resp and resp.ok:
                    return True
        # document
        if 'document' in message and isinstance(message['document'], dict):
            file_id = message['document'].get('file_id')
            if file_id:
                resp = _post_with_retries(f"{base}/sendDocument", data={'chat_id': admin_id, 'document': file_id, 'caption': caption, 'parse_mode': 'HTML'})
                if resp and resp.ok:
                    return True
        # video
        if 'video' in message and isinstance(message['video'], dict):
            file_id = message['video'].get('file_id')
            if file_id:
                resp = _post_with_retries(f"{base}/sendVideo", data={'chat_id': admin_id, 'video': file_id, 'caption': caption, 'parse_mode': 'HTML'})
                if resp and resp.ok:
                    return True
        # other
        for key, endpoint, payload_key in [
            ('voice', 'sendVoice', 'voice'),
            ('audio', 'sendAudio', 'audio'),
            ('animation', 'sendAnimation', 'animation'),
            ('sticker', 'sendSticker', 'sticker')
        ]:
            if key in message and isinstance(message[key], dict):
                file_id = message[key].get('file_id')
                if file_id:
                    payload = {'chat_id': admin_id, payload_key: file_id}
                    if key != 'sticker':
                        payload['caption'] = caption
                        payload['parse_mode'] = 'HTML'
                    resp = _post_with_retries(f"{base}/{endpoint}", data=payload)
                    if resp and resp.ok:
                        return True
        return False
    except Exception:
        logger.exception("send_media_to_admin failed")
        return False

def send_media_to_user(user_id: int, message: Dict[str, Any], caption_text: Optional[str] = None) -> bool:
    try:
        if not TOKEN:
            return False
        base = f"https://api.telegram.org/bot{TOKEN}"
        caption = caption_text or ""
        if 'photo' in message and isinstance(message['photo'], list) and message['photo']:
            file_id = message['photo'][-1].get('file_id')
            if file_id:
                resp = _post_with_retries(f"{base}/sendPhoto", data={'chat_id': user_id, 'photo': file_id, 'caption': caption, 'parse_mode': 'HTML'})
                if resp and resp.ok:
                    return True
        if 'document' in message and isinstance(message['document'], dict):
            file_id = message['document'].get('file_id')
            if file_id:
                resp = _post_with_retries(f"{base}/sendDocument", data={'chat_id': user_id, 'document': file_id, 'caption': caption, 'parse_mode': 'HTML'})
                if resp and resp.ok:
                    return True
        if 'video' in message and isinstance(message['video'], dict):
            file_id = message['video'].get('file_id')
            if file_id:
                resp = _post_with_retries(f"{base}/sendVideo", data={'chat_id': user_id, 'video': file_id, 'caption': caption, 'parse_mode': 'HTML'})
                if resp and resp.ok:
                    return True
        for key, endpoint, payload_key in [
            ('voice', 'sendVoice', 'voice'),
            ('audio', 'sendAudio', 'audio'),
            ('animation', 'sendAnimation', 'animation'),
            ('sticker', 'sendSticker', 'sticker')
        ]:
            if key in message and isinstance(message[key], dict):
                file_id = message[key].get('file_id')
                if file_id:
                    payload = {'chat_id': user_id, payload_key: file_id}
                    if key != 'sticker':
                        payload['caption'] = caption
                        payload['parse_mode'] = 'HTML'
                    resp = _post_with_retries(f"{base}/{endpoint}", data=payload)
                    if resp and resp.ok:
                        return True
        return False
    except Exception:
        logger.exception("send_media_to_user failed")
        return False

# ----- Run (only for direct run, not for WSGI gunicorn) -----
if __name__ == "__main__":
    try:
        init_db()
    except Exception:
        logger.exception("init_db on startup failed")
    try:
        log_startup_info()
    except Exception:
        logger.exception("log_startup_info failed on startup")
    try:
        set_webhook_if_needed()
    except Exception:
        logger.exception("set_webhook_if_needed failed on startup")
    app.run(host="0.0.0.0", port=PORT)
