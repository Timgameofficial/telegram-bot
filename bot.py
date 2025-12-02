import os
import time
import json
import requests
import threading
import traceback
import datetime
from flask import Flask, request

from PIL import Image, ImageDraw, ImageFont
import io

# ====== Логування ======
def MainProtokol(s, ts='Запис'):
    dt = time.strftime('%d.%m.%Y %H:%M:') + '00'
    try:
        with open('log.txt', 'a', encoding='utf-8') as f:
            f.write(f"{dt};{ts};{s}\n")
    except Exception as e:
        print("Помилка запису в лог:", e)

def replace_ukr_i(text):
    # заменяет украинскую "і" на латиницу "l"
    return text.replace("і", "l").replace("І", "L")

# ====== Крутий обробник помилок ======
def cool_error_handler(exc, context=""):
    exc_type = type(exc).__name__
    tb_str = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    msg = (
        f"\n{'='*40}\n"
        f"[CRITICAL ERROR]: {exc_type}\n"
        f"Контекст: {context}\n"
        f"Час: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Traceback:\n{tb_str}\n"
        f"{'='*40}\n"
    )
    try:
        with open('critical_errors.log', 'a', encoding='utf-8') as f:
            f.write(msg)
    except Exception as e:
        print("Помилка при запису критичної помилки:", e)
    MainProtokol(msg, ts='CRITICAL ERROR')
    print(msg)
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
    return {
        "keyboard": [
            [{"text": replace_ukr_i("📢 Про нас")}],
            [{"text": replace_ukr_i("🕰️ Графік роботи")}],
            [{"text": replace_ukr_i("📝 Повідомити про подію")}],
            [{"text": replace_ukr_i("📊 Статистика подій")}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

ADMIN_SUBCATEGORIES = [
    replace_ukr_i("🚗 ДТП"),
    replace_ukr_i("🔪 Вбивство"),
    replace_ukr_i("🏠 Побутова подія"),
    replace_ukr_i("🕵️‍♂️ Розшук"),
    replace_ukr_i("💧 Комунальна аварія"),
    replace_ukr_i("📦 Інше")
]

def get_admin_subcategory_buttons():
    return {
        "keyboard": [[{"text": cat}] for cat in ADMIN_SUBCATEGORIES],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }

waiting_for_admin_message = set()
user_admin_category = {}
EVENTS_FILE = 'events.json'

def save_event(category):
    try:
        now_iso = datetime.datetime.now().isoformat()
        events = []
        if os.path.exists(EVENTS_FILE):
            with open(EVENTS_FILE, 'r', encoding='utf-8') as f:
                events = json.load(f)
        events.append({"category": category, "dt": now_iso})
        with open(EVENTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(events, f)
    except Exception as e:
        cool_error_handler(e, "save_event")

def get_stats():
    res = {cat: {'week': 0, 'month': 0} for cat in ADMIN_SUBCATEGORIES}
    now = datetime.datetime.now()
    if os.path.exists(EVENTS_FILE):
        try:
            with open(EVENTS_FILE, 'r', encoding='utf-8') as f:
                events = json.load(f)
            for ev in events:
                cat = ev['category']
                dt_ev = datetime.datetime.fromisoformat(ev['dt'])
                if (now - dt_ev).days < 7:
                    if cat in res:
                        res[cat]['week'] += 1
                if (now - dt_ev).days < 30:
                    if cat in res:
                        res[cat]['month'] += 1
            return res
        except Exception as e:
            cool_error_handler(e, "get_stats")
            return None
    else:
        return res

def clear_stats_if_month_passed():
    now = datetime.datetime.now()
    if os.path.exists(EVENTS_FILE):
        try:
            with open(EVENTS_FILE, 'r', encoding='utf-8') as f:
                events = json.load(f)
            events = [ev for ev in events
                     if (now - datetime.datetime.fromisoformat(ev['dt'])).days < 30]
            with open(EVENTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(events, f)
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
        font_header = ImageFont.truetype(FONT_PATH, 5)
        font_logo = ImageFont.truetype(FONT_PATH, 30)
        font_line = ImageFont.truetype(FONT_PATH, 5)
    except Exception:
        font_header = ImageFont.load_default()
        font_logo = ImageFont.load_default()
        font_line = ImageFont.load_default()

    # Лого зверху
    logo_text = replace_ukr_i("spilkuvach 2.0")
    logo_bbox = draw.textbbox((0,0), logo_text, font=font_logo)
    logo_width = logo_bbox[2] - logo_bbox[0]
    logo_height = logo_bbox[3] - logo_bbox[1]
    draw.text(((width - logo_width)//2, 16), logo_text, fill=(55, 93, 194), font=font_logo)

    # Заголовок під лого
    header_text = replace_ukr_i("Статистика подій")
    header_bbox = draw.textbbox((0,0), header_text, font=font_header)
    header_width = header_bbox[2] - header_bbox[0]
    draw.text(((width-header_width)//2, 60), header_text, fill=(33,53,85), font=font_header)

    # Отступи та список проиществій
    y = header_height + margin
    for cat, v in stats.items():
        line = f"{cat}:\n   За 7 днlв — {v['week']}   За 30 днlв — {v['month']}"
        draw.text((margin, y), line, fill=(44,62,80), font=font_line)
        y += line_height + 14  # дополнительный отступ

    draw.line([(margin, y+5), (width-margin, y+5)], fill=(220,220,220), width=3)

    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes

def send_photo(chat_id, photo_bytes, caption=None):
    url = f'https://api.telegram.org/bot{TOKEN}/sendPhoto'
    files = {'photo': photo_bytes}
    data = {'chat_id': chat_id}
    if caption:
        data['caption'] = replace_ukr_i(caption)
    try:
        resp = requests.post(url, files=files, data=data)
        if not resp.ok:
            MainProtokol(resp.text, 'Помилка надсилання фото')
        return resp
    except Exception as e:
        cool_error_handler(e, context="send_photo")
        MainProtokol(str(e), 'Помилка мережі')

# ====== Конфігурація ======
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

def send_message(chat_id, text, reply_markup=None):
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': replace_ukr_i(text)
    }
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
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
            [{"text": replace_ukr_i("✉️ Відповісти"), "callback_data": f"reply_{user_id}"}]
        ]
    }

def forward_user_message_to_admin(message):
    try:
        if not ADMIN_ID or ADMIN_ID == 0:
            send_message(message['chat']['id'], "⚠️ Адміністратор не налаштований.")
            return

        user_chat_id = message['chat']['id']
        user_first = message['from'].get('first_name', 'Без lменl')
        msg_id = message.get('message_id')
        text = message.get('text') or message.get('caption') or ''
        category = user_admin_category.get(user_chat_id, 'Без категорії')
        admin_info = f"{replace_ukr_i('📩 Категорія')}: {category}\n{replace_ukr_i('Від')}: {user_first}\nID: {user_chat_id}"
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
                send_message(user_chat_id, replace_ukr_i("✅ Дякуємо! Ваше повідомлення надіслано адміністратору."))
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
                send_message(user_chat_id, replace_ukr_i("✅ Дякуємо! Ваше повідомлення надіслано адміністратору."))
                return
        except Exception as e:
            cool_error_handler(e, context="forward_user_message_to_admin: sendMedia")
            MainProtokol(str(e), "SendMediaException")

        if media_sent:
            send_message(user_chat_id, replace_ukr_i("✅ Дякуємо! Ваше повідомлення надіслано адміністратору."))
        else:
            send_message(ADMIN_ID, admin_info, reply_markup=reply_markup)
            send_message(user_chat_id, replace_ukr_i("⚠️ Не вдалося переслати медіа. Адміністратору надіслано текстове повідомлення."))
    except Exception as e:
        cool_error_handler(e, context="forward_user_message_to_admin: unhandled")
        MainProtokol(str(e), "ForwardUnhandledException")
        try:
            send_message(message['chat']['id'], replace_ukr_i("⚠️ Виникла помилка при надсиланні. Спробуйте ще раз."))
        except Exception as err:
            cool_error_handler(err, context="forward_user_message_to_admin: notify user")

waiting_for_admin = {}

app = Flask(__name__)

@app.errorhandler(Exception)
def flask_global_error_handler(e):
    cool_error_handler(e, context="Flask global error handler")
    return replace_ukr_i("Внутрішня помилка сервера. Адміністратору надіслано повідомлення."), 500

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
                        replace_ukr_i(f"✍️ Введіть відповідь для користувача {user_id}:")
                    )
                except Exception as e:
                    cool_error_handler(e, context="webhook: callback_query reply_")
                    MainProtokol(str(e), replace_ukr_i('Помилка callback reply'))
            elif data == "about":
                send_message(
                    chat_id,
                    replace_ukr_i("Ми створюємо телеграм-ботів та сервіси для вашого бізнесу l життя.\nБільше про нас: https://www.instagram.com/p/DOEpwuEiLuC/")
                )
            elif data == "schedule":
                send_message(
                    chat_id,
                    replace_ukr_i("Наш бот приймає повідомлення 24/7! Адміністратор завжди розглядає вашl звернення.")
                )
            elif data == "write_admin":
                waiting_for_admin_message.add(chat_id)
                send_message(
                    chat_id,
                    replace_ukr_i("✍️ Напишіть повідомлення адміністратору (текст/фото/документ):")
                )
            return "ok", 200

        if 'message' in update:
            message = update['message']
            chat_id = message['chat']['id']
            from_id = message['from']['id']
            text = message.get('text', '')
            first_name = message['from'].get('first_name', replace_ukr_i('Без lменl'))

            if from_id == ADMIN_ID and ADMIN_ID in waiting_for_admin:
                user_id = waiting_for_admin.pop(ADMIN_ID)
                send_message(user_id, replace_ukr_i(f"💬 Відповідь адміністратора:\n{text}"))
                send_message(ADMIN_ID, replace_ukr_i(f"✅ Відповідь надіслано користувачу {user_id}"))
                return "ok", 200

            if text == '/start':
                send_message(
                    chat_id,
                    replace_ukr_i("Вітаємо! 👋\nОберіть потрібну дію у меню нижче:"),
                    reply_markup=get_reply_buttons()
                )
            elif text in MAIN_MENU or text in [replace_ukr_i(x) for x in MAIN_MENU]:
                if text == replace_ukr_i("📢 Про нас"):
                    send_message(
                        chat_id,
                        replace_ukr_i("Ми створюємо телеграм-ботів та сервіси для вашого бізнесу l життя.\nДізнатись більше: https://www.instagram.com/p/DOEpwuEiLuC/")
                    )
                elif text == replace_ukr_i("🕰️ Графік роботи"):
                    send_message(
                        chat_id,
                        replace_ukr_i("Ми працюємо цілодобово.\nЗвертайтесь у будь-який час — відповідаємо максимально швидко.")
                    )
                elif text == replace_ukr_i("📝 Повідомити про подію"):
                    send_message(
                        chat_id,
                        replace_ukr_i("Оберіть тип події, яку хочете повідомити:"),
                        reply_markup=get_admin_subcategory_buttons()
                    )
                elif text == replace_ukr_i("📊 Статистика подій"):
                    stats = get_stats()
                    if stats:
                        img_bytes = generate_stats_image(stats)
                        send_photo(chat_id, img_bytes, caption="Звіт по всіх категоріях за останнl 7 та 30 днlв")
                    else:
                        send_message(chat_id, replace_ukr_i("Наразі статистика недоступна."))
            elif text in ADMIN_SUBCATEGORIES:
                user_admin_category[chat_id] = text
                waiting_for_admin_message.add(chat_id)
                send_message(
                    chat_id,
                    replace_ukr_i(f"Будь ласка, опишіть деталі події \"{text}\" (можна прикріпити фото чи файл):")
                )
            else:
                if chat_id in waiting_for_admin_message:
                    forward_user_message_to_admin(message)
                    waiting_for_admin_message.remove(chat_id)
                    user_admin_category.pop(chat_id, None)
                    send_message(
                        chat_id,
                        replace_ukr_i("Ваша інформація передана. Дякуємо за активну позицlю! Якщо потрібно — звертайтесь ще."),
                        reply_markup=get_reply_buttons()
                    )
                else:
                    send_message(
                        chat_id,
                        replace_ukr_i("Щоб повідомити адміна, спочатку натисніть кнопку «📝 Повідомити про подію» в меню."),
                        reply_markup=get_reply_buttons()
                    )
        return "ok", 200

    except Exception as e:
        cool_error_handler(e, context="webhook - outer")
        MainProtokol(str(e), replace_ukr_i('Помилка webhook'))
        return "ok", 200

@app.route('/', methods=['GET'])
def index():
    try:
        MainProtokol(replace_ukr_i('Відвідання сайту'))
        return replace_ukr_i("Бот працює"), 200
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
