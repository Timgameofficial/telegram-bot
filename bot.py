import os
import json
import requests
from flask import Flask, request

TOKEN = os.getenv("API_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEBHOOK_URL = f"https://telegram-bot-1-g3bw.onrender.com/webhook/{TOKEN}"

MAIN_MENU = ["📢 Про нас", "Графік роботи"]

app = Flask(__name__)
waiting_for_admin = {}

def send_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    r = requests.post(url, data=payload)
    if not r.ok:
        print("Ошибка отправки сообщения:", r.text)

def send_media(chat_id, message):
    caption = f"📩 Допис від {message['from'].get('first_name','Без имени')}\nID: {chat_id}"
    markup = {"inline_keyboard":[[{"text":"✉️ Відповісти","callback_data":f"reply_{chat_id}" }]]}
    if "photo" in message:
        file_id = message["photo"][-1]["file_id"]
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", data={"chat_id":ADMIN_ID,"photo":file_id,"caption":caption,"reply_markup":json.dumps(markup)})
    elif "video" in message:
        file_id = message["video"]["file_id"]
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendVideo", data={"chat_id":ADMIN_ID,"video":file_id,"caption":caption,"reply_markup":json.dumps(markup)})
    elif "document" in message:
        file_id = message["document"]["file_id"]
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendDocument", data={"chat_id":ADMIN_ID,"document":file_id,"caption":caption,"reply_markup":json.dumps(markup)})
    elif "voice" in message:
        file_id = message["voice"]["file_id"]
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendVoice", data={"chat_id":ADMIN_ID,"voice":file_id,"caption":caption,"reply_markup":json.dumps(markup)})
    else:
        send_message(ADMIN_ID, f"{caption}\n\n{message.get('text','')}", reply_markup=markup)

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    try:
        update = request.get_json()
        if "message" in update:
            message = update["message"]
            chat_id = message["chat"]["id"]
            text = message.get("text","")

            if text == "/start":
                send_message(chat_id, "Ласкаво просимо! Виберіть дію в меню 👇", 
                             reply_markup={"keyboard":[[m] for m in MAIN_MENU], "resize_keyboard":True})
            elif text == "📢 Про нас":
                send_message(chat_id, "Ми створюємо телеграм ботів. Детальніше: https://www.instagram.com/p/DOEpwuEiLuC/?igsh=MTdjY3l4Mmt1d2VoeQ==")
            elif text == "Графік роботи":
                send_message(chat_id, "Наш бот приймає повідомлення 25/8! Адмін може спати, але обов’язково відповість 😉")
            else:
                send_media(message)

        elif "callback_query" in update:
            call = update["callback_query"]
            user_id = int(call["data"].split("_")[1])
            waiting_for_admin[call["from"]["id"]] = user_id
            send_message(call["from"]["id"], f"✍️ Введіть відповідь для користувача {user_id}:")

        elif "message" in update and update["message"]["from"]["id"] in waiting_for_admin:
            admin_id = update["message"]["from"]["id"]
            if admin_id in waiting_for_admin:
                user_id = waiting_for_admin.pop(admin_id)
                msg = update["message"]
                if "text" in msg:
                    send_message(user_id, f"💬 Адміністратор:\n{msg['text']}")
                elif "photo" in msg:
                    file_id = msg["photo"][-1]["file_id"]
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", data={"chat_id":user_id,"photo":file_id,"caption":"💬 Адміністратор"})
                elif "video" in msg:
                    file_id = msg["video"]["file_id"]
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendVideo", data={"chat_id":user_id,"video":file_id,"caption":"💬 Адміністратор"})
                elif "document" in msg:
                    file_id = msg["document"]["file_id"]
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendDocument", data={"chat_id":user_id,"document":file_id,"caption":"💬 Адміністратор"})
                elif "voice" in msg:
                    file_id = msg["voice"]["file_id"]
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendVoice", data={"chat_id":user_id,"voice":file_id,"caption":"💬 Голосове повідомлення від адміністратора"})
        return "", 200
    except Exception as e:
        print("Webhook error:", e)
        return "", 500

if __name__ == "__main__":
    # Устанавливаем webhook автоматически при запуске
    try:
        r = requests.get(f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={WEBHOOK_URL}")
        print("Webhook установлен:", r.text)
    except Exception as e:
        print("Ошибка установки webhook:", e)
    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT",5000)))
