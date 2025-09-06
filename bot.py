import time
import json
import requests
import os
import requests

# ====== Логирование ======
def MainProtokol(s, ts='Запись'):
    dt = time.strftime('%d.%m.%Y %H:%M:') + '00'
    with open('log.txt', 'a') as f:
        f.write(f"{dt};{ts};{s}\n")

# ====== Конфигурация ======
TOKEN = os.getenv("API_TOKEN")  # Telegram токен
ADMIN_ID = os.getenv("ADMIN_ID")  # ID админа
WEBHOOK_URL = f"https://telegram-bot-1-g3bw.onrender.com/webhook/7589889850:AAGp_If3FCVgZCQDrwM2KaCx6bH9ZpGOPGY"

# Регистрируем вебхук у Telegram
try:
    r = requests.get(f"https://api.telegram.org/bot7589889850:AAGp_If3FCVgZCQDrwM2KaCx6bH9ZpGOPGY/setWebhook?url=https://telegram-bot-1-g3bw.onrender.com/webhook/7589889850:AAGp_If3FCVgZCQDrwM2KaCx6bH9ZpGOPGY
")
    if r.ok:
        print("Webhook успешно установлен!")
    else:
        print("Ошибка при установке webhook:", r.text)
except Exception as e:
    print("Не удалось установить webhook:", e)

# ====== Главное меню ======
MAIN_MENU = ["📢 Про нас", "Графік роботи", "📝 Написати адміну"]

# ====== Функция отправки сообщений ======
def send_message(chat_id, text):
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage'
    payload = {'chat_id': chat_id, 'text': text}
    resp = requests.post(url, data=payload)
    if not resp.ok:
        raise ValueError(f"Не удалось отправить сообщение: {resp.text}")
    return resp

# ====== Основной обработчик webhook ======
def application(env, start_response):
    try:
        content = ''
        path = env.get('PATH_INFO', '')
        if path.lower() == '/tg_bot':
            wsgi_input = env['wsgi.input'].read()
            data_raw = wsgi_input.decode('utf-8').replace('\n', ' ')
            
            try:
                update = json.loads(data_raw)
            except Exception:
                raise ValueError("Не удалось распарсить JSON")

            # ====== Получаем данные от пользователя ======
            message = update.get('message')
            if not message:
                raise ValueError("Нет поля 'message' в JSON")

            chat_id = message['chat']['id']
            text = message.get('text', '')
            first_name = message['from'].get('first_name', 'Без имени')

            # ====== Обработка команд и кнопок ======
            if text == '/start':
                msg = "Ласкаво просимо! Виберіть дію в меню 👇\n" + "\n".join(MAIN_MENU)
                send_message(chat_id, msg)
            elif text == "📢 Про нас":
                send_message(chat_id, "Ми створюємо телеграм ботів. Детальніше: https://www.instagram.com/p/DOEpwuEiLuC/?igsh=MTdjY3l4Mmt1d2VoeQ==")
            elif text == "Графік роботи":
                send_message(chat_id, "Наш бот приймає повідомлення 25/8! Адмін може спати, але обов’язково відповість 😉")
            elif text == "📝 Написати адміну":
                send_message(chat_id, "✍️ Напишіть повідомлення адміністратору (текст/фото/відео/документ):")
            else:
                # Просто пересылаем админу любое другое сообщение
                admin_msg = f"📩 Допис від {first_name}\nID: {chat_id}\nТекст: {text}"
                send_message(ADMIN_ID, admin_msg)
                send_message(chat_id, "✅ Повідомлення надіслано адміну!")

        elif path == '/':
            MainProtokol('кто-то просто зашел на сайт')
        else:
            raise ValueError(f"Вызов неизвестного URL :: {path}")

        start_response('200 OK', [('Content-Type', 'text/html')])
        return [content.encode('utf-8')]

    except Exception as e:
        MainProtokol(str(e), 'Ошибка')
        start_response('200 OK', [('Content-Type', 'text/html')])
        return [str(e).encode('utf-8')]


from flask import Flask

app = Flask(__name__)
