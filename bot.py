from flask import Flask, request
import time
import json
import requests
import os

# ====== Логирование ======
def MainProtokol(s, ts='Запись'):
    dt = time.strftime('%d.%m.%Y %H:%M:') + '00'
    with open('log.txt', 'a') as f:
        f.write(f"{dt};{ts};{s}\n")

# ====== Конфигурация ======
TOKEN = os.getenv("API_TOKEN")  # Telegram токен
ADMIN_ID = os.getenv("ADMIN_ID")  # ID админа
WEBHOOK_URL = f"https://telegram-bot-1-g3bw.onrender.com/webhook/7589889850:AAGp_If3FCVgZCQDrwM2KaCx6bH9ZpGOPGY"

# ====== Главное меню ======
MAIN_MENU = ["📢 Про нас", "Графік роботи", "📝 Написати адміну"]

# ====== Функция отправки сообщений ======
def send_message(chat_id, text):
    url = f'https://api.telegram.org/bot7589889850:AAGp_If3FCVgZCQDrwM2KaCx6bH9ZpGOPGY/sendMessage'
    payload = {'chat_id': chat_id, 'text': text}
    resp = requests.post(url, data=payload)
    if not resp.ok:
        raise ValueError(f"Не удалось отправить сообщение: {resp.text}")
    return resp

# ====== Flask ======
app = Flask(__name__)

@app.route("/")
def index():
    MainProtokol("кто-то просто зашел на сайт")
    return "OK"

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    try:
        update = request.get_json(force=True)

        message = update.get("message")
        if not message:
            return "Нет поля 'message'", 200

        chat_id = message["chat"]["id"]
        text = message.get("text", "")
        first_name = message["from"].get("first_name", "Без имени")

        if text == "/start":
            msg = "Ласкаво просимо! Виберіть дію в меню 👇\n" + "\n".join(MAIN_MENU)
            send_message(chat_id, msg)
        elif text == "📢 Про нас":
            send_message(chat_id, "Ми створюємо телеграм ботів. Детальніше: https://www.instagram.com/p/DOEpwuEiLuC/?igsh=MTdjY3l4Mmt1d2VoeQ==")
        elif text == "Графік роботи":
            send_message(chat_id, "Наш бот приймає повідомлення 25/8! Адмін може спати, але обов’язково відповість 😉")
        elif text == "📝 Написати адміну":
            send_message(chat_id, "✍️ Напишіть повідомлення адміністратору (текст/фото/відео/документ):")
        else:
            admin_msg = f"📩 Допис від {first_name}\nID: {chat_id}\nТекст: {text}"
            send_message(ADMIN_ID, admin_msg)
            send_message(chat_id, "✅ Повідомлення надіслано адміну!")

        return "OK", 200
    except Exception as e:
        MainProtokol(str(e), "Ошибка")
        return str(e), 200
