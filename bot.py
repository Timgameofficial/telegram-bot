import os
import time
import json
import requests
from flask import Flask, request

# ====== Логирование ======
def MainProtokol(s, ts='Запись'):
    dt = time.strftime('%d.%m.%Y %H:%M:') + '00'
    try:
        with open('log.txt', 'a', encoding='utf-8') as f:
            f.write(f"{dt};{ts};{s}\n")
    except Exception as e:
        print("Ошибка записи в лог:", e)

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
        print("Не удалось установить webhook:", e)

set_webhook()

# ====== Главное меню ======
MAIN_MENU = [
    "📢 Про нас",
    "Графік роботи",
    "📝 Написати адміну"
]

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
        MainProtokol(str(e), 'Ошибка сети')
# --- Вставляемая функция: пересылка сообщений (текст/фото/видео/документы) и подготовка кнопки "Ответить" ---
def _get_reply_markup_for_admin(user_id: int):
    return {
        "inline_keyboard": [
            [{"text": "✉️ Ответить", "callback_data": f"reply_{user_id}"}]
        ]
    }

def forward_user_message_to_admin(message: dict):
    """
    Универсальная пересылка сообщения от пользователя админу:
      - пытаемся forwardMessage (сохраняет оригинал и вложения);
      - если forwardMessage не прошёл — пересылаем вручную фото/видео/документы по file_id;
      - в любом случае отправляем админу вспомогательное сообщение с инфо и кнопкой "Ответить";
      - уведомляем пользователя о результате.
    Требует существования переменных/функций в основном модуле:
      - TOKEN (str), ADMIN_ID (int), send_message(chat_id, text, reply_markup=None), MainProtokol(str, tag)
    """
    try:
        # Проверка наличия админа
        if not ADMIN_ID or ADMIN_ID == 0:
            send_message(message['chat']['id'], "⚠️ Админ не настроен.")
            return

        user_chat_id = message['chat']['id']
        user_first = message['from'].get('first_name', 'Без имени')
        msg_id = message.get('message_id')
        # Текст из поля text или caption (если это медиа)
        text = message.get('text') or message.get('caption') or ''
        admin_info = f"📩 От {user_first}\nID: {user_chat_id}"
        if text:
            admin_info += f"\n\n{text}"

        reply_markup = _get_reply_markup_for_admin(user_chat_id)

        # 1) Сначала пробуем forwardMessage (сохраняет оригинал и вложения)
        try:
            fwd_url = f'https://api.telegram.org/bot{TOKEN}/forwardMessage'
            fwd_payload = {'chat_id': ADMIN_ID, 'from_chat_id': user_chat_id, 'message_id': msg_id}
            fwd_resp = requests.post(fwd_url, data=fwd_payload)
            if fwd_resp.ok:
                # Добавляем к пересланному сообщению вспомогательное сообщение с кнопкой "Ответить" и краткой инфой
                send_message(ADMIN_ID, admin_info, reply_markup=reply_markup)
                send_message(user_chat_id, "✅ Повідомлення надіслано адміну!")
                return
            else:
                MainProtokol(f"forwardMessage failed: {fwd_resp.text}", "ForwardFail")
        except Exception as e:
            MainProtokol(str(e), "ForwardException")

        # 2) Если forward не прошёл — пытаемся переслать вложения вручную по file_id
        media_sent = False
        r = None
        try:
            if 'photo' in message:
                file_id = message['photo'][-1]['file_id']
                url = f'https://api.telegram.org/bot{TOKEN}/sendPhoto'
                payload = {'chat_id': ADMIN_ID, 'photo': file_id, 'caption': admin_info, 'reply_markup': json.dumps(reply_markup)}
                r = requests.post(url, data=payload)
                media_sent = (r.ok if r is not None else False)
            elif 'video' in message:
                file_id = message['video']['file_id']
                url = f'https://api.telegram.org/bot{TOKEN}/sendVideo'
                payload = {'chat_id': ADMIN_ID, 'video': file_id, 'caption': admin_info, 'reply_markup': json.dumps(reply_markup)}
                r = requests.post(url, data=payload)
                media_sent = (r.ok if r is not None else False)
            elif 'document' in message:
                file_id = message['document']['file_id']
                url = f'https://api.telegram.org/bot{TOKEN}/sendDocument'
                payload = {'chat_id': ADMIN_ID, 'document': file_id, 'caption': admin_info, 'reply_markup': json.dumps(reply_markup)}
                r = requests.post(url, data=payload)
                media_sent = (r.ok if r is not None else False)
            elif 'audio' in message:
                file_id = message['audio']['file_id']
                url = f'https://api.telegram.org/bot{TOKEN}/sendAudio'
                payload = {'chat_id': ADMIN_ID, 'audio': file_id, 'caption': admin_info, 'reply_markup': json.dumps(reply_markup)}
                r = requests.post(url, data=payload)
                media_sent = (r.ok if r is not None else False)
            elif 'voice' in message:
                file_id = message['voice']['file_id']
                url = f'https://api.telegram.org/bot{TOKEN}/sendVoice'
                payload = {'chat_id': ADMIN_ID, 'voice': file_id, 'caption': admin_info, 'reply_markup': json.dumps(reply_markup)}
                r = requests.post(url, data=payload)
                media_sent = (r.ok if r is not None else False)
            elif 'animation' in message:
                file_id = message['animation']['file_id']
                url = f'https://api.telegram.org/bot{TOKEN}/sendAnimation'
                payload = {'chat_id': ADMIN_ID, 'animation': file_id, 'caption': admin_info, 'reply_markup': json.dumps(reply_markup)}
                r = requests.post(url, data=payload)
                media_sent = (r.ok if r is not None else False)
            else:
                # Нет вложений — просто отправляем текст админу
                send_message(ADMIN_ID, admin_info, reply_markup=reply_markup)
                send_message(user_chat_id, "✅ Повідомлення надіслано адміну!")
                return
        except Exception as e:
            MainProtokol(str(e), "SendMediaException")

        # 3) Проверка результата отправки медиа
        if media_sent:
            send_message(user_chat_id, "✅ Повідомлення надіслано адміну!")
        else:
            # Если не удалось переслать медиа — отправляем админу хотя бы текст и уведомляем пользователя
            send_message(ADMIN_ID, admin_info, reply_markup=reply_markup)
            send_message(user_chat_id, "⚠️ Не вдалося переслати медіа. Адміну надіслано текстове повідомлення.")
    except Exception as e:
        MainProtokol(str(e), "ForwardUnhandledException")
        try:
            send_message(message['chat']['id'], "⚠️ Сталась помилка при відправці. Спробуйте ще раз.")
        except Exception:
            pass

# ====== Хранилище ожидания ответа от админа ======
waiting_for_admin = {}

# ====== Flask ======
app = Flask(__name__)

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
                        f"✍️ Введите ответ для пользователя {user_id}:"
                    )
                except Exception as e:
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
                send_message(
                    chat_id,
                    "✍️ Напишіть сообщение админу (текст/фото/документ):"
                )
            return "ok", 200

        if 'message' in update:
            message = update['message']
            chat_id = message['chat']['id']
            from_id = message['from']['id']
            text = message.get('text', '')
            first_name = message['from'].get('first_name', 'Без имени')

            if from_id == ADMIN_ID and ADMIN_ID in waiting_for_admin:
                user_id = waiting_for_admin.pop(ADMIN_ID)
                send_message(user_id, f"💬 Админ:\n{text}")
                send_message(ADMIN_ID, f"✅ Ответ отправлен пользователю {user_id}")
                return "ok", 200

            if text == '/start':
                send_message(
                    chat_id,
                    "Ласкаво просимо! Выберите действие в меню 👇",
                    reply_markup=get_inline_buttons()
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
                    send_message(
                        chat_id,
                        "✍️ Напишіть сообщение админу (текст/фото/документ):"
                    )
            else:
                admin_msg = (
                    f"📩 Допис від {first_name}\n"
                    f"ID: {chat_id}\n"
                    f"Текст: {text}"
                )
                if ADMIN_ID > 0:
                    send_message(ADMIN_ID, admin_msg)
                    send_message(chat_id, "✅ Повідомлення надіслано адміну!")
                else:
                    send_message(chat_id, "⚠️ Админ не подключен!")

        return "ok", 200

    except Exception as e:
        MainProtokol(str(e), 'Ошибка webhook')
        return "ok", 200

@app.route('/', methods=['GET'])
def index():
    MainProtokol('Кто-то зашел на сайт')
    return "Бот работает", 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
