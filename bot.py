# contents: исправленная и выверенная версия bot.py — синтаксически корректна, убраны опечатки и добавлен автосервис демонов
import os
import time
import json
import requests
import threading
import traceback
import datetime
from html import escape
from pathlib import Path
from flask import Flask, request

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ArgumentError

# ====== Опции ======
NOTIFY_USER_ON_ADD_STAT = True

# ====== Логирование ======
def MainProtokol(s, ts='Запис'):
    dt = time.strftime('%d.%m.%Y %H:%M:') + '00'
    try:
        with open('log.txt', 'a', encoding='utf-8') as f:
            f.write(f"{dt};{ts};{s}\n")
    except Exception as e:
        # Не ломаем процесс, просто печатаем
        print("Ошибка записи в лог:", e)

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
        pass
    try:
        MainProtokol(f"{exc_type}: {str(exc)}", ts='ERROR')
    except Exception:
        pass
    print(readable_msg)
    if send_to_telegram:
        try:
            admin_id = int(os.getenv("ADMIN_ID", "0"))
            token = os.getenv("API_TOKEN")
            if admin_id and token:
                try:
                    requests.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        data={"chat_id": admin_id, "text": f"⚠️ Error {exc_type} in {context}\n{str(exc)}"},
                        timeout=5
                    )
                except Exception:
                    pass
        except Exception:
            pass

# ====== Демоны ======
def time_debugger():
    while True:
        print("[DEBUG]", time.strftime('%Y-%m-%d %H:%M:%S'))
        time.sleep(300)

def stats_autoclear_daemon():
    while True:
        try:
            clear_stats_if_month_passed()
        except Exception as e:
            cool_error_handler(e, "stats_autoclear_daemon")
        time.sleep(3600)

# ====== UI / меню ======
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

# ====== Состояния и буферы ======
waiting_for_admin_message = set()
user_admin_category = {}
waiting_for_ad_message = set()
pending_mode = {}   # chat_id -> "ad"|"event"
pending_media = {}  # chat_id -> list of messages
waiting_for_admin = {}  # ADMIN_ID -> user_id (для ответа)
admin_adding_event = {}  # admin_id -> {'category': str, 'messages': [...]}
GLOBAL_LOCK = threading.Lock()

# ====== БД ======
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
        except Exception as e:
            cool_error_handler(e, "get_engine")
            fallback = os.path.join(os.path.dirname(os.path.abspath(__file__)), "events.db")
            _engine = create_engine(f"sqlite:///{fallback}", connect_args={"check_same_thread": False}, future=True)
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
    except Exception as e:
        cool_error_handler(e, "init_db")

def save_event(category):
    try:
        engine = get_engine()
        now = datetime.datetime.utcnow().isoformat()
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO events (category, dt) VALUES (:cat, :dt)"), {"cat": category, "dt": now})
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
            q_week = text("SELECT category, COUNT(*) as cnt FROM events WHERE dt >= :week GROUP BY category")
            q_month = text("SELECT category, COUNT(*) as cnt FROM events WHERE dt >= :month GROUP BY category")
            if engine.dialect.name == "sqlite":
                wk = conn.execute(q_week, {"week": week_threshold.isoformat()}).all()
                mo = conn.execute(q_month, {"month": month_threshold.isoformat()}).all()
            else:
                wk = conn.execute(q_week, {"week": week_threshold}).all()
                mo = conn.execute(q_month, {"month": month_threshold}).all()
            for row in wk:
                cat, cnt = row[0], int(row[1])
                if cat in res:
                    res[cat]['week'] = cnt
            for row in mo:
                cat, cnt = row[0], int(row[1])
                if cat in res:
                    res[cat]['month'] = cnt
    except Exception as e:
        cool_error_handler(e, "get_stats")
    return res

def clear_stats_if_month_passed():
    try:
        engine = get_engine()
        now = datetime.datetime.utcnow()
        month_threshold = now - datetime.timedelta(days=30)
        with engine.begin() as conn:
            if engine.dialect.name == "sqlite":
                conn.execute(text("DELETE FROM events WHERE dt < :month"), {"month": month_threshold.isoformat()})
            else:
                conn.execute(text("DELETE FROM events WHERE dt < :month"), {"month": month_threshold})
    except Exception as e:
        cool_error_handler(e, "clear_stats_if_month_passed")

# Инициализация
init_db()

# ====== Конфигурация бота ======
TOKEN = os.getenv("API_TOKEN")
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except Exception:
    ADMIN_ID = 0

WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "").strip()
if TOKEN and WEBHOOK_HOST:
    WEBHOOK_URL = f"https://{WEBHOOK_HOST}/webhook/{TOKEN}"
else:
    WEBHOOK_URL = ""

def set_webhook():
    if not TOKEN or not WEBHOOK_URL:
        return
    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/setWebhook", params={"url": WEBHOOK_URL}, timeout=5)
    except Exception as e:
        cool_error_handler(e, "set_webhook")

set_webhook()

# ====== UI helpers ======
def send_chat_action(chat_id, action='typing'):
    if not TOKEN:
        return
    try:
        requests.post(f'https://api.telegram.org/bot{TOKEN}/sendChatAction', data={'chat_id': chat_id, 'action': action}, timeout=3)
    except Exception:
        pass

def send_message(chat_id, text, reply_markup=None, parse_mode=None, timeout=8):
    if not TOKEN:
        return None
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage'
    payload = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    if parse_mode:
        payload['parse_mode'] = parse_mode
    try:
        resp = requests.post(url, data=payload, timeout=timeout)
        if not resp.ok:
            MainProtokol(resp.text, 'Помилка надсилання')
        return resp
    except Exception as e:
        cool_error_handler(e, context="send_message")
        return None

def _get_reply_markup_for_admin(user_id: int, orig_chat_id: int = None, orig_msg_id: int = None, allow_addstat: bool = True):
    row = [{"text": "✉️ Відповісти", "callback_data": f"reply_{user_id}"}]
    if allow_addstat and orig_chat_id is not None and orig_msg_id is not None:
        row.append({"text": "➕ Додати до статистики", "callback_data": f"addstat_{orig_chat_id}_{orig_msg_id}"})
    return {"inline_keyboard": [row]}

def build_welcome_message(user: dict) -> str:
    first = (user.get('first_name') or "").strip()
    last = (user.get('last_name') or "").strip()
    display = (first + (" " + last if last else "")).strip() or "Друже"
    is_premium = user.get('is_premium', False)
    vip_badge = " ✨" if is_premium else ""
    name_html = escape(display)
    msg = (
        "<pre>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</pre>\n"
        f"<b>✨ Ласкаво просимо, {name_html}{vip_badge}!</b>\n\n"
        "<i>Ви опинилися у преміальному інтерфейсі нашого сервісу.</i>\n\n"
        "<b>Що доступно прямо зараз:</b>\n"
        "• 📝 Швидко повідомити про подію\n"
        "• 📊 Переглянути статистику по категоріях\n"
        "• 📣 Надіслати рекламне повідомлення\n\n"
        "<i>Натисніть одну з кнопок внизу, щоб почати.</i>\n"
        "<pre>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</pre>"
    )
    return msg

def build_admin_info(message: dict, category: str = None) -> str:
    try:
        user = message.get('from', {}) or {}
        first = (user.get('first_name') or "").strip()
        last = (user.get('last_name') or "").strip()
        username = user.get('username')
        user_id = user.get('id')
        is_premium = user.get('is_premium', None)

        display_name = (first + (" " + last if last else "")).strip() or "Без імені"
        display_html = escape(display_name)

        if username:
            profile_url = f"https://t.me/{username}"
            profile_html = f"<a href=\"{profile_url}\">@{escape(username)}</a>"
        else:
            profile_url = f"tg://user?id={user_id}"
            profile_html = f"<a href=\"{profile_url}\">Відкрити профіль</a>"

        contact = message.get('contact')
        contact_html = ""
        if isinstance(contact, dict):
            phone = contact.get('phone_number')
            contact_name = (contact.get('first_name') or "") + ((" " + contact.get('last_name')) if contact.get('last_name') else "")
            contact_parts = []
            if contact_name:
                contact_parts.append(escape(contact_name.strip()))
            if phone:
                contact_parts.append(escape(phone))
            if contact_parts:
                contact_html = ", ".join(contact_parts)

        location = message.get('location')
        location_html = ""
        if isinstance(location, dict):
            lat = location.get('latitude')
            lon = location.get('longitude')
            if lat is not None and lon is not None:
                location_html = f"{lat}, {lon}"

        msg_id = message.get('message_id', '-')
        msg_date = message.get('date')
        try:
            date_str = datetime.datetime.utcfromtimestamp(int(msg_date)).strftime('%Y-%m-%d %H:%M:%S UTC') if msg_date else '-'
        except Exception:
            date_str = str(msg_date or '-')

        text = message.get('text') or message.get('caption') or ''
        category_html = escape(category) if category else None

        parts = []
        parts.append("<pre>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</pre>")
        parts.append("<b>📩 Нове повідомлення</b>")
        parts.append("")
        name_line = f"<b>{display_html}</b>"
        if is_premium:
            name_line += " ✨"
        parts.append(name_line)
        parts.append(f"<b>Профіль:</b> {profile_html}")
        parts.append(f"<b>ID:</b> {escape(str(user_id)) if user_id is not None else '-'}")
        if contact_html:
            parts.append(f"<b>Телефон:</b> {contact_html}")
        if location_html:
            parts.append(f"<b>Локація:</b> {escape(location_html)}")
        if category_html:
            parts.append(f"<b>Категорія:</b> {category_html}")
        parts.append("")
        parts.append(f"<b>Message ID:</b> {escape(str(msg_id))}")
        parts.append(f"<b>Дата:</b> {escape(str(date_str))}")
        if text:
            display_text = text if len(text) <= 2000 else text[:1997] + "..."
            parts.append("")
            parts.append("<b>Текст / Опис:</b>")
            parts.append("<pre>{}</pre>".format(escape(display_text)))
        parts.append("")
        parts.append("<i>Повідомлення відформатовано для зручного перегляду.</i>")
        parts.append("<pre>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</pre>")
        return "\n".join(parts)
    except Exception as e:
        cool_error_handler(e, "build_admin_info")
        return "Нове повідомлення."

def _post_request(url, data=None, files=None, timeout=10):
    try:
        r = requests.post(url, data=data, files=files, timeout=timeout)
        if not r.ok:
            MainProtokol(f"Request failed: {url} -> {r.status_code} {r.text}", ts='WARN')
        return r
    except Exception as e:
        MainProtokol(f"Network error for {url}: {str(e)}", ts='ERROR')
        return None

def forward_admin_message_to_user(user_id: int, admin_msg: dict):
    try:
        if not user_id:
            return False
        caption = admin_msg.get('caption') or admin_msg.get('text') or ""
        safe_caption = escape(caption) if caption else None
        if 'photo' in admin_msg:
            file_id = admin_msg['photo'][-1].get('file_id')
            url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
            payload = {"chat_id": user_id, "photo": file_id}
            if safe_caption:
                payload["caption"] = f"💬 Відповідь адміністратора:\n<pre>{safe_caption}</pre>"
                payload["parse_mode"] = "HTML"
            _post_request(url, data=payload)
            return True
        if 'video' in admin_msg:
            file_id = admin_msg['video'].get('file_id')
            url = f"https://api.telegram.org/bot{TOKEN}/sendVideo"
            payload = {"chat_id": user_id, "video": file_id}
            if safe_caption:
                payload["caption"] = f"💬 Відповідь адміністратора:\n<pre>{safe_caption}</pre>"
                payload["parse_mode"] = "HTML"
            _post_request(url, data=payload)
            return True
        if 'document' in admin_msg:
            file_id = admin_msg['document'].get('file_id')
            filename = admin_msg.get('document', {}).get('file_name', 'документ')
            url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
            payload = {"chat_id": user_id, "document": file_id}
            if safe_caption:
                payload["caption"] = f"💬 Відповідь адміністратора:\n<pre>{safe_caption}</pre>"
                payload["parse_mode"] = "HTML"
            else:
                payload["caption"] = f"💬 Відповідь адміністратора — {escape(filename)}"
            _post_request(url, data=payload)
            return True
        if caption:
            send_message(user_id, f"💬 Відповідь адміністратора:\n<pre>{escape(caption)}</pre>", parse_mode="HTML")
            return True
        send_message(user_id, "💬 Відповідь адміністратора (без тексту).")
        return True
    except Exception as e:
        cool_error_handler(e, "forward_admin_message_to_user")
        return False

def send_media_collection_keyboard(chat_id):
    kb = {"keyboard": [[{"text": "✅ Надіслати"}], [{"text": "❌ Скасувати"}]], "resize_keyboard": True, "one_time_keyboard": False}
    send_message(chat_id, "Надсилайте фото/відео/документи/текст. Коли закінчите — натисніть «✅ Надіслати».", reply_markup=kb)

def _collect_media_summary_and_payloads(msgs):
    media_items = []
    doc_msgs = []
    leftover_texts = []
    captions_for_media = []
    other_texts = []
    for m in msgs:
        txt = m.get('text') or m.get('caption') or ''
        if 'photo' in m:
            try:
                file_id = m['photo'][-1]['file_id']
            except Exception:
                file_id = None
            if file_id:
                media_items.append({"type": "photo", "media": file_id, "orig_text": txt})
                if txt:
                    captions_for_media.append(txt)
        elif 'video' in m:
            file_id = m['video'].get('file_id')
            if file_id:
                media_items.append({"type": "video", "media": file_id, "orig_text": txt})
                if txt:
                    captions_for_media.append(txt)
        elif 'animation' in m:
            file_id = m['animation'].get('file_id')
            if file_id:
                media_items.append({"type": "animation", "media": file_id, "orig_text": txt})
                if txt:
                    captions_for_media.append(txt)
        elif 'document' in m:
            doc_msgs.append({"file_id": m['document'].get('file_id'), "file_name": m['document'].get('file_name'), "text": txt})
        else:
            if txt:
                other_texts.append(txt)
            else:
                t = []
                for k in ['sticker', 'voice', 'contact', 'location', 'audio']:
                    if k in m:
                        t.append(k)
                if t:
                    other_texts.append(f"[contains: {','.join(t)}]")
    combined_caption = None
    if media_items and captions_for_media:
        joined = "\n\n".join(captions_for_media)
        if len(joined) > 1000:
            joined = joined[:997] + "..."
        combined_caption = joined
    for idx, mi in enumerate(media_items):
        if idx == 0 and combined_caption:
            mi['caption'] = combined_caption
        else:
            mi['caption'] = ""
    leftover_texts = other_texts
    return media_items, doc_msgs, leftover_texts

def send_compiled_media_to_admin(chat_id):
    with GLOBAL_LOCK:
        msgs = list(pending_media.get(chat_id, []))
    if not msgs:
        send_message(chat_id, "Немає медіа для надсилання.")
        return
    with GLOBAL_LOCK:
        is_event_mode = (pending_mode.get(chat_id) == "event")
        if is_event_mode:
            m_category = user_admin_category.get(chat_id, 'Без категорії')
        else:
            m_category = None

    # НЕ сохраняем автоматически в статистику для event-mode (требование)
    media_items, doc_msgs, leftover_texts = _collect_media_summary_and_payloads(msgs)

    orig_chat_id = msgs[0].get('chat', {}).get('id')
    orig_msg_id = msgs[0].get('message_id')
    orig_user_id = msgs[0].get('from', {}).get('id')

    allow_addstat = not is_event_mode
    admin_info = build_admin_info(msgs[0], category=m_category)
    reply_markup = _get_reply_markup_for_admin(orig_user_id, orig_chat_id, orig_msg_id, allow_addstat=allow_addstat)
    send_message(ADMIN_ID, admin_info, reply_markup=reply_markup, parse_mode="HTML")

    try:
        if media_items:
            if len(media_items) > 1:
                sendmedia = []
                for mi in media_items:
                    obj = {"type": mi["type"], "media": mi["media"]}
                    if mi.get("caption"):
                        obj["caption"] = mi["caption"]
                        obj["parse_mode"] = "HTML"
                    sendmedia.append(obj)
                requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMediaGroup", data={"chat_id": ADMIN_ID, "media": json.dumps(sendmedia)}, timeout=10)
            else:
                mi = media_items[0]
                if mi["type"] == "photo":
                    payload = {"chat_id": ADMIN_ID, "photo": mi["media"]}
                    if mi.get("caption"):
                        payload["caption"] = mi["caption"]
                        payload["parse_mode"] = "HTML"
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", data=payload, timeout=10)
                elif mi["type"] == "video":
                    payload = {"chat_id": ADMIN_ID, "video": mi["media"]}
                    if mi.get("caption"):
                        payload["caption"] = mi["caption"]
                        payload["parse_mode"] = "HTML"
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendVideo", data=payload, timeout=10)
                elif mi["type"] == "animation":
                    payload = {"chat_id": ADMIN_ID, "animation": mi["media"]}
                    if mi.get("caption"):
                        payload["caption"] = mi["caption"]
                        payload["parse_mode"] = "HTML"
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendAnimation", data=payload, timeout=10)
    except Exception as e:
        MainProtokol(str(e), 'media_send_error')

    for d in doc_msgs:
        try:
            payload = {"chat_id": ADMIN_ID, "document": d["file_id"]}
            if d.get("text"):
                payload["caption"] = d["text"] if len(d["text"]) <= 1000 else d["text"][:997] + "..."
                payload["parse_mode"] = "HTML"
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendDocument", data=payload, timeout=10)
        except Exception as e:
            MainProtokol(str(e), 'doc_send_error')

    if leftover_texts:
        try:
            combined = "\n\n".join(leftover_texts)
            send_message(ADMIN_ID, f"<b>Текст від користувача:</b>\n<pre>{escape(combined)}</pre>", parse_mode="HTML")
        except Exception as e:
            MainProtokol(str(e), 'text_send_error')

    with GLOBAL_LOCK:
        pending_media.pop(chat_id, None)
        pending_mode.pop(chat_id, None)

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
        week = stats.get(cat, {}).get('week', 0)
        month = stats.get(cat, {}).get('month', 0)
        lines.append(f"{name.ljust(max_cat_len)}  {str(week):>6}  {str(month):>6}")
    content = "\n".join(lines)
    return "<pre>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" + content + "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━</pre>"

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    global pending_media, pending_mode, admin_adding_event
    try:
        data_raw = request.get_data(as_text=True)
        update = json.loads(data_raw)

        # CALLBACK
        if 'callback_query' in update:
            call = update['callback_query']
            chat_id = call['from']['id']
            data = call.get('data', '')

            # ответ админу
            if data.startswith("reply_") and chat_id == ADMIN_ID:
                try:
                    user_id = int(data.split("_", 1)[1])
                    with GLOBAL_LOCK:
                        waiting_for_admin[ADMIN_ID] = user_id
                    send_message(ADMIN_ID, f"✍️ Введіть відповідь для користувача {user_id} (будь-який текст або файл):")
                except Exception as e:
                    cool_error_handler(e, "webhook: reply_")

            # админ нажал добавить в статистику
            elif data.startswith("addstat_") and chat_id == ADMIN_ID:
                try:
                    parts = data.split("_", 2)
                    if len(parts) == 3:
                        orig_chat_id = int(parts[1])
                        orig_msg_id = int(parts[2])
                        kb = {"inline_keyboard": []}
                        row = []
                        for idx, cat in enumerate(ADMIN_SUBCATEGORIES):
                            row.append({"text": cat, "callback_data": f"confirm_addstat|{orig_chat_id}|{orig_msg_id}|{idx}"})
                            if len(row) == 2:
                                kb["inline_keyboard"].append(row)
                                row = []
                        if row:
                            kb["inline_keyboard"].append(row)
                        send_message(ADMIN_ID, "Оберіть категорію для додавання до статистики:", reply_markup=kb)
                    else:
                        send_message(ADMIN_ID, "Невірний формат callback для додавання в статистику.")
                except Exception as e:
                    cool_error_handler(e, "webhook: addstat_")

            elif data.startswith("confirm_addstat|") and chat_id == ADMIN_ID:
                try:
                    parts = data.split("|")
                    if len(parts) == 4:
                        orig_chat_id = int(parts[1])
                        orig_msg_id = int(parts[2])
                        cat_idx = int(parts[3])
                        if 0 <= cat_idx < len(ADMIN_SUBCATEGORIES):
                            category = ADMIN_SUBCATEGORIES[cat_idx]
                            save_event(category)
                            send_message(ADMIN_ID, f"✅ Повідомлення додано до статистики як: <b>{escape(category)}</b>", parse_mode="HTML", reply_markup=get_reply_buttons())
                            if NOTIFY_USER_ON_ADD_STAT:
                                try:
                                    send_message(orig_chat_id, f"ℹ️ Ваше повідомлення було додано до статистики як: <b>{escape(category)}</b>", parse_mode="HTML")
                                except Exception as e:
                                    MainProtokol(str(e), 'notify_user_add_stat_err')
                        else:
                            send_message(ADMIN_ID, "Невірний індекс категорії.")
                    else:
                        send_message(ADMIN_ID, "Невірний формат callback confirm_addstat.")
                except Exception as e:
                    cool_error_handler(e, "webhook: confirm_addstat")

            else:
                # другие callback'ы: about, schedule, write_admin
                if data == "about":
                    send_message(call['from']['id'], "Ми створюємо телеграм-ботів та сервіси для вашого бізнесу і життя.\nДізнатись більше: наші канали")
                elif data == "schedule":
                    send_message(call['from']['id'], "Наш бот приймає повідомлення 24/7. Ми відповідаємо якнайшвидше.")
                elif data == "write_admin":
                    with GLOBAL_LOCK:
                        waiting_for_admin_message.add(call['from']['id'])
                    send_message(call['from']['id'], "✍️ Напишіть повідомлення адміністратору (текст/фото/документ):")
            return "ok", 200

        # MESSAGE
        if 'message' in update:
            message = update['message']
            chat_id = message['chat']['id']
            from_id = message['from']['id']
            text = message.get('text', '')

            with GLOBAL_LOCK:
                in_pending = chat_id in pending_mode
            if in_pending:
                if text == "✅ Надіслати":
                    send_compiled_media_to_admin(chat_id)
                    send_message(chat_id, "✅ Ваші дані відправлено. Дякуємо!", reply_markup=get_reply_buttons())
                    return "ok", 200
                elif text == "❌ Скасувати":
                    with GLOBAL_LOCK:
                        pending_media.pop(chat_id, None)
                        pending_mode.pop(chat_id, None)
                    send_message(chat_id, "❌ Скасовано.", reply_markup=get_reply_buttons())
                    return "ok", 200
                else:
                    with GLOBAL_LOCK:
                        pending_media.setdefault(chat_id, []).append(message)
                    send_message(chat_id, "Додано до пакету. Продовжуйте надсилати або натисніть ✅ Надіслати.", reply_markup={
                        "keyboard": [[{"text": "✅ Надіслати"}, {"text": "❌ Скасувати"}]],
                        "resize_keyboard": True,
                        "one_time_keyboard": False
                    })
                    return "ok", 200

            with GLOBAL_LOCK:
                admin_flow = admin_adding_event.get(from_id)
            if admin_flow:
                # admin manual add flow (unchanged)
                if text == "✅ Підтвердити":
                    with GLOBAL_LOCK:
                        flow = admin_adding_event.pop(from_id, None)
                    if flow:
                        category = flow.get("category")
                        msgs = flow.get("messages", [])
                        try:
                            save_event(category)
                        except Exception as e:
                            cool_error_handler(e, "save_event (admin add)")
                            send_message(ADMIN_ID, "❌ Помилка при збереженні події в БД.")
                            return "ok", 200
                        media_items, doc_msgs, leftover_texts = _collect_media_summary_and_payloads(msgs)
                        cnt_photos = sum(1 for m in media_items if m["type"] == "photo")
                        cnt_videos = sum(1 for m in media_items if m["type"] == "video")
                        cnt_animations = sum(1 for m in media_items if m["type"] == "animation")
                        cnt_docs = len(doc_msgs)
                        cnt_texts = len(leftover_texts)
                        summary_lines = [
                            "<b>✅ Подія додана</b>",
                            f"<b>Категорія:</b> {escape(str(category))}",
                            f"<b>Фото:</b> {cnt_photos}",
                            f"<b>Відео:</b> {cnt_videos}",
                            f"<b>Анімації:</b> {cnt_animations}",
                            f"<b>Документи:</b> {cnt_docs}",
                            f"<b>Тексти:</b> {cnt_texts}",
                        ]
                        send_message(ADMIN_ID, "\n".join(summary_lines), parse_mode="HTML", reply_markup=get_reply_buttons())
                        return "ok", 200
                    else:
                        send_message(ADMIN_ID, "Нема активного флоу додавання події.")
                        return "ok", 200
                elif text == "❌ Відмінити":
                    with GLOBAL_LOCK:
                        admin_adding_event.pop(from_id, None)
                    send_message(ADMIN_ID, "❌ Додавання події скасовано.", reply_markup=get_reply_buttons())
                    return "ok", 200
                else:
                    with GLOBAL_LOCK:
                        admin_adding_event.setdefault(from_id, {"category": admin_flow["category"], "messages": []})
                        admin_adding_event[from_id]["messages"].append(message)
                    send_message(ADMIN_ID, "Додано до події. Продовжуйте надсилати матеріали або натисніть ✅ Підтвердити / ❌ Відмінити.")
                    return "ok", 200

            with GLOBAL_LOCK:
                waiting_user = waiting_for_admin.get(ADMIN_ID)
            if from_id == ADMIN_ID and waiting_user:
                with GLOBAL_LOCK:
                    user_to_send = waiting_for_admin.pop(ADMIN_ID, None)
                success = False
                if user_to_send:
                    success = forward_admin_message_to_user(user_to_send, message)
                if success:
                    send_message(ADMIN_ID, f"✅ Повідомлення надіслано користувачу {user_to_send}.", reply_markup=get_reply_buttons())
                else:
                    send_message(ADMIN_ID, f"❌ Не вдалося надіслати повідомлення користувачу {user_to_send}.", reply_markup=get_reply_buttons())
                return "ok", 200

            if text == '/start':
                send_chat_action(chat_id, 'typing')
                time.sleep(0.25)
                user = message.get('from', {})
                welcome = build_welcome_message(user)
                send_message(chat_id, welcome, reply_markup=get_reply_buttons(), parse_mode='HTML')
            elif text in MAIN_MENU:
                if text == "✨ Головне":
                    send_message(chat_id, "✨ Ви в головному меню.", reply_markup=get_reply_buttons())
                elif text == "📢 Про нас":
                    send_message(chat_id, "Ми створюємо телеграм-ботів та сервіси для вашого бізнесу і життя.\nДізнатись більше: наші канали", reply_markup=get_reply_buttons())
                elif text == "🕰️ Графік роботи":
                    send_message(chat_id, "Ми працюємо цілодобово. Звертайтесь у будь-який час.", reply_markup=get_reply_buttons())
                elif text == "📝 Повідомити про подію":
                    send_message(chat_id, "Оберіть тип події:", reply_markup=get_admin_subcategory_buttons())
                elif text == "📊 Статистика подій":
                    stats = get_stats()
                    send_message(chat_id, format_stats_message(stats), parse_mode='HTML')
                elif text == "📣 Реклама":
                    with GLOBAL_LOCK:
                        pending_mode[chat_id] = "ad"
                        pending_media[chat_id] = []
                    send_media_collection_keyboard(chat_id)
            elif text in ADMIN_SUBCATEGORIES:
                with GLOBAL_LOCK:
                    user_admin_category[chat_id] = text
                    pending_mode[chat_id] = "event"
                    pending_media[chat_id] = []
                send_media_collection_keyboard(chat_id)
            else:
                # входящее сообщение от пользователя — отправляем админу карточку с кнопками (reply + addstat)
                if from_id != ADMIN_ID:
                    orig_chat_id = chat_id
                    orig_msg_id = message.get('message_id')
                    admin_info = build_admin_info(message)
                    orig_user_id = message.get('from', {}).get('id')
                    # allow_addstat=True для обычных сообщений; если сообщение было собрано через pending_mode==event,
                    # то при отправке компиляции send_compiled_media_to_admin мы передадим allow_addstat=False
                    reply_markup = _get_reply_markup_for_admin(orig_user_id, orig_chat_id, orig_msg_id, allow_addstat=True)
                    send_message(ADMIN_ID, admin_info, reply_markup=reply_markup, parse_mode="HTML")
                    send_message(chat_id, "Дякуємо! Ваше повідомлення отримано — наш адміністратор перевірить його.", reply_markup=get_reply_buttons())

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

if __name__ == "__main__":
    try:
        threading.Thread(target=time_debugger, daemon=True).start()
    except Exception as e:
        cool_error_handler(e, context="main: start time_debugger")
    try:
        threading.Thread(target=stats_autoclear_daemon, daemon=True).start()
    except Exception as e:
        cool_error_handler(e, context="main: start stats_autoclear_daemon")
    port = int(os.getenv("PORT", 5000))
    try:
        app.run(host="0.0.0.0", port=port)
    except Exception as e:
        cool_error_handler(e, context="main: app.run")
