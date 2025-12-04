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
import sqlite3
from pathlib import Path

# ====== Логування ======
def MainProtokol(s, ts='Запис'):
    dt = time.strftime('%d.%m.%Y %H:%M:') + '00'
    try:
        with open('log.txt', 'a', encoding='utf-8') as f:
            f.write(f"{dt};{ts};{s}\n")
    except Exception as e:
        print("Помилка запису в лог:", e)

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
                            "text": f"⚠️ Критична помилка!\nТип: {exc_type}\nКонтекст: {context}\n\n{str(exc)}",
                            "disable_web_page_preview": True
                        },
                        timeout=5
                    )
                except Exception as telegram_err:
                    print("Не удалось отправить уведомление в Telegram:", telegram_err)
        except Exception as env_err:
            print("Ошибка при подготовке уведомления в Telegram:", env_err)

# ====== Відладка часу в консоль (фоновий потік, кожні 5 хвилин) ======
def time_debugger():
    while True:
        print("[DEBUG]", time.strftime('%Y-%m-%d %H:%M:%S'))
        time.sleep(300)

# ====== Головне меню (reply-кнопки) ======
MAIN_MENU = [
    "📢 Про нас",
    "🕰️ Графік роботи",
    "📝 Повідомити про подію",
    "📊 Статистика подій"
]

def get_reply_buttons():
    return {
        "keyboard": [
            [{"text": "📢 Про нас"}],
            [{"text": "🕰️ Графік роботи"}],
            [{"text": "📝 Повідомити про подію"}],
            [{"text": "📊 Статистика подій"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

# ====== Категорії подій (оновлено) ======
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

# ====== Хранилище для статусу вибору категорії користувача ======
waiting_for_admin_message = set()
user_admin_category = {}

# ====== Хранилище подій для статистики (переключено на SQLite) ======
# Файл БД по умолчанию — events.db, можно переопределить через ENV EVENTS_DB_FILE
DB_FILE = os.getenv("EVENTS_DB_FILE", "events.db")

def init_db():
    try:
        # Создаём файл/директорию если нужно
        db_path = Path(DB_FILE)
        if not db_path.parent.exists():
            db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    dt TEXT NOT NULL
                );
            """)
            conn.commit()
    except Exception as e:
        cool_error_handler(e, "init_db")

def save_event(category):
    try:
        now_iso = datetime.datetime.now().isoformat()
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("INSERT INTO events (category, dt) VALUES (?, ?)", (category, now_iso))
            conn.commit()
    except Exception as e:
        cool_error_handler(e, "save_event")

def get_stats():
    res = {cat: {'week': 0, 'month': 0} for cat in ADMIN_SUBCATEGORIES}
    now = datetime.datetime.now()
    week_threshold = (now - datetime.timedelta(days=7)).isoformat()
    month_threshold = (now - datetime.timedelta(days=30)).isoformat()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.cursor()
            for cat in ADMIN_SUBCATEGORIES:
                cur.execute("SELECT COUNT(*) FROM events WHERE category = ? AND dt >= ?", (cat, week_threshold))
                res[cat]['week'] = cur.fetchone()[0] or 0
                cur.execute("SELECT COUNT(*) FROM events WHERE category = ? AND dt >= ?", (cat, month_threshold))
                res[cat]['month'] = cur.fetchone()[0] or 0
        return res
    except Exception as e:
        cool_error_handler(e, "get_stats")
        return None

def clear_stats_if_month_passed():
    now = datetime.datetime.now()
    month_threshold = (now - datetime.timedelta(days=30)).isoformat()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("DELETE FROM events WHERE dt < ?", (month_threshold,))
            conn.commit()
    except Exception as e:
        cool_error_handler(e, "clear_stats_if_month_passed")

def stats_autoclear_daemon():
    while True:
        try:
            clear_stats_if_month_passed()
        except Exception as e:
            cool_error_handler(e, "stats_autoclear_daemon")
        time.sleep(3600)  # кожні 60 хвилин

# Инициализация БД при старте
init_db()

# ====== Конфігурація ======
TOKEN = os.getenv("API_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEBHOOK_URL = f"https://telegram-bot-1-g3bw.onrender.com/webhook/{TOKEN}"

# ====== Встановлення webhook ======
def set_webhook():
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/setWebhook",
            params={"url": WEBHOOK_URL}
        )
        if r.ok:
            print("Webhook успішно встановлено!")
        else:
            print("Помилка при встановленні webhook:", r.text)
    except Exception as e:
        cool_error_handler(e, context="set_webhook")

set_webhook()

# ====== Надсилання повідомлень (добавлен parse_mode) ======
def send_message(chat_id, text, reply_markup=None, parse_mode=None):
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

def forward_user_message_to_admin(message):
    try:
        if not ADMIN_ID or ADMIN_ID == 0:
            send_message(message['chat']['id'], "⚠️ Адміністратор не налаштований.")
            return

        user_chat_id = message['chat']['id']
        user_first = message['from'].get('first_name', 'Без імені')
        msg_id = message.get('message_id')
        text = message.get('text') or message.get('caption') or ''
        category = user_admin_category.get(user_chat_id, 'Без категорії')
        admin_info = f"📩 Категорія: {category}\nВід: {user_first}\nID: {user_chat_id}"
        if text:
            admin_info += f"\n\n{text}"

        reply_markup = _get_reply_markup_for_admin(user_chat_id)
        if category in ADMIN_SUBCATEGORIES:
            save_event(category)

        try:
            fwd_url = f'https://api.telegram.org/bot{TOKEN}/forwardMessage'
            fwd_payload = {'chat_id': ADMIN_ID, 'from_chat_id': user_chat_id, 'message_id': msg_id}
            fwd_resp = requests.post(fwd_url, data=fwd_payload)
            if fwd_resp.ok:
                send_message(ADMIN_ID, admin_info, reply_markup=reply_markup)
                send_message(user_chat_id, "✅ Дякуємо! Ваше повідомлення надіслано адміністратору.")
                return
            else:
                MainProtokol(f"forwardMessage failed: {fwd_resp.text}", "ForwardFail")
        except Exception as e:
            cool_error_handler(e, context="forward_user_message_to_admin: forwardMessage")
            MainProtokol(str(e), "ForwardException")

        media_sent = False
        try:
            media_types = [
                ('photo', 'sendPhoto', 'photo'),
                ('video', 'sendVideo', 'video'),
                ('document', 'sendDocument', 'document'),
                ('audio', 'sendAudio', 'audio'),
                ('voice', 'sendVoice', 'voice'),
                ('animation', 'sendAnimation', 'animation')
            ]
            for key, endpoint, payload_key in media_types:
                if key in message:
                    file_id = message[key][-1]['file_id'] if key == 'photo' else message[key]['file_id']
                    url = f'https://api.telegram.org/bot{TOKEN}/{endpoint}'
                    payload = {
                        'chat_id': ADMIN_ID,
                        payload_key: file_id,
                        'caption': admin_info,
                        'reply_markup': json.dumps(reply_markup)
                    }
                    resp = requests.post(url, data=payload)
                    media_sent = resp.ok
                    if not media_sent:
                        MainProtokol(f'{endpoint} failed: {resp.text}', "MediaSendFail")
                    break
            else:
                send_message(ADMIN_ID, admin_info, reply_markup=reply_markup)
                send_message(user_chat_id, "✅ Дякуємо! Ваше повідомлення надіслано адміністратору.")
                return
        except Exception as e:
            cool_error_handler(e, context="forward_user_message_to_admin: sendMedia")
            MainProtokol(str(e), "SendMediaException")

        if media_sent:
            send_message(user_chat_id, "✅ Дякуємо! Ваше повідомлення надіслано адміністратору.")
        else:
            send_message(ADMIN_ID, admin_info, reply_markup=reply_markup)
            send_message(user_chat_id, "⚠️ Не вдалося переслати медіа. Адміністратору надіслано текстове повідомлення.")
    except Exception as e:
        cool_error_handler(e, context="forward_user_message_to_admin: unhandled")
        MainProtokol(str(e), "ForwardUnhandledException")
        try:
            send_message(message['chat']['id'], "⚠️ Виникла помилка при надсиланні. Спробуйте ще раз.")
        except Exception as err:
            cool_error_handler(err, context="forward_user_message_to_admin: notify user")

waiting_for_admin = {}

app = Flask(__name__)

@app.errorhandler(Exception)
def flask_global_error_handler(e):
    cool_error_handler(e, context="Flask global error handler")
    return "Внутрішня помилка сервера. Адміністратору надіслано повідомлення.", 500

def format_stats_message(stats: dict) -> str:
    """
    Формирует аккуратную таблицу в моноширинном формате, оборачивает в HTML <pre>.
    Вернёт строку готовую для отправки с parse_mode='HTML'.
    """
    # Подготовим заголовок и строки, выравнивание по колонкам
    # ширина колонки для названия категории определяется по самым длинным строкам
    cat_names = [c for c in ADMIN_SUBCATEGORIES]
    max_cat_len = max(len(escape(c)) for c in cat_names) + 1
    col1 = "Категорія".ljust(max_cat_len)
    header = f"{col1}  {'7 дн':>6}  {'30 дн':>
