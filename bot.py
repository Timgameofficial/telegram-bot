# contents: визуальные улучшения UI — премиальный вид меню, карточки и статус typing
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

# Библиотека для роботи з різними БД (Postgres/SQLite)
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

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
    # Двухколоночная аккуратная раскладка — выглядит "дороже"
    return {
        "keyboard": [
            [{"text": "✨ Головне"}, {"text": "📣 Реклама"}],
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
            print(f"[DEBUG] Using DB URL: {db_url}")
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
            print(f"[DEBUG] events table row count after init: {cnt}")
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
            print(f"[DEBUG] Saved event (sqlite). Total events now: {cnt}")
        else:
            insert_sql = "INSERT INTO events (category, dt) VALUES (:cat, :dt)"
            with engine.begin() as conn:
                conn.execute(text(insert_sql), {"cat": category, "dt": now})
                try:
                    r = conn.execute(text("SELECT COUNT(*) FROM events"))
                    cnt = r.scalar() or 0
                except Exception:
                    cnt = None
            print(f"[DEBUG] Saved event (sql). Total events now: {cnt}")
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

# Инициализация БД при старте
init_db()

# ====== Конфигурация ======
TOKEN = os.getenv("API_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEBHOOK_URL = f"https://telegram-bot-1-g3bw.onrender.com/webhook/{TOKEN}"

# ====== Установка webhook ======
def set_webhook():
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/setWebhook",
            params={"url": WEBHOOK_URL}
        )
        if r.ok:
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

def forward_ad_to_admin(message):
    """
    Преміально оформленная карточка заявки на рекламу (аккуратно, без лишних деталей).
    """
    try:
        if not ADMIN_ID or ADMIN_ID == 0:
            send_message(message['chat']['id'], "⚠️ Адміністратор не налаштований.")
            return

        user = message['from']
        user_chat_id = message['chat']['id']
        first = user.get('first_name', '')
        last = user.get('last_name', '')
        username = user.get('username')
        user_id = user.get('id')

        text = message.get('text') or message.get('caption') or ''
        msg_id = message.get('message_id')

        # Аккуратный премиальный дизайн карточки (без подробных заявлений о передаче данных)
        name_display = (first + (' ' + last if last else '')).strip() or "Без імені"
        profile_link = f"tg://user?id={user_id}"
        username_line = f"@{escape(username)}" if username else None

        premium_card_lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "<b>📣 Рекламна заявка</b>",
            "",
            f"<b>Відправник:</b> <a href=\"{profile_link}\">{escape(name_display)}</a>",
        ]
        if username_line:
            premium_card_lines.append(f"<b>Профіль:</b> {escape(username_line)}")
        premium_card_lines += [
            "",
            "<b>Контент заявки:</b>",
            "<pre>{}</pre>".format(escape(text)) if text else "<i>Надано мультимедіа або файл</i>",
            "",
            "<i>Заявка відформатована для зручного перегляду.</i>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ]
        premium_card = "\n".join(premium_card_lines)

        reply_markup = _get_reply_markup_for_admin(user_chat_id)

        # Показываем админу действие typing перед отправкой (чтобы выглядело "живее")
        if ADMIN_ID and ADMIN_ID != 0:
            send_chat_action(ADMIN_ID, 'typing')
            time.sleep(0.25)

        # Пытаемся переслать оригинал (если есть) и отправить карточку
        try:
            fwd_url = f'https://api.telegram.org/bot{TOKEN}/forwardMessage'
            fwd_payload = {'chat_id': ADMIN_ID, 'from_chat_id': user_chat_id, 'message_id': msg_id}
            # не критично если forward не сработает — всё равно отправим карточку
            requests.post(fwd_url, data=fwd_payload, timeout=5)
        except Exception:
            # игнорируем ошибки пересылки, дальше отправим карточку
            pass

        # Отправляем красиво оформленную карточку админу
        send_message(ADMIN_ID, premium_card, reply_markup=reply_markup, parse_mode='HTML')
        send_message(user_chat_id, "✅ Дякуємо! Ваша заявка надіслана.")
        return

    except Exception as e:
        cool_error_handler(e, context="forward_ad_to_admin: unhandled")
        MainProtokol(str(e), "ForwardAdUnhandledException")
        try:
            send_message(message['chat']['id'], "⚠️ Виникла помилка при надсиланні рекламного запиту. Спробуйте ще раз.")
        except Exception as err:
            cool_error_handler(err, context="forward_ad_to_admin: notify user")

waiting_for_admin = {}

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
    # рамка премиального вида
    return "<pre>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" + content + "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━</pre>"

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
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

            # Ответ администратора пользователю
            if from_id == ADMIN_ID and ADMIN_ID in waiting_for_admin:
                user_id = waiting_for_admin.pop(ADMIN_ID)
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
                    waiting_for_ad_message.add(chat_id)
                    send_message(
                        chat_id,
                        "📣 Ви обрали розділ «Реклама». Надішліть текст та/або медіа — ми відформатуємо заявку у стильному вигляді та передамо адміністратору.",
                        reply_markup=get_reply_buttons()
                    )
            elif text in ADMIN_SUBCATEGORIES:
                user_admin_category[chat_id] = text
                waiting_for_admin_message.add(chat_id)
                send_message(
                    chat_id,
                    f"Будь ласка, опишіть деталі події «{text}» (можна прикріпити фото чи файл):"
                )
            else:
                if chat_id in waiting_for_ad_message:
                    forward_ad_to_admin(message)
                    waiting_for_ad_message.remove(chat_id)
                    send_message(
                        chat_id,
                        "Ваша рекламна заявка успішно надіслана. Дякуємо!",
                        reply_markup=get_reply_buttons()
                    )
                elif chat_id in waiting_for_admin_message:
                    forward_user_message_to_admin(message)
                    waiting_for_admin_message.remove(chat_id)
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
