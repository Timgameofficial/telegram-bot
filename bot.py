import os
import time
import json
import requests
import threading
import traceback
import datetime
from flask import Flask, request
from html import escape
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ArgumentError

# ======================= ПРЕМІУМ ЛОГУВАННЯ =======================
def MainProtokol(s, ts='Запис'):
    dt = time.strftime('%d.%m.%Y %H:%M:') + '00'
    try:
        with open('log.txt', 'a', encoding='utf-8') as f:
            f.write(f"{dt};{ts};{s}\n")
    except Exception as e:
        print("Помилка при записі логу:", e)

def cool_error_handler(exc, context="", send_to_telegram=False):
    exc_type = type(exc).__name__
    tb_str = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    readable_msg = (
        "\n" + "═" * 40 + "\n"
        f"[ПОМИЛКА] {exc_type}\n"
        f"Контекст: {context}\n"
        f"Час: {ts}\n"
        "Traceback:\n"
        f"{tb_str}"
        + "═" * 40 + "\n"
    )
    try:
        with open('critical_errors.log', 'a', encoding='utf-8') as f:
            f.write(readable_msg)
    except Exception as write_err:
        print("Не вдалося записати в 'critical_errors.log':", write_err)
    try:
        MainProtokol(f"{exc_type}: {str(exc)}", ts='ERROR')
    except Exception as log_err:
        print("MainProtokol повернув помилку:", log_err)
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
                    print("Не вдалося надіслати повідомлення в Telegram:", telegram_err)
        except Exception as env_err:
            print("Помилка при підготовці повідомлення в Telegram:", env_err)

def time_debugger():
    while True:
        print("[PREMIUM DEBUG]", time.strftime('%Y-%m-%d %H:%M:%S'))
        time.sleep(300)

# ======================= ПРЕМІАЛЬНЕ МЕНЮ І ВИД РОБОТИ ========================
MAIN_MENU = [
    "💎 Головне",
    "📢 Про нас",
    "🕰️ Графік роботи",
    "📝 Повідомити про подію",
    "📊 Статистика подій",
    "📣 Реклама",
    "💼 Вид роботи"
]

WORK_TYPES = [
    "🕹️ Збір інформації",
    "⏳ Очікує обробки",
    "✔️ Оброблено",
    "🔒 Закрито"
]

user_work_type = {}

def get_reply_buttons():
    return {
        "keyboard": [
            [{"text": "📣 Реклама"}],
            [{"text": "💼 Вид роботи"}],
            [{"text": "📢 Про нас"}, {"text": "🕰️ Графік роботи"}],
            [{"text": "📝 Повідомити про подію"}, {"text": "📊 Статистика подій"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

def get_work_type_buttons():
    return {
        "keyboard": [[{"text": t}] for t in WORK_TYPES],
        "resize_keyboard": True,
        "one_time_keyboard": True
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
        "keyboard": [[{"text": f"{cat}"}] for cat in ADMIN_SUBCATEGORIES],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }

waiting_for_admin_message = set()
user_admin_category = {}
waiting_for_ad_message = set()

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
                raise ValueError("DATABASE_URL порожній")
            if db_url.startswith("sqlite:///"):
                _engine = create_engine(db_url, connect_args={"check_same_thread": False}, future=True)
                print(f"[PREMIUM DEBUG] Використовується SQLite: {db_url}")
            else:
                if '://' not in db_url:
                    raise ArgumentError(f"Невалідний DB URL: {db_url}")
                _engine = create_engine(db_url, future=True)
                print(f"[PREMIUM DEBUG] Використовується DB URL: {db_url}")
        except Exception as e:
            cool_error_handler(e, "get_engine")
            try:
                fallback_sqlite = os.path.join(os.path.dirname(os.path.abspath(__file__)), "events.db")
                fallback_url = f"sqlite:///{fallback_sqlite}"
                _engine = create_engine(fallback_url, connect_args={"check_same_thread": False}, future=True)
                print(f"[PREMIUM WARN] Перехід на SQLite через помилки.")
            except Exception as e2:
                cool_error_handler(e2, "get_engine (fallback sqlite)")
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
            print(f"[PREMIUM DEBUG] Кількість рядків у events після ініціалізації: {cnt}")
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

def stats_autoclear_daemon():
    while True:
        try:
            clear_stats_if_month_passed()
        except Exception as e:
            cool_error_handler(e, "stats_autoclear_daemon")
        time.sleep(3600)

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

init_db()

TOKEN = os.getenv("API_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEBHOOK_URL = f"https://telegram-bot-1-g3bw.onrender.com/webhook/{TOKEN}"

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

def send_chat_action(chat_id, action='typing'):
    if not TOKEN:
        return
    try:
        requests.post(f'https://api.telegram.org/bot{TOKEN}/sendChatAction', data={'chat_id': chat_id, 'action': action}, timeout=3)
    except Exception:
        pass

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

def send_media_group(chat_id, media_group, reply_markup=None):
    url = f'https://api.telegram.org/bot{TOKEN}/sendMediaGroup'
    payload = {
        'chat_id': chat_id,
        'media': json.dumps(media_group)
    }
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    try:
        resp = requests.post(url, data=payload)
        if not resp.ok:
            MainProtokol(resp.text, 'Помилка надсилання media group')
        return resp
    except Exception as e:
        cool_error_handler(e, context="send_media_group")
        MainProtokol(str(e), 'Помилка мережі media group')

def extract_media_groups(message):
    groups = []
    for t in ['photo', 'video']:
        items = message.get(t)
        if items and isinstance(items, list) and len(items) > 1:
            media_group = []
            caption_sent = False
            for idx, item in enumerate(items):
                file_id = item.get('file_id')
                obj = {'type': t, 'media': file_id}
                if not caption_sent and idx == 0 and ('caption' in message or 'text' in message):
                    obj['caption'] = message.get('caption', message.get('text', ''))
                    obj['parse_mode'] = 'HTML'
                    caption_sent = True
                media_group.append(obj)
            groups.append((t, media_group))
    return groups

def extract_documents(message):
    docs = []
    if "document" in message:
        doc = message["document"]
        if isinstance(doc, list):
            docs = doc
        else:
            docs.append(doc)
    return docs

def forward_documents_to_admin(message, admin_id, reply_markup=None):
    docs = extract_documents(message)
    caption_sent = False
    for doc in docs:
        payload = {
            'chat_id': admin_id,
            'document': doc.get('file_id')
        }
        if not caption_sent:
            if 'caption' in message:
                payload['caption'] = message['caption']
            caption_sent = True
        if reply_markup:
            payload['reply_markup'] = json.dumps(reply_markup)
        requests.post(f'https://api.telegram.org/bot{TOKEN}/sendDocument', data=payload)
    return bool(docs)

def forward_documents_to_user(user_id, message):
    docs = extract_documents(message)
    caption_sent = False
    for doc in docs:
        payload = {
            'chat_id': user_id,
            'document': doc.get('file_id')
        }
        if not caption_sent:
            if 'caption' in message:
                payload['caption'] = message['caption']
            caption_sent = True
        requests.post(f'https://api.telegram.org/bot{TOKEN}/sendDocument', data=payload)
    return bool(docs)

def _get_reply_markup_for_admin(user_id: int):
    return {
        "inline_keyboard": [
            [{"text": "💬 Відповісти", "callback_data": f"reply_{user_id}"}]
        ]
    }

def build_admin_info(message: dict, category: str = None) -> str:
    try:
        user = message.get('from', {})
        first = user.get('first_name', '') or ""
        last = user.get('last_name', '') or ""
        username = user.get('username')
        user_id = user.get('id')
        is_premium = user.get('is_premium', None)
        msg_id = message.get('message_id')
        msg_date = message.get('date')
        work_type = user_work_type.get(message['chat']['id'], "🕹️ Збір інформації")
        try:
            date_str = datetime.datetime.utcfromtimestamp(int(msg_date)).strftime('%Y-%m-%d %H:%M:%S UTC') if msg_date else '-'
        except Exception:
            date_str = str(msg_date or '-')
        text = message.get('text') or message.get('caption') or ''
        entities = message.get('entities') or message.get('caption_entities') or []
        entities_summary = ", ".join([ent.get('type') for ent in entities if ent.get('type')]) if entities else "-"
        media_keys = []
        media_candidates = [
            'photo', 'video', 'document', 'audio', 'voice', 'animation', 'sticker', 'contact', 'location'
        ]
        for k in media_candidates:
            if k in message:
                media_keys.append(k)
        media_summary = ", ".join(media_keys) if media_keys else "-"
        reply_info = "-"
        if 'reply_to_message' in message and isinstance(message['reply_to_message'], dict):
            r = message['reply_to_message']
            rname = (r.get('from', {}).get('first_name','') or '') + ((' ' + r.get('from', {}).get('last_name')) if r.get('from', {}).get('last_name') else '')
            reply_info = f"id:{r.get('message_id','-')} від:{escape(rname or '-')}"
        parts = [
            "<pre>════════════════════════════╗</pre>",
            "<b>💎 Нове повідомлення від користувача</b>",
            "",
        ]
        if category:
            parts.append(f"<b>Категорія:</b> {escape(category)}")
        parts.append(f"<b>Вид роботи:</b> {escape(work_type)}")
        display_name = (first + (" " + last if last else "")).strip() or "Без імені"
        parts += [
            f"<b>👤 Ім'я:</b> {escape(display_name)}",
            f"<b>🆔 ID:</b> {escape(str(user_id)) if user_id is not None else '-'}"
        ]
        if username:
            parts.append(f"<b>@Username:</b> @{escape(username)}")
        if is_premium is not None:
            parts.append(f"<b>Преміум статус:</b> {'🌟' if is_premium else '—'}")
        parts += [
            f"<b>🎟️ Message ID:</b> {escape(str(msg_id))}",
            f"<b>🗓️ Дата:</b> {escape(str(date_str))}",
            f"<b>🔠 Entities:</b> {escape(entities_summary)}",
            f"<b>↩️ Reply to:</b> {escape(reply_info)}",
            f"<b>🗄️ Медіа:</b> {escape(media_summary)}",
            "<b>✉️ Текст / Опис:</b>",
            "<pre>{}</pre>".format(escape(text)) if text else "<i>Немає тексту</i>",
            "",
            "<footer><i>Повідомлення згенеровано ексклюзивним сервісом PremiumBot</i></footer>",
            "<pre>════════════════════════════╝</pre>"
        ]
        return "\n".join(parts)
    except Exception as e:
        cool_error_handler(e, "build_admin_info")
        try:
            return f"Повідомлення від користувача. ID: {escape(str(message.get('from', {}).get('id', '-')))}"
        except Exception:
            return "Нове повідомлення."

def forward_user_message_to_admin(message):
    try:
        if not ADMIN_ID or ADMIN_ID == 0:
            send_message(message['chat']['id'], "⚠️ Адміністратор не налаштований.")
            return
        user_chat_id = message['chat']['id']
        msg_id = message.get('message_id')
        category = user_admin_category.get(user_chat_id, 'Без категорії')
        admin_info = build_admin_info(message, category=category)
        reply_markup = _get_reply_markup_for_admin(user_chat_id)
        if category in ADMIN_SUBCATEGORIES: save_event(category)
        media_groups = extract_media_groups(message)
        sent_any_album = False
        for t, mg in media_groups:
            send_media_group(ADMIN_ID, mg, reply_markup=reply_markup)
            sent_any_album = True
        docs_forwarded = forward_documents_to_admin(message, ADMIN_ID, reply_markup=reply_markup)
        if sent_any_album or docs_forwarded:
            send_message(ADMIN_ID, admin_info, reply_markup=reply_markup, parse_mode='HTML')
            send_message(user_chat_id, "✅ Дякуємо! Ваше повідомлення успішно надіслано адміністратору 💎")
            return
        try:
            fwd_url = f'https://api.telegram.org/bot{TOKEN}/forwardMessage'
            fwd_payload = {'chat_id': ADMIN_ID, 'from_chat_id': user_chat_id, 'message_id': msg_id}
            requests.post(fwd_url, data=fwd_payload, timeout=5)
            send_message(ADMIN_ID, admin_info, reply_markup=reply_markup, parse_mode='HTML')
            send_message(user_chat_id, "✅ Дякуємо! Ваше повідомлення успішно надіслано адміністратору 💎")
            return
        except Exception as e:
            MainProtokol(f"forwardMessage failed (user): {str(e)}", "ForwardFail")
        media_types = [
            ('photo', 'sendPhoto', 'photo'),
            ('video', 'sendVideo', 'video'),
            ('document', 'sendDocument', 'document'),
            ('audio', 'sendAudio', 'audio'),
            ('voice', 'sendVoice', 'voice'),
            ('animation', 'sendAnimation', 'animation'),
            ('sticker', 'sendSticker', 'sticker')
        ]
        for key, endpoint, payload_key in media_types:
            if key in message:
                file_id = None
                if key == 'photo':
                    file_id = message[key][-1]['file_id']
                elif key == 'video':
                    file_id = message[key][-1]['file_id'] if isinstance(message[key], list) else message[key].get('file_id')
                else:
                    file_id = message[key]['file_id'] if isinstance(message[key], dict) else message[key].get('file_id')
                url = f'https://api.telegram.org/bot{TOKEN}/{endpoint}'
                payload = {
                    'chat_id': ADMIN_ID,
                    payload_key: file_id,
                    'caption': admin_info,
                    'reply_markup': json.dumps(reply_markup),
                    'parse_mode': 'HTML'
                }
                requests.post(url, data=payload)
                break
        send_message(ADMIN_ID, admin_info, reply_markup=reply_markup, parse_mode='HTML')
        send_message(user_chat_id, "✅ Дякуємо! Ваше повідомлення успішно надіслано адміністратору 💎")
    except Exception as e:
        cool_error_handler(e, context="forward_user_message_to_admin: unhandled")
        MainProtokol(str(e), "ForwardUnhandledException")
        try:
            send_message(message['chat']['id'], "⚠️ Виникла помилка при надсиланні. Спробуйте ще раз.")
        except Exception as err:
            cool_error_handler(err, context="forward_user_message_to_admin: notify user")

def forward_ad_to_admin(message):
    try:
        if not ADMIN_ID or ADMIN_ID == 0:
            send_message(message['chat']['id'], "⚠️ Адміністратор не налаштований.")
            return
        user_chat_id = message['chat']['id']
        category = None
        admin_info = build_admin_info(message, category=category)
        reply_markup = _get_reply_markup_for_admin(user_chat_id)
        send_chat_action(ADMIN_ID, 'typing')
        time.sleep(0.25)
        media_groups = extract_media_groups(message)
        sent_any_album = False
        for t, mg in media_groups:
            send_media_group(ADMIN_ID, mg, reply_markup=reply_markup)
            sent_any_album = True
        docs_forwarded = forward_documents_to_admin(message, ADMIN_ID, reply_markup=reply_markup)
        if sent_any_album or docs_forwarded:
            send_message(ADMIN_ID, admin_info, reply_markup=reply_markup, parse_mode='HTML')
            send_message(user_chat_id, "✅ Дякуємо! Ваша заявка преміально надіслана 💎")
            return
        try:
            fwd_url = f'https://api.telegram.org/bot{TOKEN}/forwardMessage'
            fwd_payload = {'chat_id': ADMIN_ID, 'from_chat_id': user_chat_id, 'message_id': message.get('message_id')}
            requests.post(fwd_url, data=fwd_payload, timeout=5)
        except Exception:
            pass
        send_message(ADMIN_ID, admin_info, reply_markup=reply_markup, parse_mode='HTML')
        send_message(user_chat_id, "✅ Дякуємо! Ваша заявка преміально надіслана 💎")
        return
    except Exception as e:
        cool_error_handler(e, context="forward_ad_to_admin: unhandled")
        MainProtokol(str(e), "ForwardAdUnhandledException")
        try:
            send_message(message['chat']['id'], "⚠️ Виникла помилка при надсиланні рекламного запиту. Спробуйте ще раз.")
        except Exception as err:
            cool_error_handler(err, context="forward_ad_to_admin: notify user")

def send_admin_media_reply(user_id, message):
    media_groups = extract_media_groups(message)
    for t, mg in media_groups:
        send_media_group(user_id, mg)
        return True
    docs_forwarded = forward_documents_to_user(user_id, message)
    if docs_forwarded:
        return True
    media_types = [
        ('photo', 'sendPhoto', 'photo'),
        ('video', 'sendVideo', 'video'),
        ('document', 'sendDocument', 'document'),
        ('audio', 'sendAudio', 'audio'),
        ('voice', 'sendVoice', 'voice'),
        ('animation', 'sendAnimation', 'animation'),
        ('sticker', 'sendSticker', 'sticker')
    ]
    for key, endpoint, payload_key in media_types:
        if key in message:
            file_id = None
            if key == 'photo':
                file_id = message[key][-1]['file_id']
            elif key == 'video':
                file_id = message[key][-1]['file_id'] if isinstance(message[key], list) else message[key].get('file_id')
            else:
                file_id = message[key]['file_id'] if isinstance(message[key], dict) else message[key].get('file_id')
            url = f'https://api.telegram.org/bot{TOKEN}/{endpoint}'
            payload = {
                'chat_id': user_id,
                payload_key: file_id
            }
            if 'caption' in message:
                payload['caption'] = message['caption']
            elif 'text' in message:
                payload['caption'] = message['text']
            requests.post(url, data=payload)
            return True
    return False

waiting_for_admin = {}

app = Flask(__name__)

@app.errorhandler(Exception)
def flask_global_error_handler(e):
    cool_error_handler(e, context="Flask global error handler")
    return "Внутрішня помилка сервера PremiumBot.", 500

def format_stats_message(stats: dict) -> str:
    cat_names = [c for c in ADMIN_SUBCATEGORIES]
    max_cat_len = max(len(escape(c)) for c in cat_names) + 1
    col1 = "Категорія".ljust(max_cat_len)
    header = f"{col1}  {'7 дн':>6}  {'30 дн':>6}"
    lines = [header, "═" * (max_cat_len + 16)]
    for cat in ADMIN_SUBCATEGORIES:
        name = escape(cat)
        week = stats[cat]['week']
        month = stats[cat]['month']
        lines.append(f"{name.ljust(max_cat_len)}  {str(week):>6}  {str(month):>6}")
    content = "\n".join(lines)
    return "<pre>════════════════════════════╗\n" + content + "\n════════════════════════════╝</pre>"

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
                        f"💬 Введіть відповідь для користувача <b>{user_id}</b>:",
                        parse_mode='HTML'
                    )
                except Exception as e:
                    cool_error_handler(e, context="webhook: callback_query reply_")
                    MainProtokol(str(e), 'Помилка callback reply')
            elif data == "about":
                send_message(
                    chat_id,
                    "🔹 Ми створюємо ексклюзивних телеграм-ботів та сервіси для вашого бізнесу і життя.\n"
                    "🔗 Деталі та наші канали: https://premiumbot.example.com",
                    parse_mode='HTML'
                )
            elif data == "schedule":
                send_message(
                    chat_id,
                    "📡 Наш бот приймає повідомлення 24/7. Відповідь гарантовано преміальна!",
                    parse_mode='HTML'
                )
            elif data == "write_admin":
                waiting_for_admin_message.add(chat_id)
                send_message(
                    chat_id,
                    "💬 Напишіть преміальне повідомлення адміністратору (текст/фото/документ):",
                    parse_mode='HTML'
                )
            return "ok", 200

        if 'message' in update:
            message = update['message']
            chat_id = message['chat']['id']
            from_id = message['from']['id']
            text = message.get('text', '')
            first_name = message['from'].get('first_name', 'Користувач')
            # Адмін-відповідь з підтримкою преміум медіа
            if from_id == ADMIN_ID and ADMIN_ID in waiting_for_admin:
                user_id = waiting_for_admin.pop(ADMIN_ID)
                if not send_admin_media_reply(user_id, message):
                    send_message(user_id, f"💬 Відповідь адміністратора:\n{text}", parse_mode='HTML')
                send_message(ADMIN_ID, f"✅ Відповідь надіслано користувачу <b>{user_id}</b> 💎", parse_mode='HTML')
                return "ok", 200
            # Персоналізоване преміум-привітання та логіка
            if text == '/start':
                send_chat_action(chat_id, 'typing')
                time.sleep(0.25)
                send_message(
                    chat_id,
                    f"<b>✨ Вітаємо, {escape(first_name)}!</b>\n\n"
                    "Обирайте дію в ексклюзивному меню нижче:",
                    reply_markup=get_reply_buttons(),
                    parse_mode='HTML'
                )
            elif text in MAIN_MENU:
                if text == "💎 Головне":
                    send_message(chat_id, f"✨ Вітаємо, {escape(first_name)}! Ви у головному преміум-меню.", reply_markup=get_reply_buttons(), parse_mode='HTML')
                elif text == "📢 Про нас":
                    send_message(
                        chat_id,
                        "🔹 Ми створюємо ексклюзивних телеграм-ботів та сервіси для вашого бізнесу і життя.\n"
                        "🔗 Деталі: https://premiumbot.example.com",
                        parse_mode='HTML'
                    )
                elif text == "🕰️ Графік роботи":
                    send_message(
                        chat_id,
                        "🕰️ PremiumBot працює цілодобово. Звертайтеся у будь-який час!",
                        parse_mode='HTML'
                    )
                elif text == "💼 Вид роботи":
                    send_message(
                        chat_id,
                        "💼 Оберіть вид роботи для вашого звернення:",
                        reply_markup=get_work_type_buttons(),
                        parse_mode='HTML'
                    )
                elif text == "📝 Повідомити про подію":
                    desc = (
                        "<b>Оберіть тип події:</b>\n\n"
                        "🏗️ <b>Техногенні:</b> Події з діяльністю людини.\n"
                        "🌪️ <b>Природні:</b> Події, спричинені стихією.\n"
                        "👥 <b>Соціальні:</b> Суспільні конфлікти.\n"
                        "⚔️ <b>Воєнні:</b> Військові дії.\n"
                        "🕵️‍♂️ <b>Розшук:</b> Пошук людей.\n"
                        "📦 <b>Інше:</b> Все, що не вписується в інші.\n"
                    )
                    send_message(chat_id, desc, reply_markup=get_admin_subcategory_buttons(), parse_mode='HTML')
                elif text == "📊 Статистика подій":
                    stats = get_stats()
                    if stats:
                        msg = format_stats_message(stats)
                        send_message(chat_id, msg, parse_mode='HTML')
                    else:
                        send_message(chat_id, "Наразі статистика недоступна.", parse_mode='HTML')
                elif text == "📣 Реклама":
                    waiting_for_ad_message.add(chat_id)
                    send_message(
                        chat_id,
                        "📣 Ви обрали розділ «Реклама». Надішліть текст та/або медіа — ми преміально оформимо заявку та надішлемо адміністратору.",
                        reply_markup=get_reply_buttons(),
                        parse_mode='HTML'
                    )
            elif text in WORK_TYPES:
                user_work_type[chat_id] = text
                send_message(
                    chat_id,
                    f"🌟 Ви обрали тип роботи: <b>{escape(text)}</b>.\nДалі можете повідомити про подію або перейти до меню.",
                    reply_markup=get_reply_buttons(),
                    parse_mode='HTML'
                )
            elif text in ADMIN_SUBCATEGORIES:
                user_admin_category[chat_id] = text
                waiting_for_admin_message.add(chat_id)
                send_message(
                    chat_id,
                    f"📝 Опишіть деталі події «{text}» (можна прикріпити преміальні фото чи файли):",
                    parse_mode='HTML'
                )
            else:
                if chat_id in waiting_for_ad_message:
                    forward_ad_to_admin(message)
                    waiting_for_ad_message.remove(chat_id)
                    send_message(
                        chat_id,
                        "📣 Ваша преміальна заявка успішно надіслана! Дякуємо!",
                        reply_markup=get_reply_buttons(),
                        parse_mode='HTML'
                    )
                elif chat_id in waiting_for_admin_message:
                    forward_user_message_to_admin(message)
                    waiting_for_admin_message.remove(chat_id)
                    user_admin_category.pop(chat_id, None)
                    send_message(
                        chat_id,
                        "✨ Ваша інформація передана адміністратору. Дякуємо за активність!",
                        reply_markup=get_reply_buttons(),
                        parse_mode='HTML'
                    )
                else:
                    send_message(
                        chat_id,
                        "💡 Щоб повідомити адміна або надіслати рекламу, скористайтеся преміальними кнопками в меню.",
                        reply_markup=get_reply_buttons(),
                        parse_mode='HTML'
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
        return "PremiumBot працює 💎", 200
    except Exception as e:
        cool_error_handler(e, context="index route")
        return "Помилка сервера PremiumBot", 500

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
