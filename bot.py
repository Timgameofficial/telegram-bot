# contents: бот с поддержкой media_group, пересылкой пользователю/админу и инициализацией при первом запросе.
# Обновлён: упрощён и приведён в соответствие поведение команды "📣 Реклама" — теперь использует ту же логику,
# что и "📝 Повідомити про подію": режим ожидания одного сообщения/альбома, поддержка media_group.
import os
import time
import json
import requests
import threading
import traceback
import datetime
import random
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, request, abort
from html import escape
from typing import Dict, Any, Tuple, List

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# ====== Логирование ======
logger = logging.getLogger("bot")
logger.setLevel(logging.INFO)
log_handler = RotatingFileHandler("bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
log_formatter = logging.Formatter("%(asctime)s\t%(levelname)s\t%(message)s")
log_handler.setFormatter(log_formatter)
logger.addHandler(log_handler)

def MainProtokol(s, ts='Запис'):
    dt = time.strftime('%d.%m.%Y %H:%M:') + '00'
    line = f"{dt};{ts};{s}"
    try:
        with open('log.txt', 'a', encoding='utf-8') as f:
            f.write(line + "\n")
    except Exception:
        logger.exception("Ошибка записи в log.txt")
    logger.info(line)

def cool_error_handler(exc, context="", send_to_telegram=False):
    exc_type = type(exc).__name__
    tb_str = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    readable_msg = (
        "\n" + "=" * 40 + "\n"
        f"[ERROR] {exc_type}\n"
        f"Context: {context}\n"
        f"Time: {ts}\n"
        "Traceback:\n"
        f"{tb_str}"
        + "=" * 40 + "\n"
    )
    try:
        with open('critical_errors.log', 'a', encoding='utf-8') as f:
            f.write(readable_msg)
    except Exception:
        logger.exception("Не удалось записать в 'critical_errors.log'")
    try:
        MainProtokol(f"{exc_type}: {str(exc)}", ts='ERROR')
    except Exception:
        logger.exception("MainProtokol вернул ошибку")
    logger.error(readable_msg)
    if send_to_telegram:
        try:
            admin_id = int(os.getenv("ADMIN_ID", "0") or 0)
            token = os.getenv("API_TOKEN")
            if admin_id and token:
                try:
                    requests.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        data={
                            "chat_id": admin_id,
                            "text": f"⚠️ Критична ошибка!\nТип: {exc_type}\nКонтекст: {context}\n\n{str(exc)}",
                            "disable_web_page_preview": True
                        },
                        timeout=5
                    )
                except Exception:
                    logger.exception("Не удалось отправить уведомление в Telegram")
        except Exception:
            logger.exception("Ошибка при подготовке уведомления в Telegram")

# ====== Конфигурация / состояние ======
TOKEN = os.getenv("API_TOKEN")
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
except Exception:
    ADMIN_ID = 0
    MainProtokol("Invalid ADMIN_ID env variable, defaulting to 0", "StartupWarning")

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()

state_lock = threading.Lock()
waiting_for_admin_message = set()
user_admin_category: Dict[int, str] = {}
waiting_for_ad_message = set()
waiting_for_admin: Dict[int, int] = {}  # admin_id -> user_id awaiting reply

# Буфер для media_group (альбомов)
media_group_buffers: Dict[Tuple[int, str], Dict[str, Any]] = {}
MEDIA_GROUP_COLLECT_DELAY = 1.5  # seconds

# DB
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
            logger.info(f"[DEBUG] Using DB URL: {db_url}")
        except Exception as e:
            cool_error_handler(e, "get_engine")
            raise
    return _engine

def init_db():
    try:
        engine = get_engine()
        create_sql = """
        CREATE TABLE IF NOT EXISTS events (
            id SERIAL PRIMARY KEY,
            category TEXT NOT NULL,
            dt TIMESTAMP NOT NULL
        );
        """
        if engine.dialect.name == "sqlite":
            create_sql = """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                dt TEXT NOT NULL
            );
            """
        with engine.begin() as conn:
            conn.execute(text(create_sql))
    except Exception as e:
        cool_error_handler(e, "init_db")

def save_event(category):
    try:
        engine = get_engine()
        now = datetime.datetime.utcnow()
        if engine.dialect.name == "sqlite":
            dt_val = now.isoformat()
            insert_sql = "INSERT INTO events (category, dt) VALUES (:cat, :dt)"
            with engine.begin() as conn:
                conn.execute(text(insert_sql), {"cat": category, "dt": dt_val})
        else:
            insert_sql = "INSERT INTO events (category, dt) VALUES (:cat, :dt)"
            with engine.begin() as conn:
                conn.execute(text(insert_sql), {"cat": category, "dt": now})
    except Exception as e:
        cool_error_handler(e, "save_event")

def get_stats():
    res = {cat: {'week': 0, 'month': 0} for cat in ADMIN_SUBCATEGORIES}
    try:
        engine = get_engine()
        now = datetime.datetime.utcnow()
        week_threshold = now - datetime.timedelta(days=7)
        month_threshold = now - datetime.timedelta(days=30)

        with engine.connect() as conn:
            if engine.dialect.name == "sqlite":
                week_ts = week_threshold.isoformat()
                month_ts = month_threshold.isoformat()
                q_week = text("SELECT category, COUNT(*) as cnt FROM events WHERE dt >= :week GROUP BY category")
                q_month = text("SELECT category, COUNT(*) as cnt FROM events WHERE dt >= :month GROUP BY category")
                wk = conn.execute(q_week, {"week": week_ts}).all()
                mo = conn.execute(q_month, {"month": month_ts}).all()
            else:
                q_week = text("SELECT category, COUNT(*) as cnt FROM events WHERE dt >= :week GROUP BY category")
                q_month = text("SELECT category, COUNT(*) as cnt FROM events WHERE dt >= :month GROUP BY category")
                wk = conn.execute(q_week, {"week": week_threshold}).all()
                mo = conn.execute(q_month, {"month": month_threshold}).all()

            for row in wk:
                cat = row[0]
                cnt = int(row[1])
                if cat in res:
                    res[cat]['week'] = cnt
            for row in mo:
                cat = row[0]
                cnt = int(row[1])
                if cat in res:
                    res[cat]['month'] = cnt
        return res
    except Exception as e:
        cool_error_handler(e, "get_stats")
        return None

# ====== Простейшие HTTP helper/timeout/retries ======
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
            logger.exception("HTTP request failed")
            try:
                MainProtokol(f"_post_with_retries exception: {str(e)}", "HTTP")
            except Exception:
                pass
            if attempt < RETRIES:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                return None

def send_chat_action(chat_id, action='typing'):
    if not TOKEN:
        return
    try:
        _post_with_retries(f'https://api.telegram.org/bot{TOKEN}/sendChatAction', data={'chat_id': chat_id, 'action': action})
    except Exception:
        logger.exception("send_chat_action failed")

def send_message(chat_id, text, reply_markup=None, parse_mode=None):
    if not TOKEN:
        logger.warning("send_message called but TOKEN not set")
        return None
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage'
    payload = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    if parse_mode:
        payload['parse_mode'] = parse_mode
    resp = _post_with_retries(url, data=payload)
    if resp is None:
        MainProtokol("send_message: request failed", 'Помилка надсилання')
        return None
    if not resp.ok:
        MainProtokol(resp.text, 'Помилка надсилання')
    return resp

def _get_reply_markup_for_admin(user_id: int):
    return {"inline_keyboard": [[{"text": "✉️ Відповісти", "callback_data": f"reply_{user_id}"}]]}

def build_admin_info(message: dict, category: str = None) -> str:
    try:
        user = message.get('from', {})
        chat = message.get('chat', {})
        first = user.get('first_name', '') or ""
        last = user.get('last_name', '') or ""
        username = user.get('username')
        user_id = user.get('id')
        lang = user.get('language_code', '-')
        is_bot = user.get('is_bot', False)
        is_premium = user.get('is_premium', None)

        chat_type = chat.get('type', '-')
        chat_title = chat.get('title') or ''
        msg_id = message.get('message_id')
        msg_date = message.get('date')
        try:
            date_str = datetime.datetime.utcfromtimestamp(int(msg_date)).strftime('%Y-%m-%d %H:%M:%S UTC') if msg_date else '-'
        except Exception:
            date_str = str(msg_date or '-')

        text = message.get('text') or message.get('caption') or ''
        entities = message.get('entities') or message.get('caption_entities') or []
        entities_summary = [ent.get('type') for ent in entities if ent.get('type')]
        entities_summary = ", ".join(entities_summary) if entities_summary else "-"

        media_keys = []
        media_candidates = ['photo', 'video', 'document', 'audio', 'voice', 'animation', 'sticker', 'contact', 'location']
        for k in media_candidates:
            if k in message:
                media_keys.append(k)

        parts = ["<pre>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</pre>", "<b>📩 Нове повідомлення від користувача</b>", ""]
        if category:
            parts.append(f"<b>Категорія:</b> {escape(category)}")
        display_name = (first + (" " + last if last else "")).strip() or "Без імені"
        parts += [f"<b>Ім'я:</b> {escape(display_name)}", f"<b>ID:</b> {escape(str(user_id)) if user_id is not None else '-'}"]
        if username:
            parts.append(f"<b>Username:</b> @{escape(username)}")
        parts += [f"<b>Мова:</b> {escape(str(lang))}", f"<b>Is bot:</b> {escape(str(is_bot))}"]
        if is_premium is not None:
            parts.append(f"<b>Is premium:</b> {escape(str(is_premium))}")
        parts += [
            f"<b>Тип чату:</b> {escape(str(chat_type))}" + (f" ({escape(chat_title)})" if chat_title else ""),
            f"<b>Message ID:</b> {escape(str(msg_id))}",
            f"<b>Дата:</b> {escape(str(date_str))}",
            f"<b>Entities:</b> {escape(entities_summary)}",
            f"<b>Медіа:</b> {escape(','.join(media_keys) if media_keys else '-')}",
            "<b>Текст / Опис:</b>",
            "<pre>{}</pre>".format(escape(text)) if text else "<i>Немає тексту</i>",
            "",
            "<i>Повідомлення відформатовано для зручного перегляду.</i>",
            "<pre>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</pre>"
        ]
        return "\n".join(parts)
    except Exception as e:
        cool_error_handler(e, "build_admin_info")
        try:
            return f"Повідомлення від користувача. ID: {escape(str(message.get('from', {}).get('id', '-')))}"
        except Exception:
            return "Нове повідомлення."

# ====== Helpers media_group ======
def _buffer_media_group(chat_id: int, media_group_id: str, message: Dict[str, Any], origin: str, target_user: int = None, purpose: str = None):
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
        logger.debug(f"Buffered media_group {media_group_id} from chat {chat_id}, origin={origin}, purpose={purpose}. count={len(entry['messages'])}")

def _process_media_group(key: Tuple[int, str]):
    try:
        with state_lock:
            entry = media_group_buffers.pop(key, None)
        if not entry:
            return
        messages = entry.get('messages', [])
        origin = entry.get('origin')
        target_user = entry.get('target_user')
        purpose = entry.get('purpose', None)
        try:
            messages.sort(key=lambda m: m.get('message_id', 0))
        except Exception:
            pass

        if origin == 'user':
            if not messages:
                return
            first = messages[0]
            user_chat_id = first['chat']['id']
            if purpose == 'ad':
                admin_info = build_admin_info(first, category=None)
            else:
                category = user_admin_category.get(user_chat_id, 'Без категорії')
                admin_info = build_admin_info(first, category=category)
            reply_markup = _get_reply_markup_for_admin(user_chat_id)
            ok = _send_media_group_to_admin(ADMIN_ID, messages, admin_info, reply_markup)
            if not ok:
                send_message(ADMIN_ID, admin_info, reply_markup=reply_markup, parse_mode='HTML')
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
                logger.warning("process_media_group admin origin but no target_user")
                return
            caption_text = None
            try:
                if messages and isinstance(messages[0], dict):
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
    except Exception as e:
        cool_error_handler(e, context="_process_media_group")

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

def _send_media_group_to_admin(admin_id: int, messages: list, admin_info_html: str, reply_markup: dict = None) -> bool:
    if not admin_id:
        return False
    base = f"https://api.telegram.org/bot{TOKEN}"
    media = []
    for idx, m in enumerate(messages):
        mtype, fid = _extract_media_type_and_file_id(m)
        if not mtype or not fid:
            continue
        item = {"type": "photo" if mtype == 'photo' else ("video" if mtype == 'video' else "photo"), "media": fid}
        if idx == 0:
            caption = admin_info_html
            if caption:
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
                count = len(media)
                short_msg = f"📩 Нове повідомлення від користувача (альбом: {count} елемент(ів))."
                short_msg += "\nНатисніть «✉️ Відповісти», щоб відповісти користувачу."
                send_message(admin_id, short_msg, reply_markup=reply_markup, parse_mode=None)
            except Exception:
                logger.exception("Failed to send short notification after sendMediaGroup")
            return True
        else:
            if resp is not None:
                MainProtokol(f"sendMediaGroup failed: {resp.status_code} {resp.text}", "MediaGroup")
            return False
    except Exception as e:
        cool_error_handler(e, context="_send_media_group_to_admin")
        return False

def _send_media_group_to_user(user_id: int, messages: list, caption_text: str = None) -> bool:
    if not user_id:
        return False
    base = f"https://api.telegram.org/bot{TOKEN}"
    media = []
    for idx, m in enumerate(messages):
        mtype, fid = _extract_media_type_and_file_id(m)
        if not mtype or not fid:
            continue
        item = {"type": "photo" if mtype == 'photo' else ("video" if mtype == 'video' else "photo"), "media": fid}
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
                MainProtokol(f"sendMediaGroup->user failed: {resp.status_code} {resp.text}", "MediaGroupUser")
            return False
    except Exception as e:
        cool_error_handler(e, context="_send_media_group_to_user")
        return False

def _truncate_caption_for_media(caption: str, max_len: int = 1000) -> str:
    if not caption:
        return ""
    if len(caption) <= max_len:
        return caption
    return caption[:max_len-3] + "..."

def send_media_to_admin(admin_id: int, message: Dict[str, Any], admin_info_html: str, reply_markup: dict = None) -> bool:
    if not admin_id:
        MainProtokol("send_media_to_admin: admin_id пустой", "Media")
        return False
    base = f"https://api.telegram.org/bot{TOKEN}"
    caption = _truncate_caption_for_media(admin_info_html, max_len=1000)
    rm_json = json.dumps(reply_markup) if reply_markup else None
    try:
        if 'photo' in message and isinstance(message['photo'], list) and message['photo']:
            file_id = message['photo'][-1].get('file_id')
            if file_id:
                resp = _post_with_retries(f"{base}/sendPhoto", data={'chat_id': admin_id, 'photo': file_id, 'caption': caption, 'parse_mode': 'HTML', **({'reply_markup': rm_json} if rm_json else {})})
                if resp and resp.ok:
                    return True
                if resp is not None:
                    MainProtokol(f"sendPhoto failed: {resp.status_code} {resp.text}", "Media")
        if 'document' in message:
            file_id = message['document'].get('file_id')
            if file_id:
                resp = _post_with_retries(f"{base}/sendDocument", data={'chat_id': admin_id, 'document': file_id, 'caption': caption, 'parse_mode': 'HTML', **({'reply_markup': rm_json} if rm_json else {})})
                if resp and resp.ok:
                    return True
                if resp is not None:
                    MainProtokol(f"sendDocument failed: {resp.status_code} {resp.text}", "Media")
        if 'video' in message:
            file_id = message['video'].get('file_id')
            if file_id:
                resp = _post_with_retries(f"{base}/sendVideo", data={'chat_id': admin_id, 'video': file_id, 'caption': caption, 'parse_mode': 'HTML', **({'reply_markup': rm_json} if rm_json else {})})
                if resp and resp.ok:
                    return True
                if resp is not None:
                    MainProtokol(f"sendVideo failed: {resp.status_code} {resp.text}", "Media")
        for key, endpoint, payload_key in [
            ('voice', 'sendVoice', 'voice'),
            ('audio', 'sendAudio', 'audio'),
            ('animation', 'sendAnimation', 'animation'),
            ('sticker', 'sendSticker', 'sticker')
        ]:
            if key in message:
                file_id = message[key].get('file_id')
                if file_id:
                    payload = {'chat_id': admin_id, payload_key: file_id}
                    if key not in ('sticker',):
                        payload['caption'] = caption
                        payload['parse_mode'] = 'HTML'
                    if rm_json:
                        payload['reply_markup'] = rm_json
                    resp = _post_with_retries(f"{base}/{endpoint}", data=payload)
                    if resp and resp.ok:
                        return True
                    if resp is not None:
                        MainProtokol(f"{endpoint} failed: {resp.status_code} {resp.text}", "Media")
        return False
    except Exception as e:
        cool_error_handler(e, context="send_media_to_admin: outer")
        return False

def send_media_to_user(user_id: int, message: Dict[str, Any], caption_text: str = None) -> bool:
    if not user_id:
        MainProtokol("send_media_to_user: user_id пустой", "Media")
        return False
    base = f"https://api.telegram.org/bot{TOKEN}"
    caption = _truncate_caption_for_media(caption_text or "", max_len=1000)
    try:
        if 'photo' in message and isinstance(message['photo'], list) and message['photo']:
            file_id = message['photo'][-1].get('file_id')
            if file_id:
                resp = _post_with_retries(f"{base}/sendPhoto", data={'chat_id': user_id, 'photo': file_id, 'caption': caption, 'parse_mode': 'HTML'})
                if resp and resp.ok:
                    return True
                if resp is not None:
                    MainProtokol(f"sendPhoto->user failed: {resp.status_code} {resp.text}", "MediaUser")
        if 'document' in message:
            file_id = message['document'].get('file_id')
            if file_id:
                resp = _post_with_retries(f"{base}/sendDocument", data={'chat_id': user_id, 'document': file_id, 'caption': caption, 'parse_mode': 'HTML'})
                if resp and resp.ok:
                    return True
                if resp is not None:
                    MainProtokol(f"sendDocument->user failed: {resp.status_code} {resp.text}", "MediaUser")
        if 'video' in message:
            file_id = message['video'].get('file_id')
            if file_id:
                resp = _post_with_retries(f"{base}/sendVideo", data={'chat_id': user_id, 'video': file_id, 'caption': caption, 'parse_mode': 'HTML'})
                if resp and resp.ok:
                    return True
                if resp is not None:
                    MainProtokol(f"sendVideo->user failed: {resp.status_code} {resp.text}", "MediaUser")
        for key, endpoint, payload_key in [
            ('voice', 'sendVoice', 'voice'),
            ('audio', 'sendAudio', 'audio'),
            ('animation', 'sendAnimation', 'animation'),
            ('sticker', 'sendSticker', 'sticker')
        ]:
            if key in message:
                file_id = message[key].get('file_id')
                if file_id:
                    payload = {'chat_id': user_id, payload_key: file_id}
                    if key not in ('sticker',):
                        payload['caption'] = caption
                        payload['parse_mode'] = 'HTML'
                    resp = _post_with_retries(f"{base}/{endpoint}", data=payload)
                    if resp and resp.ok:
                        return True
                    if resp is not None:
                        MainProtokol(f"{endpoint}->user failed: {resp.status_code} {resp.text}", "MediaUser")
        return False
    except Exception as e:
        cool_error_handler(e, context="send_media_to_user: outer")
        return False

# ====== Flask app и init-once через before_request ======
app = Flask(__name__)

def set_webhook_if_needed():
    try:
        if not TOKEN:
            MainProtokol("TOKEN не установлен, webhook не настраивается", "Webhook")
            return
        if not WEBHOOK_URL:
            MainProtokol("WEBHOOK_URL не задан, webhook не настраивается", "Webhook")
            return
        try:
            r = requests.get(f"https://api.telegram.org/bot{TOKEN}/setWebhook", params={"url": WEBHOOK_URL}, timeout=6)
            if r.ok:
                logger.info("Webhook успешно установлен (init).")
            else:
                logger.warning("Ошибка при установке webhook (init): %s", r.text)
        except Exception:
            logger.exception("set_webhook_if_needed exception")
    except Exception as e:
        cool_error_handler(e, context="set_webhook_if_needed")

def start_background_workers_once():
    try:
        init_db()
    except Exception as e:
        cool_error_handler(e, context="init_db in background")
    try:
        set_webhook_if_needed()
    except Exception as e:
        cool_error_handler(e, context="set_webhook in background")

    def _start_thread_if_missing(name, target):
        exists = any(t.name == name for t in threading.enumerate())
        if not exists:
            threading.Thread(target=target, daemon=True, name=name).start()

    try:
        _start_thread_if_missing("time-debugger", time_debugger)
    except Exception as e:
        cool_error_handler(e, context="start background threads")

_initialized = False
_init_lock = threading.Lock()

def _start_init_in_background():
    try:
        start_background_workers_once()
    except Exception as e:
        cool_error_handler(e, context="background init runner")

def ensure_initialized():
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        t = threading.Thread(target=_start_init_in_background, daemon=True, name="init-once")
        t.start()
        _initialized = True
        logger.info("Initialization scheduled in background thread for this process.")

@app.before_request
def _app_ensure_initialized_before_request():
    try:
        ensure_initialized()
    except Exception as e:
        logger.exception("Error in before_request initialization hook")
        cool_error_handler(e, context="before_request init")

@app.errorhandler(Exception)
def flask_global_error_handler(e):
    cool_error_handler(e, context="Flask global error handler")
    return "Внутрішня помилка сервера.", 500

def format_stats_message(stats: dict) -> str:
    cat_names = [c for c in ADMIN_SUBCATEGORIES]
    max_cat_len = max(len(escape(c)) for c in cat_names) + 1
    col1 = "Категорія".ljust(max_cat_len)
    header = f"{col1}  {'7 дн':>6}  {'30 дн':>6}"
    lines = [header, "-" * (max_cat_len + 16)]
    for cat in ADMIN_SUBCATEGORIES:
        name = escape(cat)
        week = stats[cat]['week']
        month = stats[cat]['month']
        lines.append(f"{name.ljust(max_cat_len)}  {str(week):>6}  {str(month):>6}")
    content = "\n".join(lines)
    return "<pre>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" + content + "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━</pre>"

# ====== Webhook route ======
@app.route("/webhook/<token>", methods=["POST"])
def webhook(token):
    try:
        if not TOKEN or token != TOKEN:
            logger.warning("Received webhook with invalid token")
            abort(403)

        data_raw = request.get_data(as_text=True)
        update = json.loads(data_raw)

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
                except Exception as e:
                    cool_error_handler(e, context="webhook: callback_query reply_")
                    MainProtokol(str(e), 'Помилка callback reply')
            elif data == "write_admin":
                with state_lock:
                    waiting_for_admin_message.add(chat_id)
                send_message(chat_id, "✍️ Напишіть повідомлення адміністратору (текст/фото/документ):")
            return "ok", 200

        if 'message' in update:
            message = update['message']
            chat_id = message['chat']['id']
            from_id = message['from']['id']
            text = message.get('text', '')

            # admin reply to user
            with state_lock:
                admin_waiting = waiting_for_admin.get(ADMIN_ID)
            if from_id == ADMIN_ID and admin_waiting:
                mgid = message.get('media_group_id')
                if mgid:
                    _buffer_media_group(from_id, mgid, message, origin='admin', target_user=admin_waiting)
                    return "ok", 200
                try:
                    user_id = None
                    with state_lock:
                        user_id = waiting_for_admin.pop(ADMIN_ID, None)
                    if user_id:
                        media_sent = send_media_to_user(user_id, message, caption_text=text)
                        if not media_sent:
                            send_message(user_id, f"💬 Відповідь адміністратора:\n{text}")
                        send_message(ADMIN_ID, f"✅ Відповідь надіслано користувачу {user_id}")
                except Exception as e:
                    cool_error_handler(e, context="webhook: admin reply send")
                return "ok", 200

            # main commands
            if text == '/start':
                send_chat_action(chat_id, 'typing')
                time.sleep(0.25)
                send_message(chat_id, "✨ Ласкаво просимо!\n\nОберіть дію в меню нижче:", reply_markup=get_reply_buttons(), parse_mode='HTML')
            elif text in MAIN_MENU:
                if text == "✨ Головне":
                    send_message(chat_id, "✨ Ви в головному меню.", reply_markup=get_reply_buttons())
                elif text == "📢 Про нас":
                    send_message(chat_id, "Ми створюємо телеграм-ботів та сервіси для вашого бізнесу і життя.")
                elif text == "🕰️ Графік роботи":
                    send_message(chat_id, "Ми працюємо цілодобово. Звертайтесь у будь-який час.")
                elif text == "📝 Повідомити про подію":
                    desc = "Оберіть тип події..."
                    send_message(chat_id, desc, reply_markup=get_admin_subcategory_buttons())
                elif text == "📊 Статистика подій":
                    stats = get_stats()
                    if stats:
                        msg = format_stats_message(stats)
                        send_message(chat_id, msg, parse_mode='HTML')
                    else:
                        send_message(chat_id, "Наразі статистика недоступна.")
                elif text == "📣 Реклама":
                    # Поводимся так же, як с "Повідомити про подію": ждём одно сообщение или альбом.
                    with state_lock:
                        waiting_for_ad_message.add(chat_id)
                    send_message(chat_id, "📣 Ви обрали розділ «Реклама». Надішліть текст та/або медіа (можна кілька фото/відео як альбом).", reply_markup=get_reply_buttons())
            elif text in ADMIN_SUBCATEGORIES:
                with state_lock:
                    user_admin_category[chat_id] = text
                    waiting_for_admin_message.add(chat_id)
                send_message(chat_id, f"Будь ласка, опишіть деталі події «{text}» (можна прикріпити фото чи файл):")
            else:
                mgid = message.get('media_group_id')
                with state_lock:
                    in_ad = chat_id in waiting_for_ad_message
                    in_admin_msg = chat_id in waiting_for_admin_message

                # If this message is part of an album and user is in ad or event flow -> buffer album
                if mgid and (in_admin_msg or in_ad):
                    purpose = 'event' if in_admin_msg else 'ad'
                    _buffer_media_group(chat_id, mgid, message, origin='user', purpose=purpose)
                    # For ad: remove waiting flag because user already sent content
                    if purpose == 'ad':
                        with state_lock:
                            waiting_for_ad_message.discard(chat_id)
                    return "ok", 200

                if in_ad:
                    # single message ad (not album)
                    forward_ad_to_admin(message)
                    with state_lock:
                        waiting_for_ad_message.discard(chat_id)
                    send_message(chat_id, "✅ Ваша рекламна заявка успішно надіслана. Дякуємо!", reply_markup=get_reply_buttons())
                elif in_admin_msg:
                    forward_user_message_to_admin(message)
                    with state_lock:
                        waiting_for_admin_message.discard(chat_id)
                        user_admin_category.pop(chat_id, None)
                    send_message(chat_id, "Ваша інформація передана. Дякуємо за активну позицію!", reply_markup=get_reply_buttons())
                else:
                    send_message(chat_id, "Щоб повідомити адміна або надіслати рекламу, скористайтесь відповідними кнопками в меню.", reply_markup=get_reply_buttons())
        return "ok", 200
    except Exception as e:
        cool_error_handler(e, context="webhook - outer")
        MainProtokol(str(e), 'Помилка webhook')
        return "ok", 200

@app.route('/', methods=['GET'])
def index():
    try:
        MainProtokol('Відвідання сайту')
        return "Бот працює", 200
    except Exception as e:
        cool_error_handler(e, context="index route")
        return "Error", 500

@app.route('/health', methods=['GET'])
def health():
    return "ok", 200

if __name__ == "__main__":
    try:
        init_db()
    except Exception as e:
        cool_error_handler(e, context="main: init_db")
    def set_webhook():
        try:
            if not TOKEN:
                MainProtokol("TOKEN не установлен, webhook не настраивается", "Webhook")
                return
            if not WEBHOOK_URL:
                MainProtokol("WEBHOOK_URL не задан, webhook не настраивается", "Webhook")
                return
            r = requests.get(f"https://api.telegram.org/bot{TOKEN}/setWebhook", params={"url": WEBHOOK_URL}, timeout=6)
            if r.ok:
                logger.info("Webhook успешно установлен!")
            else:
                logger.warning("Ошибка при установке webhook: %s", r.text)
        except Exception as e:
            cool_error_handler(e, context="set_webhook")
    try:
        set_webhook()
    except Exception as e:
        cool_error_handler(e, context="main: set_webhook")
    try:
        threading.Thread(target=time_debugger, daemon=True).start()
    except Exception as e:
        cool_error_handler(e, context="main: start time_debugger")
    port = int(os.getenv("PORT", 5000))
    try:
        app.run(host="0.0.0.0", port=port)
    except Exception as e:
        cool_error_handler(e, context="main: app.run")
