# Исправленная и улучшенная версия вашего бота
# Проверьте и при необходимости скорректируйте переменные окружения:
# API_TOKEN, ADMIN_ID, WEBHOOK_HOST (напр. https://yourdomain.com), WEBHOOK_SECRET (опционально)

import os
import time
import json
import requests
import threading
import traceback
import datetime
from flask import Flask, request, abort

from PIL import Image, ImageDraw, ImageFont
import io

# ====== Конфигурация и проверки ======
TOKEN = os.getenv("API_TOKEN")
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except Exception:
    ADMIN_ID = 0

WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")  # e.g. "https://yourdomain.com"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")  # лучше задать секретный путь
if not WEBHOOK_SECRET and TOKEN:
    # fallback — НЕ рекомендуется держать полный токен; лучше задать WEBHOOK_SECRET явно
    WEBHOOK_SECRET = "hook-" + TOKEN[:10]

if not TOKEN:
    print("WARNING: API_TOKEN not set. Bot will not be able to call Telegram API.")

WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}" if WEBHOOK_SECRET else "/webhook"

REQUEST_TIMEOUT = 6  # seconds

# ====== Логирование ======
LOG_LOCK = threading.Lock()
def MainProtokol(s, ts='Запис'):
    dt = time.strftime('%d.%m.%Y %H:%M:%S')
    try:
        with LOG_LOCK:
            with open('log.txt', 'a', encoding='utf-8') as f:
                f.write(f"{dt};{ts};{s}\n")
    except Exception as e:
        print("Помилка запису в лог:", e)

# ====== Крутий обробник помилок ======
def cool_error_handler(exc, context=""):
    exc_type = type(exc).__name__
    tb_str = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    # Можно фильтровать потенциально чувствительные данные здесь (например, части TOKEN)
    msg = (
        f"\n{'='*40}\n"
        f"[КРИТИЧНА ПОМИЛКА]: {exc_type}\n"
        f"Контекст: {context}\n"
        f"Час: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Traceback:\n{tb_str}\n"
        f"{'='*40}\n"
    )
    try:
        with LOG_LOCK:
            with open('critical_errors.log', 'a', encoding='utf-8') as f:
                f.write(msg)
    except Exception as e:
        print("Помилка при запису критичної помилки:", e)
    MainProtokol(msg, ts='КРИТИЧНА ПОМИЛКА')
    print(msg)
    if ADMIN_ID and TOKEN:
        try:
            safe_text = f"⚠️ Критична помилка!\nТип: {exc_type}\nКонтекст: {context}\n\n{str(exc)}"
            requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                data={
                    "chat_id": ADMIN_ID,
                    "text": safe_text,
                    "disable_web_page_preview": True
                },
                timeout=5
            )
        except Exception as e:
            print("Помилка при надсиланні помилки адміну:", e)

def time_debugger():
    while True:
        print("[DEBUG]", time.strftime('%Y-%m-%d %H:%M:%S'))
        time.sleep(300)

MAIN_MENU = [
    "📢 Про нас",
    "🕰️ Графік роботи",
    "📝 Повідомити про подію",
    "📊 Статистика подій"
]

def get_reply_buttons():
    # Telegram дозволяє або строки, або об'єкти KeyboardButton; используем simpler strings
    return {
        "keyboard": [
            ["📢 Про нас"],
            ["🕰️ Графік роботи"],
            ["📝 Повідомити про подію"],
            ["📊 Статистика подій"]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

ADMIN_SUBCATEGORIES = [
    "🚗 ДТП",
    "🔪 Вбивство",
    "🏠 Побутова подія",
    "🕵️‍♂️ Розшук",
    "💧 Комунальна аварія",
    "📦 Інше"
]

def get_admin_subcategory_buttons():
    return {
        "keyboard": [[cat] for cat in ADMIN_SUBCATEGORIES],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }

waiting_for_admin_message = set()
user_admin_category = {}
waiting_for_admin = {}

EVENTS_FILE = 'events.json'
events_lock = threading.Lock()

def save_event(category):
    try:
        now_iso = datetime.datetime.now().isoformat()
        with events_lock:
            events = []
            if os.path.exists(EVENTS_FILE):
                try:
                    with open(EVENTS_FILE, 'r', encoding='utf-8') as f:
                        events = json.load(f)
                except Exception:
                    # если файл поврежден — перезаписать
                    events = []
            events.append({"category": category, "dt": now_iso})
            with open(EVENTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(events, f, ensure_ascii=False)
    except Exception as e:
        cool_error_handler(e, "save_event")

def get_stats():
    res = {cat: {'week': 0, 'month': 0} for cat in ADMIN_SUBCATEGORIES}
    now = datetime.datetime.now()
    with events_lock:
        if os.path.exists(EVENTS_FILE):
            try:
                with open(EVENTS_FILE, 'r', encoding='utf-8') as f:
                    events = json.load(f)
                for ev in events:
                    cat = ev.get('category')
                    dt_str = ev.get('dt')
                    try:
                        dt_ev = datetime.datetime.fromisoformat(dt_str)
                    except Exception:
                        continue
                    days_diff = (now - dt_ev).days
                    if cat in res:
                        if days_diff < 7:
                            res[cat]['week'] += 1
                        if days_diff < 30:
                            res[cat]['month'] += 1
                return res
            except Exception as e:
                cool_error_handler(e, "get_stats")
                return None
        else:
            return res

def clear_stats_if_month_passed():
    now = datetime.datetime.now()
    with events_lock:
        if os.path.exists(EVENTS_FILE):
            try:
                with open(EVENTS_FILE, 'r', encoding='utf-8') as f:
                    events = json.load(f)
                events = [ev for ev in events
                         if (now - datetime.datetime.fromisoformat(ev['dt'])).days < 30]
                with open(EVENTS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(events, f, ensure_ascii=False)
            except Exception as e:
                cool_error_handler(e, "clear_stats_if_month_passed")

def stats_autoclear_daemon():
    while True:
        try:
            clear_stats_if_month_passed()
        except Exception as e:
            cool_error_handler(e, "stats_autoclear_daemon")
        time.sleep(3600)

# === Генератор зображення зі статистикою ===
FONT_PATH = "DejaVuSerif-BoldItalic.ttf"

def generate_stats_image(stats):
    width, margin, header_height = 600, 40, 80
    line_height = 48
    background = (255, 255, 255)
    items_count = len(stats)
    total_height = header_height + (line_height+5)*items_count + margin + 60

    img = Image.new('RGB', (width, total_height), color=background)
    draw = ImageDraw.Draw(img)

    try:
        font_header = ImageFont.truetype(FONT_PATH, 15)
        font_logo = ImageFont.truetype(FONT_PATH, 30)
        font_line = ImageFont.truetype(FONT_PATH, 15)
    except Exception:
        font_header = ImageFont.load_default()
        font_logo = ImageFont.load_default()
        font_line = ImageFont.load_default()

    logo_text = "Spilkuvach 2.0"
    try:
        logo_bbox = draw.textbbox((0, 0), logo_text, font=font_logo)
        logo_width = logo_bbox[2] - logo_bbox[0]
        draw.text(((width - logo_width)//2, 16), logo_text, fill=(55, 93, 194), font=font_logo)
    except Exception:
        draw.text((margin, 16), logo_text, fill=(55, 93, 194), font=font_logo)

    header_text = "Статистика подій"
    try:
        header_bbox = draw.textbbox((0, 0), header_text, font=font_header)
        header_width = header_bbox[2] - header_bbox[0]
        draw.text(((width-header_width)//2, 60), header_text, fill=(33,53,85), font=font_header)
    except Exception:
        draw.text((margin, 60), header_text, fill=(33,53,85), font=font_header)

    y = header_height + margin
    for cat, v in stats.items():
        line = f"{cat}:\n   За 7 днів — {v['week']}   За 30 днів — {v['month']}"
        draw.text((margin, y), line, fill=(44,62,80), font=font_line)
        y += line_height + 14

    draw.line([(margin, y+5), (width-margin, y+5)], fill=(220,220,220), width=3)

    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes

def send_photo(chat_id, photo_bytes, caption=None):
    if not TOKEN:
        MainProtokol("TOKEN не задан", 'Помилка надсилання фото')
        return None
    url = f'https://api.telegram.org/bot{TOKEN}/sendPhoto'
    files = {'photo': ('stats.png', photo_bytes, 'image/png')}
    data = {'chat_id': chat_id}
    if caption:
        data['caption'] = caption
    try:
        resp = requests.post(url, files=files, data=data, timeout=REQUEST_TIMEOUT)
        if not resp.ok:
            MainProtokol(resp.text, 'Помилка надсилання фото')
        return resp
    except Exception as e:
        cool_error_handler(e, context="send_photo")
        MainProtokol(str(e), 'Помилка мережі')
        return None

def send_message(chat_id, text, reply_markup=None):
    if not TOKEN:
        MainProtokol("TOKEN не задан", 'Помилка надсилання')
        return None
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': text
    }
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup, ensure_ascii=False)
    try:
        resp = requests.post(url, data=payload, timeout=REQUEST_TIMEOUT)
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

def forward_user_message_to_admin(message):
    """
    Пересылает сообщение админу (только админу), НЕ отправляет подтверждение пользователю.
    Возвращает True, если админу отправлено сообщение (включая текстовое), False если админ не настроен или произошла ошибка.
    """
    try:
        if not ADMIN_ID:
            return False

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

        # Сначала пробуем forwardMessage — это дает оригинальное сообщение
        try:
            fwd_url = f'https://api.telegram.org/bot{TOKEN}/forwardMessage'
            fwd_payload = {'chat_id': ADMIN_ID, 'from_chat_id': user_chat_id, 'message_id': msg_id}
            fwd_resp = requests.post(fwd_url, data=fwd_payload, timeout=REQUEST_TIMEOUT)
            if fwd_resp.ok:
                # добавляем дополнительный контекст под пересланным сообщением
                send_message(ADMIN_ID, admin_info, reply_markup=reply_markup)
                return True
            else:
                MainProtokol(f"forwardMessage failed: {fwd_resp.text}", "ForwardFail")
        except Exception as e:
            cool_error_handler(e, context="forward_user_message_to_admin: forwardMessage")

        # Если forward не прошел, пробуем отправить медиа/текст напрямую
        try:
            media_sent = False
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
                    # photo — список размеров
                    file_id = message[key][-1]['file_id'] if key == 'photo' else message[key]['file_id']
                    url = f'https://api.telegram.org/bot{TOKEN}/{endpoint}'
                    payload = {
                        'chat_id': ADMIN_ID,
                        payload_key: file_id,
                        'caption': admin_info,
                        'reply_markup': json.dumps(reply_markup, ensure_ascii=False)
                    }
                    resp = requests.post(url, data=payload, timeout=REQUEST_TIMEOUT)
                    if resp.ok:
                        media_sent = True
                        break
                    else:
                        MainProtokol(f'{endpoint} failed: {resp.text}', "MediaSendFail")
            if media_sent:
                return True
            else:
                # Если нет медиа — отправляем текстовый контекст
                send_message(ADMIN_ID, admin_info, reply_markup=reply_markup)
                return True
        except Exception as e:
            cool_error_handler(e, context="forward_user_message_to_admin: sendMedia")
            return False

    except Exception as e:
        cool_error_handler(e, context="forward_user_message_to_admin: unhandled")
        return False

app = Flask(__name__)

@app.errorhandler(Exception)
def flask_global_error_handler(e):
    cool_error_handler(e, context="Flask global error handler")
    return "Внутрішня помилка сервера. Адміністратору надіслано повідомлення.", 500

# Маршрут webhook - параметризированный путь, проверяем токен внутри
@app.route('/webhook/<token>', methods=['POST'])
def webhook_with_token(token):
    if not TOKEN or token != WEBHOOK_SECRET:
        # Если token не совпадает — отказ
        abort(403)
    return webhook()

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
                    user_id = int(data.split("_", 1)[1])
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
                    "Ми створюємо телеграм-ботів та сервіси для вашого бізнесу і життя.\nБільше про нас: https://www.instagram.com/spilkuvach/"
                )
            elif data == "schedule":
                send_message(
                    chat_id,
                    "Наш бот приймає повідомлення 24/7! Адміністратор завжди розглядає ваші звернення."
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

            # Ответ администратора пользователю (waiting_for_admin хранит mapping admin->user)
            if from_id == ADMIN_ID and ADMIN_ID in waiting_for_admin:
                user_id = waiting_for_admin.pop(ADMIN_ID)
                send_message(user_id, f"💬 Відповідь адміністратора:\n{text}")
                send_message(ADMIN_ID, f"✅ Відповідь надіслано користувачу {user_id}")
                return "ok", 200

            if text == '/start':
                send_message(
                    chat_id,
                    "Вітаємо! 👋\nОберіть потрібну дію у меню нижче:",
                    reply_markup=get_reply_buttons()
                )
            elif text in MAIN_MENU:
                if text == "📢 Про нас":
                    send_message(
                        chat_id,
                        "Ми створюємо телеграм-ботів та сервіси для вашого бізнесу і життя.\nДізнатись більше: https://www.instagram.com/spilkuvach/"
                    )
                elif text == "🕰️ Графік роботи":
                    send_message(
                        chat_id,
                        "Ми працюємо цілодобово.\nЗвертайтесь у будь-який час — відповідаємо максимально швидко."
                    )
                elif text == "📝 Повідомити про подію":
                    send_message(
                        chat_id,
                        "Оберіть тип події, яку хочете повідомити:",
                        reply_markup=get_admin_subcategory_buttons()
                    )
                elif text == "📊 Статистика подій":
                    stats = get_stats()
                    if stats:
                        img_bytes = generate_stats_image(stats)
                        send_photo(chat_id, img_bytes, caption="Звіт по всіх категоріях за останні 7 та 30 днів")
                    else:
                        send_message(chat_id, "Наразі статистика недоступна.")
            elif text in ADMIN_SUBCATEGORIES:
                user_admin_category[chat_id] = text
                waiting_for_admin_message.add(chat_id)
                send_message(
                    chat_id,
                    f"Будь ласка, опишіть деталі події \"{text}\" (можна прикріпити фото чи файл):"
                )
            else:
                if chat_id in waiting_for_admin_message:
                    # Пересылаем админу и отправляем пользователю одно подтверждение
                    ok = forward_user_message_to_admin(message)
                    waiting_for_admin_message.discard(chat_id)
                    user_admin_category.pop(chat_id, None)
                    if ok:
                        send_message(
                            chat_id,
                            "Ваша інформація передана. Дякуємо за активну позицію! Якщо потрібно — звертайтесь ще.",
                            reply_markup=get_reply_buttons()
                        )
                    else:
                        send_message(
                            chat_id,
                            "⚠️ Не вдалося надіслати повідомлення адміністратору. Спробуйте пізніше.",
                            reply_markup=get_reply_buttons()
                        )
                else:
                    send_message(
                        chat_id,
                        "Щоб повідомити адміна, спочатку натисніть кнопку «📝 Повідомити про подію» в меню.",
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

def set_webhook():
    if not TOKEN:
        print("Cannot set webhook: API_TOKEN missing")
        return
    if not WEBHOOK_HOST or not WEBHOOK_SECRET:
        print("WEBHOOK_HOST or WEBHOOK_SECRET not set; skipping webhook registration")
        return
    url = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/setWebhook",
            params={"url": url},
            timeout=REQUEST_TIMEOUT
        )
        if r.ok:
            print("Webhook успішно встановлено!")
        else:
            print("Помилка при встановленні webhook:", r.text)
            MainProtokol(r.text, 'WebhookFail')
    except Exception as e:
        cool_error_handler(e, context="set_webhook")

if __name__ == "__main__":
    # Установка webhook при запуске через __main__ (локально/на render)
    try:
        set_webhook()
    except Exception as e:
        cool_error_handler(e, context="main: set_webhook")

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
        # В продакшене используйте gunicorn/uvicorn
        app.run(host="0.0.0.0", port=port)
    except Exception as e:
        cool_error_handler(e, context="main: app.run")
