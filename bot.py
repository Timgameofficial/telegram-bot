# contents: расширение информации, отправляемой админу — больше полей и аккуратное HTML-оформление
# Обновлён: перенесён init/set_webhook в main, добавлены timeout/ретраи для HTTP,
# блокировки для глобального состояния, support sendMediaGroup/аккуратная отправка медиа,
# /health endpoint, улучшенное логирование, возможность админа отвечать медиa.
import os
import time
import json
import requests
import threading
import traceback
import datetime
import textwrap
import random
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, request, abort
from html import escape
from pathlib import Path
from typing import Dict, Any

# Библиотека для работы с разными БД (Postgres/SQLite)
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# ====== Настройка логирования (RotatingFileHandler) ======
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
    except Exception as e:
        logger.exception("Ошибка записи в log.txt")
    # также в основной лог
    logger.info(line)

# ====== Простой и понятный обработчик ошибок ======
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
    except Exception as write_err:
        logger.exception("Не удалось записать в 'critical_errors.log'")
    try:
        MainProtokol(f"{exc_type}: {str(exc)}", ts='ERROR')
    except Exception as log_err:
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
                except Exception as telegram_err:
                    logger.exception("Не удалось отправить уведомление в Telegram")
        except Exception as env_err:
            logger.exception("Ошибка при подготовке уведомления в Telegram")

# ====== Фоновый отладчик времени (каждые 5 минут) ======
def time_debugger():
    while True:
        logger.debug("[DEBUG] " + time.strftime('%Y-%m-%d %H:%M:%S'))
        time.sleep(300)

# ====== Главное меню (reply-кнопки) — премиальное оформление ======
MAIN_MENU = [
    "✨ Головне",
    "📢 Про нас",
    "🕰️ Графік роботи",
    "📝 Повідомити про подію",
    "📊 Статистика подій",
    "📣 Реклама"
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

# ====== Категории событий ======
ADMIN_SUBCATEGORIES = [
    "🏗️ Техногенні",
    "🌪️ Природні",
    "👥 Соціальні",
    "⚔️ Воєнні",
    "🕵️‍♂️ Розшук",
    "📦 Інше"
]

def get_admin_subcategory_buttons():
    return {
        "keyboard": [[{"text": cat}] for cat in ADMIN_SUBCATEGORIES],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }

# ====== Состояния ожидания (в памяти, защищены lock) ======
state_lock = threading.Lock()
waiting_for_admin_message = set()
user_admin_category = {}
waiting_for_ad_message = set()
waiting_for_admin = {}  # mapping admin_id -> user_id awaiting reply

# ====== Настройки БД ======
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
            try:
                res = conn.execute(text("SELECT COUNT(*) as cnt FROM events"))
                cnt = res.scalar() if res is not None else 0
            except Exception:
                cnt = 0
            logger.info(f"[DEBUG] events table row count after init: {cnt}")
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
                try:
                    r = conn.execute(text("SELECT COUNT(*) as cnt FROM events"))
                    cnt = r.scalar() or 0
                except Exception:
                    cnt = None
            logger.info(f"[DEBUG] Saved event (sqlite). Total events now: {cnt}")
        else:
            insert_sql = "INSERT INTO events (category, dt) VALUES (:cat, :dt)"
            with engine.begin() as conn:
                conn.execute(text(insert_sql), {"cat": category, "dt": now})
                try:
                    r = conn.execute(text("SELECT COUNT(*) FROM events"))
                    cnt = r.scalar() or 0
                except Exception:
                    cnt = None
            logger.info(f"[DEBUG] Saved event (sql). Total events now: {cnt}")
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

def clear_stats_if_month_passed():
    try:
        engine = get_engine()
        now = datetime.datetime.utcnow()
        month_threshold = now - datetime.timedelta(days=30)
        with engine.begin() as conn:
            if engine.dialect.name == "sqlite":
                month_ts = month_threshold.isoformat()
                conn.execute(text("DELETE FROM events WHERE dt < :month"), {"month": month_ts})
            else:
                conn.execute(text("DELETE FROM events WHERE dt < :month"), {"month": month_threshold})
    except Exception as e:
        cool_error_handler(e, "clear_stats_if_month_passed")

def stats_autoclear_daemon():
    while True:
        try:
            clear_stats_if_month_passed()
        except Exception as e:
            cool_error_handler(e, "stats_autoclear_daemon")
        time.sleep(3600)

# ====== Конфигурация (будет считываться в main) ======
TOKEN = os.getenv("API_TOKEN")
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
except Exception:
    ADMIN_ID = 0
    MainProtokol("Invalid ADMIN_ID env variable, defaulting to 0", "StartupWarning")

# WEBHOOK_URL следует задавать через переменную окружения WEBHOOK_URL = https://your-app.onrender.com/webhook/<token>
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()

# ====== HTTP helper с ретраями ======
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
                cool_error_handler(e, context="_post_with_retries", send_to_telegram=False)
            except Exception:
                pass
            if attempt < RETRIES:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                return None

# ====== UI helpers ======
def send_chat_action(chat_id, action='typing'):
    if not TOKEN:
        return
    try:
        _post_with_retries(f'https://api.telegram.org/bot{TOKEN}/sendChatAction', data={'chat_id': chat_id, 'action': action})
    except Exception:
        logger.exception("send_chat_action failed")

# ====== Отправка сообщений (parse_mode поддерживается), теперь с таймаутом/ретраями ======
def send_message(chat_id, text, reply_markup=None, parse_mode=None):
    if not TOKEN:
        logger.warning("send_message called but TOKEN not set")
        return None
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': text
    }
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
    return {
        "inline_keyboard": [
            [{"text": "✉️ Відповісти", "callback_data": f"reply_{user_id}"}]
        ]
    }

# ====== Helper: строим расширённую карточку для админа ======
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
        entities_summary = []
        for ent in entities:
            etype = ent.get('type')
            if etype:
                entities_summary.append(etype)
        entities_summary = ", ".join(entities_summary) if entities_summary else "-"

        media_keys = []
        media_details = []
        media_candidates = [
            'photo', 'video', 'document', 'audio', 'voice', 'animation', 'sticker', 'contact', 'location'
        ]
        for k in media_candidates:
            if k in message:
                media_keys.append(k)
                try:
                    if k == 'photo':
                        photos = message.get('photo', [])
                        file_ids = [escape(p.get('file_id')) for p in photos if p.get('file_id')]
                        media_details.append(f"{k} (file_ids: {','.join(file_ids)})")
                    elif k == 'contact':
                        c = message.get('contact', {})
                        media_details.append(f"contact ({escape(str(c.get('phone_number','-')))}: {escape(str(c.get('first_name','')))} )")
                    elif k == 'location':
                        loc = message.get('location', {})
                        media_details.append(f"location (lat:{escape(str(loc.get('latitude')) )}, lon:{escape(str(loc.get('longitude')) )})")
                    else:
                        if isinstance(message.get(k), dict) and 'file_id' in message.get(k):
                            media_details.append(f"{k} (file_id: {escape(message[k].get('file_id'))})")
                        elif isinstance(message.get(k), list) and message.get(k) and isinstance(message.get(k)[-1], dict) and message.get(k)[-1].get('file_id'):
                            media_details.append(f"{k} (file_id: {escape(message[k][-1].get('file_id'))})")
                        else:
                            media_details.append(f"{k}")
                except Exception:
                    media_details.append(k)

        media_summary = ", ".join(media_keys) if media_keys else "-"

        reply_info = "-"
        if 'reply_to_message' in message and isinstance(message['reply_to_message'], dict):
            r = message['reply_to_message']
            rfrom = r.get('from', {})
            rname = (rfrom.get('first_name','') or '') + ((' ' + (rfrom.get('last_name') or '')) if rfrom.get('last_name') else '')
            reply_info = f"id:{r.get('message_id','-')} from:{escape(rname or '-')}"

        parts = [
            "<pre>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</pre>",
            "<b>📩 Нове повідомлення від користувача</b>",
            "",
        ]
        if category:
            parts.append(f"<b>Категорія:</b> {escape(category)}")
        display_name = (first + (" " + last if last else "")).strip() or "Без імені"
        parts += [
            f"<b>Ім'я:</b> {escape(display_name)}",
            f"<b>ID:</b> {escape(str(user_id)) if user_id is not None else '-'}",
        ]
        if username:
            parts.append(f"<b>Username:</b> @{escape(username)}")
        parts += [
            f"<b>Мова:</b> {escape(str(lang))}",
            f"<b>Is bot:</b> {escape(str(is_bot))}",
        ]
        if is_premium is not None:
            parts.append(f"<b>Is premium:</b> {escape(str(is_premium))}")
        parts += [
            f"<b>Тип чату:</b> {escape(str(chat_type))}" + (f" ({escape(chat_title)})" if chat_title else ""),
            f"<b>Message ID:</b> {escape(str(msg_id))}",
            f"<b>Дата:</b> {escape(str(date_str))}",
            f"<b>Entities:</b> {escape(entities_summary)}",
            f"<b>Reply to:</b> {escape(reply_info)}",
            f"<b>Медіа:</b> {escape(media_summary)}",
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

# ====== Новая аккуратная пересылка: отправляем медиа+подпись (вместо forwardMessage) ======
def _truncate_caption_for_media(caption: str, max_len: int = 1000) -> str:
    if not caption:
        return ""
    if len(caption) <= max_len:
        return caption
    return caption[:max_len-3] + "..."

def send_media_to_admin(admin_id: int, message: Dict[str, Any], admin_info_html: str, reply_markup: dict = None) -> bool:
    """
    Попытаться аккуратно отправить медиа+подпись админу. Возвращает True при успехе.
    Поддерживает: photo, document, video, audio, voice, animation, sticker.
    """
    if not admin_id:
        MainProtokol("send_media_to_admin: admin_id пустой", "Media")
        return False

    rm_json = json.dumps(reply_markup) if reply_markup else None
    caption = _truncate_caption_for_media(admin_info_html, max_len=1000)
    base = f"https://api.telegram.org/bot{TOKEN}"

    try:
        if 'photo' in message and isinstance(message['photo'], list) and message['photo']:
            try:
                # Обычно message['photo'] — размеры одного фото; берем последний
                file_id = message['photo'][-1].get('file_id')
                if file_id:
                    url = f"{base}/sendPhoto"
                    payload = {'chat_id': admin_id, 'photo': file_id, 'caption': caption, 'parse_mode': 'HTML'}
                    if rm_json:
                        payload['reply_markup'] = rm_json
                    resp = _post_with_retries(url, data=payload)
                    if resp and resp.ok:
                        return True
                    if resp is not None:
                        MainProtokol(f"sendPhoto failed: {resp.status_code} {resp.text}", "Media")
            except Exception as e:
                cool_error_handler(e, context="send_media_to_admin: photo")
                return False

        if 'document' in message:
            try:
                doc = message['document']
                file_id = doc.get('file_id') if isinstance(doc, dict) else None
                if file_id:
                    url = f"{base}/sendDocument"
                    payload = {'chat_id': admin_id, 'document': file_id, 'caption': caption, 'parse_mode': 'HTML'}
                    if rm_json:
                        payload['reply_markup'] = rm_json
                    resp = _post_with_retries(url, data=payload)
                    if resp and resp.ok:
                        return True
                    if resp is not None:
                        MainProtokol(f"sendDocument failed: {resp.status_code} {resp.text}", "Media")
            except Exception as e:
                cool_error_handler(e, context="send_media_to_admin: document")
                return False

        if 'video' in message:
            try:
                video = message['video']
                file_id = video.get('file_id') if isinstance(video, dict) else None
                if file_id:
                    url = f"{base}/sendVideo"
                    payload = {'chat_id': admin_id, 'video': file_id, 'caption': caption, 'parse_mode': 'HTML'}
                    if rm_json:
                        payload['reply_markup'] = rm_json
                    resp = _post_with_retries(url, data=payload)
                    if resp and resp.ok:
                        return True
                    if resp is not None:
                        MainProtokol(f"sendVideo failed: {resp.status_code} {resp.text}", "Media")
            except Exception as e:
                cool_error_handler(e, context="send_media_to_admin: video")
                return False

        for key, endpoint, payload_key in [
            ('voice', 'sendVoice', 'voice'),
            ('audio', 'sendAudio', 'audio'),
            ('animation', 'sendAnimation', 'animation'),
            ('sticker', 'sendSticker', 'sticker')
        ]:
            if key in message:
                try:
                    obj = message[key]
                    file_id = obj.get('file_id') if isinstance(obj, dict) else None
                    if file_id:
                        url = f"{base}/{endpoint}"
                        payload = {'chat_id': admin_id, payload_key: file_id}
                        if key not in ('sticker',):
                            payload['caption'] = caption
                            payload['parse_mode'] = 'HTML'
                        if rm_json:
                            payload['reply_markup'] = rm_json
                        resp = _post_with_retries(url, data=payload)
                        if resp and resp.ok:
                            return True
                        if resp is not None:
                            MainProtokol(f"{endpoint} failed: {resp.status_code} {resp.text}", "Media")
                except Exception as e:
                    cool_error_handler(e, context=f"send_media_to_admin: {key}")
                    return False

        return False
    except Exception as e:
        cool_error_handler(e, context="send_media_to_admin: outer")
        return False

# ====== Аналогично: отправка от админа пользователю (поддержка медиа при ответе) ======
def send_media_to_user(user_id: int, message: Dict[str, Any], caption_text: str = None) -> bool:
    """
    Используется, когда админ отвечает пользователю и прикрепляет медиа.
    caption_text будет подставлен в подпись (ограничено).
    """
    if not user_id:
        MainProtokol("send_media_to_user: user_id пустой", "Media")
        return False
    base = f"https://api.telegram.org/bot{TOKEN}"
    caption = _truncate_caption_for_media(caption_text or "", max_len=1000)

    try:
        if 'photo' in message and isinstance(message['photo'], list) and message['photo']:
            try:
                file_id = message['photo'][-1].get('file_id')
                if file_id:
                    url = f"{base}/sendPhoto"
                    payload = {'chat_id': user_id, 'photo': file_id, 'caption': caption, 'parse_mode': 'HTML'}
                    resp = _post_with_retries(url, data=payload)
                    if resp and resp.ok:
                        return True
                    if resp is not None:
                        MainProtokol(f"sendPhoto->user failed: {resp.status_code} {resp.text}", "MediaUser")
            except Exception as e:
                cool_error_handler(e, context="send_media_to_user: photo")
                return False

        if 'document' in message:
            try:
                file_id = message['document'].get('file_id')
                if file_id:
                    url = f"{base}/sendDocument"
                    payload = {'chat_id': user_id, 'document': file_id, 'caption': caption, 'parse_mode': 'HTML'}
                    resp = _post_with_retries(url, data=payload)
                    if resp and resp.ok:
                        return True
                    if resp is not None:
                        MainProtokol(f"sendDocument->user failed: {resp.status_code} {resp.text}", "MediaUser")
            except Exception as e:
                cool_error_handler(e, context="send_media_to_user: document")
                return False

        if 'video' in message:
            try:
                file_id = message['video'].get('file_id')
                if file_id:
                    url = f"{base}/sendVideo"
                    payload = {'chat_id': user_id, 'video': file_id, 'caption': caption, 'parse_mode': 'HTML'}
                    resp = _post_with_retries(url, data=payload)
                    if resp and resp.ok:
                        return True
                    if resp is not None:
                        MainProtokol(f"sendVideo->user failed: {resp.status_code} {resp.text}", "MediaUser")
            except Exception as e:
                cool_error_handler(e, context="send_media_to_user: video")
                return False

        for key, endpoint, payload_key in [
            ('voice', 'sendVoice', 'voice'),
            ('audio', 'sendAudio', 'audio'),
            ('animation', 'sendAnimation', 'animation'),
            ('sticker', 'sendSticker', 'sticker')
        ]:
            if key in message:
                try:
                    file_id = message[key].get('file_id')
                    if file_id:
                        url = f"{base}/{endpoint}"
                        payload = {'chat_id': user_id, payload_key: file_id}
                        if key not in ('sticker',):
                            payload['caption'] = caption
                            payload['parse_mode'] = 'HTML'
                        resp = _post_with_retries(url, data=payload)
                        if resp and resp.ok:
                            return True
                        if resp is not None:
                            MainProtokol(f"{endpoint}->user failed: {resp.status_code} {resp.text}", "MediaUser")
                except Exception as e:
                    cool_error_handler(e, context=f"send_media_to_user: {key}")
                    return False

        return False
    except Exception as e:
        cool_error_handler(e, context="send_media_to_user: outer")
        return False

def forward_user_message_to_admin(message: Dict[str, Any]):
    """
    Обновлённая версия: не пересылает оригинал через forwardMessage,
    а аккуратно отправляет медиа с подписью (admin_info) или просто отправляет карточку.
    """
    try:
        if not ADMIN_ID or ADMIN_ID == 0:
            try:
                send_message(message['chat']['id'], "⚠️ Адміністратор не налаштований.")
            except Exception:
                pass
            return

        user_chat_id = message['chat']['id']
        category = user_admin_category.get(user_chat_id, 'Без категорії')

        admin_info = build_admin_info(message, category=category)
        reply_markup = _get_reply_markup_for_admin(user_chat_id)

        try:
            if category in ADMIN_SUBCATEGORIES:
                save_event(category)
        except Exception as e:
            MainProtokol(f"save_event failed: {str(e)}", "SaveEvent")

        try:
            media_ok = send_media_to_admin(ADMIN_ID, message, admin_info, reply_markup=reply_markup)
            if not media_ok:
                send_message(ADMIN_ID, admin_info, reply_markup=reply_markup, parse_mode='HTML')
            send_message(user_chat_id, "✅ Дякуємо! Ваше повідомлення надіслано адміністратору.")
            return
        except Exception as e:
            cool_error_handler(e, context="forward_user_message_to_admin: sendMedia")
            MainProtokol(str(e), "SendMediaException")
            try:
                send_message(ADMIN_ID, admin_info, reply_markup=reply_markup, parse_mode='HTML')
                send_message(user_chat_id, "⚠️ Виникла помилка при пересиланні медіа, адміністратору надіслано текст повідомлення.")
            except Exception:
                pass
            return
    except Exception as e:
        cool_error_handler(e, context="forward_user_message_to_admin: unhandled")
        MainProtokol(str(e), "ForwardUnhandledException")
        try:
            send_message(message['chat']['id'], "⚠️ Виникла помилка при надсиланні. Спробуйте ще раз.")
        except Exception as err:
            cool_error_handler(err, context="forward_user_message_to_admin: notify user")

def forward_ad_to_admin(message: Dict[str, Any]):
    try:
        if not ADMIN_ID or ADMIN_ID == 0:
            try:
                send_message(message['chat']['id'], "⚠️ Адміністратор не налаштований.")
            except Exception:
                pass
            return

        user_chat_id = message['chat']['id']
        admin_info = build_admin_info(message, category=None)
        reply_markup = _get_reply_markup_for_admin(user_chat_id)

        if ADMIN_ID and ADMIN_ID != 0:
            send_chat_action(ADMIN_ID, 'typing')
            time.sleep(0.25)

        try:
            media_ok = send_media_to_admin(ADMIN_ID, message, admin_info, reply_markup=reply_markup)
            if not media_ok:
                send_message(ADMIN_ID, admin_info, reply_markup=reply_markup, parse_mode='HTML')
            send_message(user_chat_id, "✅ Дякуємо! Ваша заявка надіслана.")
            return
        except Exception as e:
            cool_error_handler(e, context="forward_ad_to_admin: sendMedia")
            MainProtokol(str(e), "ForwardAdMediaException")
            try:
                send_message(ADMIN_ID, admin_info, reply_markup=reply_markup, parse_mode='HTML')
                send_message(user_chat_id, "⚠️ Виникла помилка при надсиланні рекламного запиту. Спробуйте ще раз.")
            except Exception:
                pass
            return
    except Exception as e:
        cool_error_handler(e, context="forward_ad_to_admin: unhandled")
        MainProtokol(str(e), "ForwardAdUnhandledException")
        try:
            send_message(message['chat']['id'], "⚠️ Виникла помилка при надсиланні рекламного запиту. Спробуйте ще раз.")
        except Exception as err:
            cool_error_handler(err, context="forward_ad_to_admin: notify user")

app = Flask(__name__)

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

# Маршрут webhook общий, проверяем токен внутри
@app.route("/webhook/<token>", methods=["POST"])
def webhook(token):
    try:
        # Verify token matches configured TOKEN
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
                    send_message(
                        ADMIN_ID,
                        f"✍️ Введіть відповідь для користувача {user_id}:"
                    )
                except Exception as e:
                    cool_error_handler(e, context="webhook: callback_query reply_")
                    MainProtokol(str(e), 'Помилка callback reply')
            elif data == "about":
                send_message(
                    chat_id,
                    "Ми створюємо телеграм-ботів та сервіси для вашого бізнесу і життя.\nДізнатись більше: наші канали"
                )
            elif data == "schedule":
                send_message(
                    chat_id,
                    "Наш бот приймає повідомлення 24/7. Ми відповідаємо якнайшвидше."
                )
            elif data == "write_admin":
                with state_lock:
                    waiting_for_admin_message.add(chat_id)
                send_message(
                    chat_id,
                    "✍️ Напишіть повідомлення адміністратору (текст/фото/документ):"
                )
            return "ok", 200

        if 'message' in update:
            message = update['message']
            chat_id = message['chat']['id']
            from_id = message['from']['id']
            text = message.get('text', '')
            first_name = message['from'].get('first_name', 'Без імені')

            # Ответ администратора пользователю (текст или медиа)
            with state_lock:
                admin_waiting = waiting_for_admin.get(ADMIN_ID)
            if from_id == ADMIN_ID and admin_waiting:
                user_id = None
                with state_lock:
                    user_id = waiting_for_admin.pop(ADMIN_ID, None)
                if user_id:
                    # Если админ отправил медиа - пересылаем медиа аккуратно
                    try:
                        media_sent = send_media_to_user(user_id, message, caption_text=text)
                        if not media_sent:
                            # фоллбек — отправить текст
                            send_message(user_id, f"💬 Відповідь адміністратора:\n{text}")
                        send_message(ADMIN_ID, f"✅ Відповідь надіслано користувачу {user_id}")
                    except Exception as e:
                        cool_error_handler(e, context="webhook: admin reply send")
                        try:
                            send_message(ADMIN_ID, f"❌ Не вдалося надіслати відповідь користувачу {user_id}")
                        except Exception:
                            pass
                    return "ok", 200

            # Главное меню и другие обработки
            if text == '/start':
                send_chat_action(chat_id, 'typing')
                time.sleep(0.25)
                send_message(
                    chat_id,
                    "✨ Ласкаво просимо!\n\nОберіть дію в меню нижче:",
                    reply_markup=get_reply_buttons(),
                    parse_mode='HTML'
                )
            elif text in MAIN_MENU:
                if text == "✨ Головне":
                    send_message(chat_id, "✨ Ви в головному меню.", reply_markup=get_reply_buttons())
                elif text == "📢 Про нас":
                    send_message(
                        chat_id,
                        "Ми створюємо телеграм-ботів та сервіси для вашого бізнесу і життя.\nДізнатись більше: https://www.instagram.com/creator.bot_official?igsh=cHg1aDRqNXdrb210"
                    )
                elif text == "🕰️ Графік роботи":
                    send_message(
                        chat_id,
                        "Ми працюємо цілодобово. Звертайтесь у будь-який час."
                    )
                elif text == "📝 Повідомити про подію":
                    desc = (
                        "Оберіть тип події, яку хочете повідомити:\n\n"
                        "Техногенні: Події, пов'язані з діяльністю людини (аварії, катастрофи на виробництві/транспорті).\n\n"
                        "Природні: Події, спричинені силами природи (землетруси, повені, буревії).\n\n"
                        "Соціальні: Події, пов'язані з суспільними конфліктами або масовими заворушеннями.\n\n"
                        "Воєнні: Події, пов'язані з військовими діями або конфліктами.\n\n"
                        "Розшук: Дії, спрямовані на пошук зниклих осіб або злочинців.\n\n"
                        "Інші події: Загальна категорія для всього, що не вписується в попередні визначення."
                    )
                    send_message(chat_id, desc, reply_markup=get_admin_subcategory_buttons())
                elif text == "📊 Статистика подій":
                    stats = get_stats()
                    if stats:
                        msg = format_stats_message(stats)
                        send_message(chat_id, msg, parse_mode='HTML')
                    else:
                        send_message(chat_id, "Наразі статистика недоступна.")
                elif text == "📣 Реклама":
                    with state_lock:
                        waiting_for_ad_message.add(chat_id)
                    send_message(
                        chat_id,
                        "📣 Ви обрали розділ «Реклама». Надішліть текст та/або медіа — ми відформатуємо заявку у стильному вигляді та передамо адміністратору.",
                        reply_markup=get_reply_buttons()
                    )
            elif text in ADMIN_SUBCATEGORIES:
                with state_lock:
                    user_admin_category[chat_id] = text
                    waiting_for_admin_message.add(chat_id)
                send_message(
                    chat_id,
                    f"Будь ласка, опишіть деталі події «{text}» (можна прикріпити фото чи файл):"
                )
            else:
                with state_lock:
                    in_ad = chat_id in waiting_for_ad_message
                    in_admin_msg = chat_id in waiting_for_admin_message
                if in_ad:
                    forward_ad_to_admin(message)
                    with state_lock:
                        waiting_for_ad_message.discard(chat_id)
                    send_message(
                        chat_id,
                        "Ваша рекламна заявка успішно надіслана. Дякуємо!",
                        reply_markup=get_reply_buttons()
                    )
                elif in_admin_msg:
                    forward_user_message_to_admin(message)
                    with state_lock:
                        waiting_for_admin_message.discard(chat_id)
                        user_admin_category.pop(chat_id, None)
                    send_message(
                        chat_id,
                        "Ваша інформація передана. Дякуємо за активну позицію!",
                        reply_markup=get_reply_buttons()
                    )
                else:
                    send_message(
                        chat_id,
                        "Щоб повідомити адміна або надіслати рекламу, скористайтесь відповідними кнопками в меню.",
                        reply_markup=get_reply_buttons()
                    )
        return "ok", 200

    except Exception as e:
        cool_error_handler(e, context="webhook - outer")
        MainProtokol(str(e), 'Помилка webhook')
        # Возвращаем 200 чтобы Telegram не повторял бесконечно, но логируем ошибку
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
    # Лёгкий health-check: быстрый 200 без тяжёлых операций
    return "ok", 200

# ====== Self-pinger: опциональный внутренний пинг публичного /health или / ======
def self_pinger_loop(url: str, min_sec: int = 180, max_sec: int = 600, timeout: int = 5):
    if not url:
        MainProtokol("SELF_PING_URL пустой — пингер не запущен", "Pinger")
        return

    MainProtokol(f"Self-pinger запущен. URL: {url}", "Pinger")
    consecutive_failures = 0

    while True:
        try:
            wait = random.uniform(min_sec, max_sec)
            time.sleep(wait)

            headers = {"X-Self-Ping": "1", "User-Agent": "self-pinger/1.0"}
            try:
                resp = requests.get(url, headers=headers, timeout=timeout)
                if resp.ok:
                    consecutive_failures = 0
                    MainProtokol(f"Self-ping OK ({resp.status_code})", "Pinger")
                else:
                    consecutive_failures += 1
                    MainProtokol(f"Self-ping HTTP {resp.status_code}: {resp.text[:200]}", "Pinger")
            except Exception as e:
                consecutive_failures += 1
                MainProtokol(f"Self-ping exception: {str(e)}", "PingerError")
                try:
                    cool_error_handler(e, context="self_pinger_loop")
                except Exception:
                    pass

            if consecutive_failures >= 6:
                backoff = min(3600, max_sec * 2)
                MainProtokol(f"Много ошибок пинга, делаем backoff {backoff}s", "PingerBackoff")
                time.sleep(backoff)
        except Exception as outer:
            try:
                cool_error_handler(outer, context="self_pinger_loop: outer")
            except Exception:
                logger.exception("Ошибка в self_pinger_loop outer")
            time.sleep(30)

def start_self_pinger_thread():
    url = os.getenv("SELF_PING_URL", "").strip()
    if not url:
        MainProtokol("SELF_PING_URL не задан — self-pinger не будет запущен", "Pinger")
        return
    if "/webhook/" in url:
        MainProtokol("SELF_PING_URL содержит '/webhook/' — измените на корень или /health", "PingerWarning")
        return
    t = threading.Thread(target=self_pinger_loop, args=(url,), daemon=True, name="self-pinger")
    t.start()

if __name__ == "__main__":
    # Инициализация БД при старте (только при запуске процесса)
    try:
        init_db()
    except Exception as e:
        cool_error_handler(e, context="main: init_db")

    # Установка webhook (опционально) — WEBHOOK_URL должен быть задан в env
    def set_webhook():
        try:
            if not TOKEN:
                MainProtokol("TOKEN не установлен, webhook не настраивается", "Webhook")
                return
            if not WEBHOOK_URL:
                MainProtokol("WEBHOOK_URL не задан, webhook не настраивается", "Webhook")
                return
            r = requests.get(
                f"https://api.telegram.org/bot{TOKEN}/setWebhook",
                params={"url": WEBHOOK_URL}
            )
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

    # Запуск фоновых демонов
    try:
        threading.Thread(target=time_debugger, daemon=True).start()
    except Exception as e:
        cool_error_handler(e, context="main: start time_debugger")
    try:
        threading.Thread(target=stats_autoclear_daemon, daemon=True).start()
    except Exception as e:
        cool_error_handler(e, context="main: start stats_autoclear_daemon")

    # Запуск self-pinger (если указан SELF_PING_URL)
    try:
        start_self_pinger_thread()
    except Exception as e:
        cool_error_handler(e, context="main: start self-pinger")

    port = int(os.getenv("PORT", 5000))
    try:
        app.run(host="0.0.0.0", port=port)
    except Exception as e:
        cool_error_handler(e, context="main: app.run")
