import time
import json
import requests
import os
from flask import Flask, request

# ====== Логирование ======
def MainProtokol(s, ts='Запись'):
    dt = time.strftime('%d.%m.%Y %H:%M:') + '00'
    with open('log.txt', 'a') as f:
        f.write(f"{dt};{ts};{s}\n")

# ====== Конфигурация ======
TOKEN = os.getenv("API_TOKEN")  # Telegram токен
ADMIN_ID = os.getenv("ADMIN_ID")  # ID админа
WEBHOOK_URL = f"https://telegram-bot-1-g3bw.onrender.com/webhook/{TOKEN}"

# ====== Главное меню и инлайн кнопки ======
MAIN_MENU = ["📢 Про нас", "Графік роботи", "📝 Написати адміну"]

def get_inline_buttons():
    """Возвращает JSON для инлайн-кнопок"""
    return json.dumps({
        "inline_keyboard": [
            [{"text": "📢 Про нас", "callback_data": "about"}],
            [{"text": "Графік роботи", "callback_data": "schedule"}],
            [{"text": "📝 Написати адміну", "callback_data": "write_admin"}]
        ]
    })

# ====== Функция отправки сообщений ======
def send_message(chat_id, text, reply_markup=None):
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage'
    payload = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        payload['reply_markup'] = reply_markup
    resp = requests.post(url, data=payload)
    if not resp.ok:
        raise ValueError(f"Не удалось отправить сообщение: {resp.text}")
    return resp

def send_media(chat_id, media_type, file_id, caption=""):
    url_map = {
        'photo': f'https://api.telegram.org/bot{TOKEN}/sendPhoto',
        'video': f'https://api.telegram.org/bot{TOKEN}/sendVideo',
        'document': f'https://api.telegram.org/bot{TOKEN}/sendDocument',
        'voice': f'https://api.telegram.org/bot{TOKEN}/sendVoice',
    }
    if media_type not in url_map:
        return
    data = {'chat_id': chat_id, 'caption': caption}
    files = {media_type: file_id} if media_type in ['photo','video','document','voice'] else None
    requests.post(url_map[media_type], data=data)

# ====== Основной обработчик webhook ======
def application(env, start_response):
    try:
        path = env.get('PATH_INFO', '')
        if path.lower() == '/webhook/' + TOKEN:
            wsgi_input = env['wsgi.input'].read()
            data_raw = wsgi_input.decode('utf-8').replace('\n',' ')
            update = json.loads(data_raw)

            message = update.get('message')
            callback = update.get('callback_query')

            if message:
                chat_id = message['chat']['id']
                text = message.get('text', '')
                first_name = message['from'].get('first_name','Без имени')

                if text == '/start':
                    send_message(chat_id, "Ласкаво просимо! Выберите команду 👇", reply_markup=get_inline_buttons())
                elif text in MAIN_MENU:
                    if text == "📢 Про нас":
                        send_message(chat_id, "Ми створюємо телеграм ботів. Детальніше: https://www.instagram.com/p/DOEpwuEiLuC/?igsh=MTdjY3l4Mmt1d2VoeQ==")
                    elif text == "Графік роботи":
                        send_message(chat_id, "Наш бот приймає повідомлення 25/8! Адмін може спати, але обов’язково відповість 😉")
                    elif text == "📝 Написати адміну":
                        send_message(chat_id, "✍️ Напишіть повідомлення адміністратору (текст/фото/відео/документ):")
                else:
                    # пересылаем все админу
                    admin_msg = f"📩 Допис від {first_name}\nID: {chat_id}\nТекст: {text}"
                    send_message(ADMIN_ID, admin_msg)
                    if 'photo' in message:
                        send_media(ADMIN_ID,'photo',message['photo'][-1]['file_id'],caption=f"Фото от {first_name}")
                    if 'video' in message:
                        send_media(ADMIN_ID,'video',message['video']['file_id'],caption=f"Видео от {first_name}")
                    if 'document' in message:
                        send_media(ADMIN_ID,'document',message['document']['file_id'],caption=f"Документ от {first_name}")
                    if 'voice' in message:
                        send_media(ADMIN_ID,'voice',message['voice']['file_id'],caption=f"Голосовое от {first_name}")
                    send_message(chat_id, "✅ Повідомлення надіслано адміну!")

            elif callback:
                data = callback['data']
                chat_id = callback['from']['id']
                if data == 'about':
                    send_message(chat_id, "Ми створюємо телеграм ботів. Детальніше: https://www.instagram.com/p/DOEpwuEiLuC/?igsh=MTdjY3l4Mmt1d2VoeQ==")
                elif data == 'schedule':
                    send_message(chat_id, "Наш бот приймає повідомлення 25/8! Адмін може спати, але обов’язково відповість 😉")
                elif data == 'write_admin':
                    send_message(chat_id, "✍️ Напишіть повідомлення адміністратору (текст/фото/відео/документ):")

        elif path == '/':
            MainProtokol('кто-то просто зашел на сайт')
        else:
            raise ValueError(f"Вызов неизвестного URL :: {path}")

        start_response('200 OK', [('Content-Type','text/html')])
        return [b'']

    except Exception as e:
        MainProtokol(str(e),'Ошибка')
        start_response('200 OK', [('Content-Type','text/html')])
        return [str(e).encode('utf-8')]


# ====== Flask для локального теста ======
app = Flask(__name__)

@app.route(f'/webhook/{TOKEN}', methods=['POST'])
def webhook():
    return application(request.environ, lambda status, headers: None)

@app.route('/')
def index():
    return "Бот работает!"

