# contents: расширение информации, отправляемой админу — больше полей и аккуратное HTML-оформление
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

# Библиотека для работы с разными БД (Postgres/SQLite)
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ArgumentError

# ====== Логирование ======
def MainProtokol(s, ts='Запис'):
    dt = time.strftime('%d.%m.%Y %H:%M:') + '00'
    try:
        with open('log.txt', 'a', encoding='utf-8') as f:
            f.write(f"{dt};{ts};{s}\n")
    except Exception as e:
        print("Ошибка записи в лог:", e)

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
        print("Не удалось записать в 'critical_errors.log':", write_err)
    try:
        MainProtokol(f"{exc_type}: {str(exc)}", ts='ERROR')
    except Exception as log_err:
        print("MainProtokol вернул ошибку:", log_err)
    print(readable_msg)
    if send_to_telegram:
        try:
            admin_id = int(os.getenv("ADMIN_ID", "0"))
            token = os.getenv("API_TOKEN")
            if admin_id and token:
                try:
                    r = requests.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        data={
                            "chat_id": admin_id,
                            "text": f"⚠️ Критична помилка!\nТип: {exc_type}\nКонтекст: {context}\n\n{str(exc)}",
                            "disable_web_page_preview": True
                        },
                        timeout=5
                    )
                    if not r.ok:
                        MainProtokol(f"Telegram notify failed: {r.status_code} {r.text}", ts='WARN')
                except Exception as telegram_err:
                    print("Не удалось отправить уведомление в Telegram:", telegram_err)
        except Exception as env_err:
            print("Ошибка при подготовке уведомления в Telegram:", env_err)

# ====== Фоновый отладчик времени (каждые 5 минут) ======
def time_debugger():
    while True:
        print("[DEBUG]", time.strftime('%Y-%m-%d %H:%M:%S'))
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

# ====== Состояния ожидания ======
waiting_for_admin_message = set()
user_admin_category = {}
waiting_for_ad_message = set()
pending_mode = {}   # chat_id -> "ad"|"event"
pending_media = {}  # chat_id -> list of message dicts
waiting_for_admin = {}

# Блокировка для потокобезопасных операций над глобальными структурами
GLOBAL_LOCK = threading.Lock()

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
            if not db_url:
                raise ValueError("DATABASE_URL is empty")
            if db_url.startswith("sqlite:///"):
                _engine = create_engine(db_url, connect_args={"check_same_thread": False}, future=True)
                print(f"[DEBUG] Using SQLite DB URL: {db_url}")
            else:
                if '://' not in db_url:
                    raise ArgumentError(f"Invalid DB URL (missing scheme): {db_url}")
                _engine = create_engine(db_url, future=True)
                print(f"[DEBUG] Using DB URL: {db_url}")
        except ArgumentError as e:
            cool_error_handler(e, "get_engine (ArgumentError)")
            MainProtokol(f"Invalid DATABASE_URL: {db_url}", ts='WARN')
            try:
                fallback_sqlite = os.path.join(os.path.dirname(os.path.abspath(__file__)), "events.db")
                fallback_url = f"sqlite:///{fallback_sqlite}"
                _engine = create_engine(fallback_url, connect_args={"check_same_thread": False}, future=True)
                print(f"[WARN] Fallback to SQLite at {fallback_sqlite} due to invalid DATABASE_URL.")
                MainProtokol("Fallback to SQLite due to invalid DATABASE_URL", ts='WARN')
            except Exception as e2:
                cool_error_handler(e2, "get_engine (fallback sqlite)")
                raise
        except ImportError as e:
            cool_error_handler(e, "get_engine (ImportError)")
            MainProtokol("DB driver import failed, falling back to local SQLite", ts='WARN')
            try:
                fallback_sqlite = os.path.join(os.path.dirname(os.path.abspath(__file__)), "events.db")
                fallback_url = f"sqlite:///{fallback_sqlite}"
                _engine = create_engine(fallback_url, connect_args={"check_same_thread": False}, future=True)
                print(f"[WARN] Fallback to SQLite at {fallback_sqlite} due to ImportError for DB driver.")
            except Exception as e2:
                cool_error_handler(e2, "get_engine (fallback sqlite after ImportError)")
                raise
        except Exception as e:
            cool_error_handler(e, "get_engine")
            MainProtokol(f"get_engine general exception: {str(e)}", ts='ERROR')
            try:
                fallback_sqlite = os.path.join(os.path.dirname(os.path.abspath(__file__)), "events.db")
                fallback_url = f"sqlite:///{fallback_sqlite}"
                _engine = create_engine(fallback_url, connect_args={"check_same_thread": False}, future=True)
                print(f"[WARN] Fallback to SQLite at {fallback_sqlite} due to engine creation error.")
                MainProtokol("Fallback to SQLite due to engine creation error", ts='WARN')
            except Exception as e2:
                cool_error_handler(e2, "get_engine (fallback sqlite after general exception)")
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
        MainProtokol(str(e), 'get_stats_exception')
        return {cat: {'week': 0, 'month': 0} for cat in ADMIN_SUBCATEGORIES}

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

# Инициализация БД при старте
init_db()

# ====== Конфигурация ======
TOKEN = os.getenv("API_TOKEN")
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except Exception:
    ADMIN_ID = 0

# WEBHOOK: можно задать хост в переменной WEBHOOK_HOST, иначе webhook не устанавливается автоматически
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "").strip()
if TOKEN and WEBHOOK_HOST:
    WEBHOOK_URL = f"https://{WEBHOOK_HOST}/webhook/{TOKEN}"
else:
    WEBHOOK_URL = ""

# ====== Установка webhook ======
def set_webhook():
    if not TOKEN:
        print("[WARN] TOKEN is not set, webhook not initialized.")
        return
    if not WEBHOOK_URL:
        print("[INFO] WEBHOOK_HOST not set; skip setting webhook.")
        return
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/setWebhook",
            params={"url": WEBHOOK_URL},
            timeout=5
        )
        if r.ok:
            print("Webhook успешно установлен!")
        else:
            print("Ошибка при установке webhook:", r.status_code, r.text)
            MainProtokol(f"setWebhook failed: {r.status_code} {r.text}", ts='WARN')
    except Exception as e:
        cool_error_handler(e, context="set_webhook")

set_webhook()

# ====== UI helpers ======
def send_chat_action(chat_id, action='typing'):
    if not TOKEN:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{TOKEN}/sendChatAction',
            data={'chat_id': chat_id, 'action': action},
            timeout=3
        )
    except Exception:
        pass

# Прекрасное приветствие — делает бот «дорогим»
def build_welcome_message(user: dict) -> str:
    try:
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
    except Exception as e:
        cool_error_handler(e, "build_welcome_message")
        return "Ласкаво просимо! Використайте меню для початку."

# ====== Отправка сообщений (parse_mode поддерживается) ======
def send_message(chat_id, text, reply_markup=None, parse_mode=None, timeout=8):
    if not TOKEN:
        print("[WARN] Попытка отправки сообщения без TOKEN")
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
    try:
        resp = requests.post(url, data=payload, timeout=timeout)
        if not resp.ok:
            MainProtokol(resp.text, 'Помилка надсилання')
        return resp
    except Exception as e:
        cool_error_handler(e, context="send_message")
        MainProtokol(str(e), 'Помилка мережі')
        return None

def _get_reply_markup_for_admin(user_id: int):
    return {
        "inline_keyboard": [
            [{"text": "✉️ Відповісти", "callback_data": f"reply_{user_id}"}]
        ]
    }

# ====== Новый helper: строим расширённую карточку для админа ======
def build_admin_info(message: dict, category: str = None) -> str:
    """
    Обновленная, окультуренная карточка для админа:
    - Убираем поля: language, is_bot, тип чата (как минимум).
    - Добавляем аккуратный профиль пользователя: имя, ссылка на профиль (если есть username) или tg://user?id=,
      ID, признак премиума (значок), контакт/телефон (если прислан), локейшн (если прислан).
    - Сохраняем информацию о медиа/типах и тексте, но оформляем более компактно и читабельно.
    """
    try:
        user = message.get('from', {}) or {}
        chat = message.get('chat', {}) or {}
        first = (user.get('first_name') or "").strip()
        last = (user.get('last_name') or "").strip()
        username = user.get('username')
        user_id = user.get('id')
        is_premium = user.get('is_premium', None)

        # Display name
        display_name = (first + (" " + last if last else "")).strip() or "Без імені"
        display_html = escape(display_name)

        # Profile link: prefer t.me/username if present, otherwise tg://user?id=
        if username:
            profile_url = f"https://t.me/{username}"
            profile_label = f"@{escape(username)}"
            profile_html = f"<a href=\"{profile_url}\">{profile_label}</a>"
        else:
            profile_url = f"tg://user?id={user_id}"
            profile_label = "Відкрити профіль"
            profile_html = f"<a href=\"{profile_url}\">{escape(profile_label)}</a>"

        # Contact and location if present in the message (these are commonly present in forwarded contact/location)
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

        # Message meta
        msg_id = message.get('message_id', '-')
        msg_date = message.get('date')
        try:
            date_str = datetime.datetime.utcfromtimestamp(int(msg_date)).strftime('%Y-%m-%d %H:%M:%S UTC') if msg_date else '-'
        except Exception:
            date_str = str(msg_date or '-')

        text = message.get('text') or message.get('caption') or ''
        entities = message.get('entities') or message.get('caption_entities') or []
        entities_summary = ", ".join(e.get('type') for e in entities if e.get('type')) or "-"

        # Media summary: list present media keys in a compact form
        media_keys = []
        media_candidates = ['photo', 'video', 'document', 'audio', 'voice', 'animation', 'sticker', 'contact', 'location']
        for k in media_candidates:
            if k in message:
                media_keys.append(k)
        media_summary = ", ".join(media_keys) if media_keys else "-"

        # Reply information (if the message is a reply)
        reply_info = "-"
        if 'reply_to_message' in message and isinstance(message['reply_to_message'], dict):
            r = message['reply_to_message']
            rfrom = r.get('from', {})
            rname = (rfrom.get('first_name','') or '') + ((' ' + rfrom.get('last_name')) if rfrom.get('last_name') else '')
            reply_info = f"id:{r.get('message_id','-')} from:{escape(rname or '-')}"

        # Category (если передано)
        category_html = escape(category) if category else None

        # Собираем аккуратно оформленную карточку
        parts = []
        parts.append("<pre>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</pre>")
        parts.append("<b>📩 Нове повідомлення</b>")
        parts.append("")

        # Профиль — крупно
        name_line = f"<b>{display_html}</b>"
        if is_premium:
            name_line += " ✨"
        parts.append(name_line)

        # Профиль и ID
        parts.append(f"<b>Профіль:</b> {profile_html}")
        parts.append(f"<b>ID:</b> {escape(str(user_id)) if user_id is not None else '-'}")

        # Контакт / Локація (если есть)
        if contact_html:
            parts.append(f"<b>Телефон:</b> {contact_html}")
        if location_html:
            parts.append(f"<b>Локація:</b> {escape(location_html)}")

        # Категорія (если есть)
        if category_html:
            parts.append(f"<b>Категорія:</b> {category_html}")

        # Техническая краткая секция (без лишних полей)
        parts.append("")
        parts.append(f"<b>Message ID:</b> {escape(str(msg_id))}")
        parts.append(f"<b>Дата:</b> {escape(str(date_str))}")
        parts.append(f"<b>Медіа:</b> {escape(media_summary)}")
        parts.append(f"<b>Entities:</b> {escape(entities_summary)}")
        parts.append(f"<b>Reply to:</b> {escape(reply_info)}")

        # Текст / Описание — моноширинный блок
        parts.append("")
        if text:
            # Ограничим длину отображаемого текста для аккуратности
            display_text = text if len(text) <= 2000 else text[:1997] + "..."
            parts.append("<b>Текст / Опис:</b>")
            parts.append("<pre>{}</pre>".format(escape(display_text)))
        else:
            parts.append("<i>Немає тексту</i>")

        parts.append("")
        parts.append("<i>Повідомлення відформатовано для зручного перегляду.</i>")
        parts.append("<pre>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</pre>")

        return "\n".join(parts)
    except Exception as e:
        cool_error_handler(e, "build_admin_info")
        try:
            return f"Повідомлення від користувача.  ID: {escape(str(message.get('from', {}).get('id', '-')))}"
        except Exception:
            return "Нове повідомлення."

# ====== НОВЫЕ функции для пакетной отправки медиа ======

def send_media_collection_keyboard(chat_id):
    kb = {
        "keyboard": [
            [{"text": "✅ Надіслати"}],
            [{"text": "❌ Скасувати"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }
    send_message(
        chat_id,
        "Надсилайте усі потрібні фото, відео, документи та/або текст (кілька повідомлень). Як закінчите — натисніть «✅ Надіслати».",
        reply_markup=kb
    )

def _collect_media_summary_and_payloads(msgs):
    """
    Принцип:
      - Собрать все media items (photo, video, animation) для отправки через sendMediaGroup (если >=2) или sendPhoto/sendVideo (если 1).
      - Документы собираются в список doc_msgs, будут отправляться по одному.
      - Тексты: если присутствует медиа, объединить тексты и использовать как caption (на первом элементе),
        если caption слишком длинный или нет медиа — отправить как отдельное сообщение.
    Возвращает: media_items(list), doc_msgs(list), leftover_texts(list)
    """
    media_items = []  # для sendMediaGroup: каждый элемент dict с type, media, caption (caption только на первом)
    doc_msgs = []
    leftover_texts = []

    # Собираем тексты/капы отдельно, чтобы потом объединить
    captions_for_media = []
    other_texts = []

    for m in msgs:
        # text in message (standalone text)
        txt = m.get('text') or m.get('caption') or ''
        if 'photo' in m:
            # выбираем последний размер фото
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
            # Документы будем отправлять отдельно. У документа может быть caption/text.
            doc_msgs.append({"file_id": m['document'].get('file_id'), "file_name": m['document'].get('file_name'), "text": txt})
            if txt:
                # считам текст использованным как подпись документа — не добавляем в other_texts
                pass
        else:
            # остальные виды (sticker, voice, contact, location, plain text)
            if txt:
                other_texts.append(txt)
            else:
                # если нет текста и нет известных файлов — добавляем краткое описание
                t = []
                for k in ['sticker', 'voice', 'contact', 'location', 'audio']:
                    if k in m:
                        t.append(k)
                if t:
                    other_texts.append(f"[contains: {','.join(t)}]")
    # Сформируем combined caption для media (если есть)
    combined_caption = None
    if media_items:
        if captions_for_media:
            # объединяем, разделяем двойным переносом, но нужно учитывать ограничение caption (1024 символа)
            joined = "\n\n".join(captions_for_media)
            if len(joined) > 1000:
                joined = joined[:997] + "..."
            combined_caption = joined
        # При необходимости установить caption в первый элемент media_items
        for idx, mi in enumerate(media_items):
            if idx == 0 and combined_caption:
                mi['caption'] = combined_caption
            else:
                mi['caption'] = ""
    # leftover_texts — тексты, не использованные как caption (other_texts)
    leftover_texts = other_texts
    return media_items, doc_msgs, leftover_texts

def send_compiled_media_to_admin(chat_id):
    # Берём копию под блокировкой, затем обрабатываем её
    with GLOBAL_LOCK:
        msgs = list(pending_media.get(chat_id, []))
    if not msgs:
        send_message(chat_id, "Немає медіа для надсилання.")
        return
    # Определяем категорию и сохраняем событие при необходимости
    m_category = None
    with GLOBAL_LOCK:
        if pending_mode.get(chat_id) == "event":
            m_category = user_admin_category.get(chat_id, 'Без категорії')
    if m_category in ADMIN_SUBCATEGORIES:
        try:
            save_event(m_category)
        except Exception as e:
            cool_error_handler(e, "save_event in send_compiled_media_to_admin")

    # Собираем payloads
    media_items, doc_msgs, leftover_texts = _collect_media_summary_and_payloads(msgs)

    # Формируем admin_info из первого сообщения для контекста (как раньше)
    admin_info = build_admin_info(msgs[0], category=m_category)

    reply_markup = _get_reply_markup_for_admin(chat_id)
    # --- Отправляем админ-инфо сначала ---
    send_message(ADMIN_ID, admin_info, reply_markup=reply_markup, parse_mode="HTML")

    # --- Отправляем media (photo/video/animation) ---
    try:
        if media_items:
            # Если больше одного — используем sendMediaGroup
            if len(media_items) > 1:
                # Подготовим список объектов InputMedia для sendMediaGroup
                sendmedia = []
                for mi in media_items:
                    obj = {"type": mi["type"], "media": mi["media"]}
                    # caption только для первого элемента (Telegram разрешает caption для каждого, но обычно отображается для первого)
                    if mi.get("caption"):
                        obj["caption"] = mi["caption"]
                        obj["parse_mode"] = "HTML"
                    sendmedia.append(obj)
                url = f"https://api.telegram.org/bot{TOKEN}/sendMediaGroup"
                payload = {"chat_id": ADMIN_ID, "media": json.dumps(sendmedia)}
                try:
                    r = requests.post(url, data=payload, timeout=10)
                    if not r.ok:
                        MainProtokol(f"sendMediaGroup failed: {r.status_code} {r.text}", "MediaGroupFail")
                except Exception as e:
                    MainProtokol(f"sendMediaGroup error: {str(e)}", "MediaGroupFail")
            else:
                # Один элемент — отправляем через соответствующий метод, чтобы корректно передать caption
                mi = media_items[0]
                if mi["type"] == "photo":
                    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
                    payload = {"chat_id": ADMIN_ID, "photo": mi["media"]}
                    if mi.get("caption"):
                        payload["caption"] = mi["caption"]
                        payload["parse_mode"] = "HTML"
                    try:
                        r = requests.post(url, data=payload, timeout=10)
                        if not r.ok:
                            MainProtokol(f"sendPhoto failed: {r.status_code} {r.text}", "PhotoFail")
                    except Exception as e:
                        MainProtokol(f"sendPhoto error: {str(e)}", "PhotoFail")
                elif mi["type"] == "video":
                    url = f"https://api.telegram.org/bot{TOKEN}/sendVideo"
                    payload = {"chat_id": ADMIN_ID, "video": mi["media"]}
                    if mi.get("caption"):
                        payload["caption"] = mi["caption"]
                        payload["parse_mode"] = "HTML"
                    try:
                        r = requests.post(url, data=payload, timeout=10)
                        if not r.ok:
                            MainProtokol(f"sendVideo failed: {r.status_code} {r.text}", "VideoFail")
                    except Exception as e:
                        MainProtokol(f"sendVideo error: {str(e)}", "VideoFail")
                elif mi["type"] == "animation":
                    url = f"https://api.telegram.org/bot{TOKEN}/sendAnimation"
                    payload = {"chat_id": ADMIN_ID, "animation": mi["media"]}
                    if mi.get("caption"):
                        payload["caption"] = mi["caption"]
                        payload["parse_mode"] = "HTML"
                    try:
                        r = requests.post(url, data=payload, timeout=10)
                        if not r.ok:
                            MainProtokol(f"sendAnimation failed: {r.status_code} {r.text}", "AnimationFail")
                    except Exception as e:
                        MainProtokol(f"sendAnimation error: {str(e)}", "AnimationFail")
    except Exception as e:
        cool_error_handler(e, "send_compiled_media_to_admin: media send")

    # --- Отправляем документы по одному ---
    for d in doc_msgs:
        try:
            payload = {
                "chat_id": ADMIN_ID,
                "document": d["file_id"]
            }
            if d.get("text"):
                payload["caption"] = d["text"] if len(d["text"]) <= 1000 else d["text"][:997] + "..."
                payload["parse_mode"] = "HTML"
            r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendDocument", data=payload, timeout=10)
            if not r.ok:
                MainProtokol(f"sendDocument failed: {r.status_code} {r.text}", "DocumentFail")
        except Exception as e:
            MainProtokol(f"sendDocument error: {str(e)}", "DocumentFail")

    # --- Отправляем оставшиеся тексты (если есть) ---
    if leftover_texts:
        try:
            combined = "\n\n".join(leftover_texts)
            # Разрешим большой текст, но при необходимости можно разбить на части
            send_message(ADMIN_ID, f"<b>Текст від користувача:</b>\n<pre>{escape(combined)}</pre>", parse_mode="HTML")
        except Exception as e:
            MainProtokol(f"text send error: {str(e)}", "TextFail")

    # Очищаем pending
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
    global pending_media, pending_mode
    try:
        data_raw = request.get_data(as_text=True)
        update = json.loads(data_raw)

        if 'callback_query' in update:
            call = update['callback_query']
            chat_id = call['from']['id']
            data = call['data']

            if data.startswith("reply_") and chat_id == ADMIN_ID:
                try:
                    user_id = int(data.split("_")[1])
                    with GLOBAL_LOCK:
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
                with GLOBAL_LOCK:
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

            # ---- ПАКЕТНЫЙ РЕЖИМ СОБОРА МЕДИА/ТЕКСТА ----
            with GLOBAL_LOCK:
                in_pending = chat_id in pending_mode
            if in_pending:
                # Обрабатываем команды подтверждения/отмены
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
                    # Подтверждаем приём отдельного файла/сообщения
                    send_message(chat_id, "Додано до пакету. Продовжуйте надсилати або натисніть ✅ Надіслати.", reply_markup={
                        "keyboard": [[{"text": "✅ Надіслати"}, {"text": "❌ Скасувати"}]],
                        "resize_keyboard": True,
                        "one_time_keyboard": False
                    })
                    return "ok", 200

            # Ответ администратора пользователю
            with GLOBAL_LOCK:
                waiting_user = waiting_for_admin.get(ADMIN_ID)
            if from_id == ADMIN_ID and waiting_user:
                with GLOBAL_LOCK:
                    user_id = waiting_for_admin.pop(ADMIN_ID, None)
                if user_id:
                    send_message(user_id, f"💬 Відповідь адміністратора:\n{text}")
                    send_message(ADMIN_ID, f"✅ Відповідь надіслано користувачу {user_id}")
                return "ok", 200

            # Главное меню
            if text == '/start':
                send_chat_action(chat_id, 'typing')
                time.sleep(0.25)
                user = message.get('from', {})
                welcome = build_welcome_message(user)
                send_message(
                    chat_id,
                    welcome,
                    reply_markup=get_reply_buttons(),
                    parse_mode='HTML'
                )
            elif text in MAIN_MENU:
                if text == "✨ Головне":
                    send_message(chat_id, "✨ Ви в головному меню.", reply_markup=get_reply_buttons())
                elif text == "📢 Про нас":
                    send_message(
                        chat_id,
                        "Ми створюємо телеграм-ботів та сервіси для вашого бізнесу і життя.\nДізнатись більше: наші канали",
                        reply_markup=get_reply_buttons()
                    )
                elif text == "🕰️ Графік роботи":
                    send_message(
                        chat_id,
                        "Ми працюємо цілодобово. Звертайтесь у будь-який час.",
                        reply_markup=get_reply_buttons()
                    )
                elif text == "📝 Повідомити про подію":
                    desc = (
                        "Оберіть тип події, яку хочете повідомити:\n\n"
                        "🏗️ Техногенні: Події, пов'язані з діяльністю людини (аварії, катастрофи на виробництві/транспорті).\n\n"
                        "🌪️ Природні: Події, спричинені силами природи (землетруси, повені, буревії).\n\n"
                        "👥 Соціальні: Події, пов'язані з суспільними конфліктами або масовими заворушеннями.\n\n"
                        "⚔️ Воєнні: Події, пов'язані з військовими діями або конфліктами.\n\n"
                        "🕵️‍♂️ Розшук: Дії, спрямовані на пошук зниклих осіб або злочинців.\n\n"
                        "📦 Інші події: Загальна категорія для всього, що не вписується в попередні визначення."
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
                if chat_id not in pending_mode:
                    send_message(
                        chat_id,
                        "Щоб повідомити адміна або надіслати рекламу, скористайтесь відповідними кнопками в меню.",
                        reply_markup=get_reply_buttons()
                    )
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
