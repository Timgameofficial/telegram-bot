import os
import time
import json
import requests
from flask import Flask, request

# ====== Логирование ======
def MainProtokol(s, ts='Запись'):
    dt = time.strftime('%d.%m.%Y %H:%M:') + '00'
    with open('log.txt', 'a') as f:
        f.write(f"{dt};{ts};{s}\n")

# ====== Конфигурация ======
TOKEN = os.getenv("API_TOKEN")  # Telegram токен
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # ID админа
WEBHOOK_URL = f"https://telegram-bot-1-g3bw.onrender.com/webhook/{TOKEN}"

# ====== Регистрируем вебхук ======
try:
    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={WEBHOOK_URL}")
    if r.ok:
        print("Webhook успешно установлен!")
    else:
        print("Ошибка при установке webhook:", r.text)
except Exception as e:
    print("Не удалось установить webhook:", e)

# ====== Главное меню и кнопки ======
MAIN_MENU = ["📢 Про нас", "Графік роботи", "📝 Написати адміну"]

def get_inline_buttons():
    return {
        "inline_keyboard": [
            [{"text": "📢 Про нас", "callback_data": "about"}],
            [{"text": "Графік роботи", "callback_data": "schedule"}],
            [{"text": "📝 Написати адміну", "callback_data": "write_admin"}]
        ]
    }

# ====== Отправка сообщений ======
def send_message(chat_id, text, reply_markup=None):
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage'
    payload = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)  # важно: JSON string
    resp = requests.post(url, data=payload)
    if not resp.ok:
        raise ValueError(f"Не удалось отправить сообщение: {resp.text}")
    return resp

# ====== Хранилище ожидания ответа от админа ======
waiting_for_admin = {}  # {admin_id: user_id}

# ====== Flask ======
app = Flask(__name__)

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    try:
        data_raw = request.get_data().decode('utf-8')
        update = json.loads(data_raw)

        # ==== Callback кнопки ====
        if 'callback_query' in update:
            call = update['callback_query']
            chat_id = call['from']['id']
            data = call['data']

            if chat_id != ADMIN_ID:
                send_message(chat_id, "❌ Только админ может использовать кнопки.")
                return "ok", 200

            if data.startswith("reply_"):
                user_id = int(data.split("_")[1])
                waiting_for_admin[ADMIN_ID] = user_id
                send_message(ADMIN_ID, f"✍️ Введите ответ для пользователя {user_id}:")
            elif data == "about":
                send_message(chat_id, "Ми створюємо телеграм ботів. Детальніше: https://www.instagram.com/p/DOEpwuEiLuC/?igsh=MTdjY3l4Mmt1d2VoeQ==")
            elif data == "schedule":
                send_message(chat_id, "Наш бот приймає повідомлення 25/8! Адмін може спати, але обов’язково відповість 😉")
            elif data == "write_admin":
                send_message(chat_id, "✍️ Напишіть сообщение админу (текст/фото/документ):")
            return "ok", 200

        # ==== Сообщения пользователей ====
        if 'message' in update:
            message = update['message']
            chat_id = message['chat']['id']
            text = message.get('text', '')
            first_name = message['from'].get('first_name', 'Без имени')

            # Если админ отвечает пользователю
            if message['from']['id'] == ADMIN_ID and ADMIN_ID in waiting_for_admin:
                user_id = waiting_for_admin.pop(ADMIN_ID)
                send_message(user_id, f"💬 Админ:\n{text}")
                send_message(ADMIN_ID, f"✅ Ответ отправлен пользователю {user_id}")
                return "ok", 200

            # Обработка команд и кнопок
            if text == '/start':
                send_message(chat_id, "Ласкаво просимо! Выберите действие в меню 👇", reply_markup=get_inline_buttons())
            elif text in MAIN_MENU:
                if text == "📢 Про нас":
                    send_message(chat_id, "Ми створюємо телеграм ботів. Детальніше: https://www.instagram.com/p/DOEpwuEiLuC/?igsh=MTdjY3l4Mmt1d2VoeQ==")
                elif text == "Графік роботи":
                    send_message(chat_id, "Наш бот приймає повідомлення 25/8! Адмін може спати, але обов’язково відповість 😉")
                elif text == "📝 Написати адміну":
                    send_message(chat_id, "✍️ Напишіть сообщение админу (текст/фото/документ):")
            else:
                # Пересылаем админу любое другое сообщение
                admin_msg = f"📩 Допис від {first_name}\nID: {chat_id}\nТекст: {text}"
                send_message(ADMIN_ID, admin_msg)
                send_message(chat_id, "✅ Повідомлення надіслано адміну!")

        return "ok", 200

    except Exception as e:
        MainProtokol(str(e), 'Ошибка')
        return str(e), 200

# ====== Запуск сайта для проверки ======
@app.route('/', methods=['GET'])
def index():
    MainProtokol('Кто-то зашел на сайт')
    return "Бот работает", 200
