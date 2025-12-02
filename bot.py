import os
import time
import json
import requests
import threading
import traceback
import datetime
from flask import Flask, request

# ====== Логирование ======
def MainProtokol(s, ts='Запись'):
    dt = time.strftime('%d.%m.%Y %H:%M:') + '00'
    try:
        with open('log.txt', 'a', encoding='utf-8') as f:
            f.write(f"{dt};{ts};{s}\n")
    except Exception as e:
        print("Ошибка записи в лог:", e)

# ====== Максимально крутой обработчик ошибок ======
def cool_error_handler(exc, context=""):
    exc_type = type(exc).__name__
    tb_str = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    msg = (
        f"\n{'='*40}\n"
        f"[CRITICAL ERROR]: {exc_type}\n"
        f"Context: {context}\n"
        f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Traceback:\n{tb_str}\n"
        f"{'='*40}\n"
    )
    # Запись в лог файл
    try:
        with open('critical_errors.log', 'a', encoding='utf-8') as f:
            f.write(msg)
    except Exception as e:
        print("Ошибка при записи критической ошибки:", e)
    # Также пишем в основной лог
    MainProtokol(msg, ts='CRITICAL ERROR')
    # Выводим в консоль
    print(msg)
    # Если админ задан, отправляем в Telegram админу
    admin_id = int(os.getenv("ADMIN_ID", "0"))
    token = os.getenv("API_TOKEN")
    if admin_id and token:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={
                    "chat_id": admin_id,
                    "text": f"⚠️ Critically Error!\nТип: {exc_type}\nContext: {context}\n\n{str(exc)}",
                    "disable_web_page_preview": True
                },
                timeout=5
            )
        except Exception as e:
            print("Ошибка при отправке ошибки админу:", e)

# ====== Отладка времени в консоль (фоновый поток, каждые 5 минут) ======
def time_debugger():
    while True:
        print("[DEBUG]", time.strftime('%Y-%m-%d %H:%M:%S'))
        time.sleep(300)  # 5 минут

# ====== Главное меню (reply-кнопки) ======
MAIN_MENU = [
    "📢 Про нас",
    "Графік роботи",
    "📝 Написати адміну",
    "📊 Статистика происшествий"
]

def get_reply_buttons():
    return {
        "keyboard": [
            [{"text": "📢 Про нас"}],
            [{"text": "Графік роботи"}],
            [{"text": "📝 Написати адміну"}],
            [{"text": "📊 Статистика происшествий"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }

# ====== Подпункты для связи с админом ======
ADMIN_SUBCATEGORIES = [
    "ДТП",
    "Вбивство",
    "Бытовуха",
    "Розшук",
    "Коммунальные аварии",
    "Разное"
]

def get_admin_subcategory_buttons():
    return {
        "keyboard": [[{"text": cat}] for cat in ADMIN_SUBCATEGORIES],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }

# ====== Хранилище для ожидания сообщения админу и категории ======
waiting_for_admin_message = set()
user_admin_category = {}  # user_id -> category

# ====== Хранилище событий и статистики ======
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
            # Оставляем только события не старше 30 дней
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
        time.sleep(3600)  # каждые 60 минут очищаем

# ====== Конфигурация ======
TOKEN = os.getenv("API_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEBHOOK_URL = f"https://telegram-bot-1-g3bw.onrender.com/webhook/{TOKEN}"

# ====== Установка вебхука ======
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

# ====== Отправка сообщений ======
def send_message(chat_id, text, reply_markup=None):
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': text
    }
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    try:
        resp = requests.post(url, data=payload)
        if not resp.ok:
            MainProtokol(resp.text, 'Ошибка отправки')
        return resp
    except Exception as e:
        cool_error_handler(e, context="send_message")
        MainProtokol(str(e), 'Ошибка сети')

def _get_reply_markup_for_admin(user_id: int):
    return {
        "inline_keyboard": [
            [{"text": "✉️ Відповісти", "callback_data": f"reply_{user_id}"}]
        ]
    }

def forward_user_message_to_admin(message):
    try:
        if not ADMIN_ID or ADMIN_ID == 0:
            send_message(message['chat']['id'], "⚠️ Админ не настроен.")
            return

        user_chat_id = message['chat']['id']
        user_first = message['from'].get('first_name', 'Без имени')
        msg_id = message.get('message_id')
        text = message.get('text') or message.get('caption') or ''
        # Получить категорию
        category = user_admin_category.get(user_chat_id, 'Без категорії')
        admin_info = f"📩 Категорія: {category}\nОт {user_first}\nID: {user_chat_id}"
        if text:
            admin_info += f"\n\n{text}"

        reply_markup = _get_reply_markup_for_admin(user_chat_id)

        # Сохраняем событие для статистики если категория валидная
        if category in ADMIN_SUBCATEGORIES:
            save_event(category)

        try:
            fwd_url = f'https://api.telegram.org/bot{TOKEN}/forwardMessage'
            fwd_payload = {'chat_id': ADMIN_ID, 'from_chat_id': user_chat_id, 'message_id': msg_id}
            fwd_resp = requests.post(fwd_url, data=fwd_payload)
            if fwd_resp.ok:
                send_message(ADMIN_ID, admin_info, reply_markup=reply_markup)
                send_message(user_chat_id, "✅ Повідомлення надіслано адміну!")
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
                send_message(user_chat_id, "✅ Повідомлення надіслано адміну!")
                return
        except Exception as e:
            cool_error_handler(e, context="forward_user_message_to_admin: sendMedia")
            MainProtokol(str(e), "SendMediaException")

        if media_sent:
            send_message(user_chat_id, "✅ Повідомлення надіслано адміну!")
        else:
            send_message(ADMIN_ID, admin_info, reply_markup=reply_markup)
            send_message(user_chat_id, "⚠️ Не вдалося переслати медіа. Адміну надіслано текстове повідомлення.")
    except Exception as e:
        cool_error_handler(e, context="forward_user_message_to_admin: unhandled")
        MainProtokol(str(e), "ForwardUnhandledException")
        try:
            send_message(message['chat']['id'], "⚠️ Сталась помилка при відправці. Спробуйте ще раз.")
        except Exception as err:
            cool_error_handler(err, context="forward_user_message_to_admin: notify user")

# ====== Хранилище ожидания ответа от админа ======
waiting_for_admin = {}

# ====== Flask ======
app = Flask(__name__)

@app.errorhandler(Exception)
def flask_global_error_handler(e):
    cool_error_handler(e, context="Flask global error handler")
    return "Внутренняя ошибка сервера. Администратору отправлено уведомление.", 500

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
                    MainProtokol(str(e), 'Ошибка callback reply')
            elif data == "about":
                send_message(
                    chat_id,
                    "Ми створюємо телеграм ботів. "
                    "Детальніше: "
                    "https://www.instagram.com/p/DOEpwuEiLuC/"
                )
            elif data == "schedule":
                send_message(
                    chat_id,
                    "Наш бот приймає повідомлення 25/8! "
                    "Адмін може спати, але обов’язково відповість 😉"
                )
            elif data == "write_admin":
                waiting_for_admin_message.add(chat_id)
                send_message(
                    chat_id,
                    "✍️ Напишіть повідомлення адміну (текст/фото/документ):"
                )
            return "ok", 200

        if 'message' in update:
            message = update['message']
            chat_id = message['chat']['id']
            from_id = message['from']['id']
            text = message.get('text', '')
            first_name = message['from'].get('first_name', 'Без имени')

            # Ответ админа пользователю
            if from_id == ADMIN_ID and ADMIN_ID in waiting_for_admin:
                user_id = waiting_for_admin.pop(ADMIN_ID)
                send_message(user_id, f"💬 Адмін:\n{text}")
                send_message(ADMIN_ID, f"✅ Відповідь надіслано користувачу {user_id}")
                return "ok", 200

            # Главное меню как Reply-кнопки
            if text == '/start':
                send_message(
                    chat_id,
                    "Ласкаво просимо! Виберіть дію в меню 👇",
                    reply_markup=get_reply_buttons()
                )
            elif text in MAIN_MENU:
                if text == "📢 Про нас":
                    send_message(
                        chat_id,
                        "Ми створюємо телеграм ботів. "
                        "Детальніше: "
                        "https://www.instagram.com/p/DOEpwuEiLuC/"
                    )
                elif text == "Графік роботи":
                    send_message(
                        chat_id,
                        "Наш бот приймає повідомлення 25/8! "
                        "Адмін може спати, але обов’язково відповість 😉"
                    )
                elif text == "📝 Написати адміну":
                    # Показываем подкатегории
                    send_message(
                        chat_id,
                        "Оберіть категорію повідомлення:",
                        reply_markup=get_admin_subcategory_buttons()
                    )
                elif text == "📊 Статистика происшествий":
                    stats = get_stats()
                    if stats:
                        msg = "Статистика за 7 днів / 30 днів:\n"
                        for cat in ADMIN_SUBCATEGORIES:
                            msg += f"{cat}: за 7 днів — {stats[cat]['week']}, за 30 днів — {stats[cat]['month']}\n"
                        send_message(chat_id, msg)
                    else:
                        send_message(chat_id, "Дані не знайдені.")
            elif text in ADMIN_SUBCATEGORIES:
                # Пользователь выбрал категорию для админу
                user_admin_category[chat_id] = text
                waiting_for_admin_message.add(chat_id)
                send_message(
                    chat_id,
                    f"✍️ Напишіть текст або надішліть файл для категорії '{text}':"
                )
            else:
                # Принимаем сообщение админу только если была выбрана категория
                if chat_id in waiting_for_admin_message:
                    forward_user_message_to_admin(message)
                    waiting_for_admin_message.remove(chat_id)
                    user_admin_category.pop(chat_id, None)
                else:
                    send_message(
                        chat_id,
                        "Щоб написати адміну, спочатку натисніть кнопку '📝 Написати адміну' у меню."
                    )

        return "ok", 200

    except Exception as e:
        cool_error_handler(e, context="webhook - outer")
        MainProtokol(str(e), 'Ошибка webhook')
        return "ok", 200

@app.route('/', methods=['GET'])
def index():
    try:
        MainProtokol('Кто-то зашел на сайт')
        return "Бот работает", 200
    except Exception as e:
        cool_error_handler(e, context="index route")
        return "Error", 500

if __name__ == "__main__":
    # Запуск отладчика времени в отдельном потоке (каждые 5 минут)
    try:
        threading.Thread(target=time_debugger, daemon=True).start()
    except Exception as e:
        cool_error_handler(e, context="main: start time_debugger")
    # Автоочистка статистики событий каждые 60 минут
    try:
        threading.Thread(target=stats_autoclear_daemon, daemon=True).start()
    except Exception as e:
        cool_error_handler(e, context="main: start stats_autoclear_daemon")
    port = int(os.getenv("PORT", 5000))
    try:
        app.run(host="0.0.0.0", port=port)
    except Exception as e:
        cool_error_handler(e, context="main: app.run")
