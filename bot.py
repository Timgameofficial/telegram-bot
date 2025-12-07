# contents: расширение информации, отправляемой админу — больше полей и аккуратное HTML-оформление
import os
import time
import json
import requests
import threading
import traceback
import datetime
import textwrap
from flask import Flask, request
from html import escape
from pathlib import Path

# Библиотека для работы с разными БД (Postgres/SQLite)
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ArgumentError

# ====== Логирование ======
def MainProtokol(s, ts='Запис'):
    dt = time.strftime('%d.%m.%Y %H:%M:') + '00'
    try:
        with open('log. txt', 'a', encoding='utf-8') as f:
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
                    requests.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        data={
                            "chat_id": admin_id,
                            "text": f"⚠️ Критичная ошибка!\nТип: {exc_type}\nКонтекст: {context}\n\n{str(exc)}",
                            "disable_web_page_preview": True
                        },
                        timeout=5
                    )
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

# ====== Настройки БД ======
DATABASE_URL = os.getenv("DATABASE_URL", ""). strip()
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
                fallback_sqlite = os.path.join(os. path.dirname(os.path. abspath(__file__)), "events.db")
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
            conn. execute(text(create_sql))
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
                mo = conn.execute(q_month, {"month": month_ts}). all()
            else:
                q_week = text("SELECT category, COUNT(*) as cnt FROM events WHERE dt >= :week GROUP BY category")
                q_month = text("SELECT category, COUNT(*) as cnt FROM events WHERE dt >= :month GROUP BY category")
                wk = conn.execute(q_week, {"week": week_threshold}). all()
                mo = conn. execute(q_month, {"month": month_threshold}).all()
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
ADMIN_ID = int(os. getenv("ADMIN_ID", "0"))
WEBHOOK_URL = f"https://telegram-bot-1-g3bw.onrender.com/webhook/{TOKEN}"

# ====== Установка webhook ======
def set_webhook():
    if not TOKEN:
        print("[WARN] TOKEN is not set, webhook not initialized.")
        return
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/setWebhook",
            params={"url": WEBHOOK_URL}
        )
        if r. ok:
            print("Webhook успешно установлен!")
        else:
            print("Ошибка при установке webhook:", r.text)
    except Exception as e:
        cool_error_handler(e, context="set_webhook")

set_webhook()

# ====== UI helpers ======
def send_chat_action(chat_id, action='typing'):
    if not TOKEN:
        return
    try:
        requests.post(f'https://api.telegram.org/bot{TOKEN}/sendChatAction', data={'chat_id': chat_id, 'action': action}, timeout=3)
    except Exception:
        pass

# ====== Отправка сообщений (parse_mode поддерживается) ======
def send_message(chat_id, text, reply_markup=None, parse_mode=None):
    if not TOKEN:
        print("[WARN] Попытка отправки сообщения без TOKEN")
        return
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
        resp = requests.post(url, data=payload)
        if not resp.ok:
            MainProtokol(resp.text, 'Помилка надсилання')
        return resp
    except Exception as e:
        cool_error_handler(e, context="send_message")
        MainProtokol(str(e), 'Помилка мережі')

def _get_reply_markup_for_admin(user_id: int):
    return {
        "inline_keyboard": [
            [{"text": "✉️ Відповісти", "callback_data": f"reply_{user_id}"}]
        ]
    }

# ====== Новый helper: строим расширённую карточку для админа ======
def build_admin_info(message: dict, category: str = None) -> str:
    try:
        user = message. get('from', {})
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
        entities_summary = ", ".join(e.get('type') for e in entities if e.get('type')) or "-"

        media_keys = []
        media_candidates = ['photo', 'video', 'document', 'audio', 'voice', 'animation', 'sticker', 'contact', 'location']
        for k in media_candidates:
            if k in message:
                media_keys.append(k)
        media_summary = ", ".join(media_keys) if media_keys else "-"

        reply_info = "-"
        if 'reply_to_message' in message and isinstance(message['reply_to_message'], dict):
            r = message['reply_to_message']
            rfrom = r.get('from', {})
            rname = (rfrom.get('first_name','') or '') + ((' ' + rfrom.get('last_name')) if rfrom.get('last_name') else '')
            reply_info = f"id:{r.get('message_id','-')} from:{escape(rname or '-')}"

        parts = [
            "<pre>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</pre>",
            "<b>📩 Нове повідомлення від користувача</b>",
            ""
        ]
        if category:
            parts.append(f"<b>Категорія:</b> {escape(category)}")
        display_name = (first + (" " + last if last else "")). strip() or "Без імені"
        parts += [
            f"<b>Ім'я:</b> {escape(display_name)}",
            f"<b>ID:</b> {escape(str(user_id)) if user_id is not None else '-'}",
        ]
        if username:
            parts. append(f"<b>Username:</b> @{escape(username)}")
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
            "<i>Повідомлення відформатовано для зручного перегляду. </i>",
            "<pre>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</pre>"
        ]
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
        "Надсилайте усі потрібні фото, відео, документи та/або текст (кілька повідомлень).  Як закінчите – натисніть «✅ Надіслати».",
        reply_markup=kb
    )

def send_compiled_media_to_admin(chat_id):
    msgs = pending_media.get(chat_id, [])
    if not msgs:
        send_message(chat_id, "Немає медіа для надсилання.")
        return
    reply_markup = _get_reply_markup_for_admin(chat_id)
    media_items = []
    doc_msgs = []
    text_msgs = []
    for msg in msgs:
        if 'photo' in msg:
            file_id = msg['photo'][-1]['file_id']
            media_items.append({
                "type": "photo", "media": file_id, "caption": "", "parse_mode": "HTML"
            })
        elif 'video' in msg:
            file_id = msg['video']['file_id']
            media_items.append({
                "type": "video", "media": file_id, "caption": "", "parse_mode": "HTML"
            })
        elif 'document' in msg:
            doc_msgs.append(msg)
        elif 'text' in msg and msg['text']. strip():
            text_msgs.append(msg['text'])
    
    m_category = None
    if pending_mode. get(chat_id) == "event":
        m_category = user_admin_category.get(chat_id, 'Без категорії')
        if m_category in ADMIN_SUBCATEGORIES:
            save_event(m_category)
    
    admin_info = build_admin_info(msgs[0], category=m_category)
    
    # ===== ОТПРАВЛЯЕМ ИНФОРМАЦИЮ ПЕРВОЙ =====
    send_message(ADMIN_ID, admin_info, reply_markup=reply_markup, parse_mode="HTML")
    
    # ===== ПОТОМ МЕДИАФАЙЛЫ =====
    if media_items:
        # Убираем caption из медиагруппы (информация уже отправлена выше)
        url = f"https://api.telegram.org/bot{TOKEN}/sendMediaGroup"
        payload = {
            "chat_id": ADMIN_ID,
            "media": json.dumps(media_items)
        }
        try:
            requests.post(url, data=payload)
        except Exception as e:
            MainProtokol(f"sendMediaGroup error: {str(e)}", "MediaGroupFail")
    
    # Документы отправляем по одному
    for dmsg in doc_msgs:
        file_id = dmsg['document']['file_id']
        filename = dmsg. get('document', {}).get('file_name', 'документ')
        payload = {
            "chat_id": ADMIN_ID,
            "document": file_id,
            "caption": f"📎 {escape(filename)}"  # Только имя файла в подписи
        }
        try:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendDocument", data=payload)
        except Exception as e:
            MainProtokol(f"sendDocument error: {str(e)}", "DocumentFail")
    
    # Текстовые сообщения отправляем отдельно (если нет медиа)
    if text_msgs and not media_items and not doc_msgs:
        for txt in text_msgs:
            send_message(ADMIN_ID, f"<b>Текст від користувача:</b>\n<pre>{escape(txt)}</pre>", parse_mode="HTML")
    
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
        week = stats[cat]['week']
        month = stats[cat]['month']
        lines.append(f"{name. ljust(max_cat_len)}  {str(week):>6}  {str(month):>6}")
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

            if data. startswith("reply_") and chat_id == ADMIN_ID:
                try:
                    user_id = int(data.split("_")[1])
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
                    "Наш бот приймає повідомлення 24/7.  Ми відповідаємо якнайшвидше."
                )
            elif data == "write_admin":
                waiting_for_admin_message. add(chat_id)
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
            if chat_id in pending_mode:
                if text == "✅ Надіслати":
                    send_compiled_media_to_admin(chat_id)
                    send_message(chat_id, "✅ Ваші дані відправлено.  Дякуємо!", reply_markup=get_reply_buttons())
                    return "ok", 200
                elif text == "❌ Скасувати":
                    pending_media.pop(chat_id, None)
                    pending_mode. pop(chat_id, None)
                    send_message(chat_id, "❌ Скасовано.", reply_markup=get_reply_buttons())
                    return "ok", 200
                else:
                    pending_media. setdefault(chat_id, []).append(message)
                    return "ok", 200

            # Ответ администратора пользователю
            if from_id == ADMIN_ID and ADMIN_ID in waiting_for_admin:
                user_id = waiting_for_admin. pop(ADMIN_ID)
                send_message(user_id, f"💬 Відповідь адміністратора:\n{text}")
                send_message(ADMIN_ID, f"✅ Відповідь надіслано користувачу {user_id}")
                return "ok", 200

            # Главное меню
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
                        "Ми створюємо телеграм-ботів та сервіси для вашого бізнесу і життя.\nДізнатись більше: наші канали"
                    )
                elif text == "🕰️ Графік роботи":
                    send_message(
                        chat_id,
                        "Ми працюємо цілодобово. Звертайтесь у будь-який час."
                    )
                elif text == "📝 Повідомити про подію":
                    desc = (
                        "Оберіть тип події, яку хочете повідомити:\n\n"
                        "🏗️ Техногенні: Події, пов'язані з діяльністю людини (аварії, катастрофи на виробництві/транспорті)\n\n"
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
                    pending_mode[chat_id] = "ad"
                    pending_media[chat_id] = []
                    send_media_collection_keyboard(chat_id)
            elif text in ADMIN_SUBCATEGORIES:
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
