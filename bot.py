import os
import logging
from flask import Flask, request
import telebot
from telebot import types

# ====== Конфигурация ======
API_TOKEN = os.getenv("API_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Публичный URL Render

bot = telebot.TeleBot(API_TOKEN, parse_mode="HTML")
app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

# ====== Хранилища ======
waiting_for_admin = {}  # {admin_id: user_id}

# ====== Главное меню ======
def get_main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("📢 Про нас", "Графік роботи")
    markup.add("📝 Написати адміну")
    return markup

# ====== Хендлеры бота ======
@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(message.chat.id, "Ласкаво просимо! Виберіть дію в меню 👇", reply_markup=get_main_menu())

@bot.message_handler(func=lambda msg: msg.text == "📢 Про нас")
def about_company(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🏠 Додому")
    bot.send_message(
        message.chat.id,
        "Ми створюємо телеграм ботів. Детальніше: https://www.instagram.com/p/DOEpwuEiLuC/",
        reply_markup=markup
    )

@bot.message_handler(func=lambda msg: msg.text == "Графік роботи")
def quick_answer(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🏠 Додому")
    bot.send_message(
        message.chat.id,
        "Наш бот приймає повідомлення 25/8! Адмін відповість 😉",
        reply_markup=markup
    )

@bot.message_handler(func=lambda msg: msg.text == "🏠 Додому")
def go_home(message):
    bot.send_message(message.chat.id, "Ви повернулися до головного меню 👇", reply_markup=get_main_menu())

# ====== Пользователь пишет админу ======
@bot.message_handler(func=lambda msg: msg.text == "📝 Написати адміну")
def write_admin(message):
    bot.send_message(message.chat.id, "✍️ Напишіть повідомлення адміністратору:")
    bot.register_next_step_handler(message, forward_to_admin)

def forward_to_admin(message):
    user_id = message.from_user.id
    name = message.from_user.first_name or "Без имени"
    username = f"@{message.from_user.username}" if message.from_user.username else "—"
    caption = f"📩 Допис від {name}\nID: <code>{user_id}</code>\nUsername: {username}"

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✉️ Відповісти", callback_data=f"reply_{user_id}"))

    try:
        if message.photo:
            bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=caption, reply_markup=markup)
        elif message.video:
            bot.send_video(ADMIN_ID, message.video.file_id, caption=caption, reply_markup=markup)
        elif message.document:
            bot.send_document(ADMIN_ID, message.document.file_id, caption=caption, reply_markup=markup)
        elif message.voice:
            bot.send_voice(ADMIN_ID, message.voice.file_id, caption=caption, reply_markup=markup)
        else:
            bot.send_message(ADMIN_ID, f"{caption}\n\n{message.text or ''}", reply_markup=markup)

        bot.send_message(user_id, "✅ Повідомлення надіслано адміну!")
    except Exception:
        logging.exception(f"Помилка при надсиланні адміну(user_id={user_id})")
        bot.send_message(user_id, "❌ Помилка надсилання повідомлення. Спробуйте пізніше.")

# ====== Админ отвечает ======
@bot.callback_query_handler(func=lambda call: call.data.startswith("reply_"))
def admin_reply(call):
    if call.from_user.id != ADMIN_ID:
        return
    user_id = int(call.data.split("_")[1])
    waiting_for_admin[ADMIN_ID] = user_id
    bot.send_message(ADMIN_ID, f"✍️ Введіть відповідь для користувача {user_id}:")

@bot.message_handler(func=lambda msg: msg.from_user.id == ADMIN_ID)
def send_admin_reply(message):
    if ADMIN_ID not in waiting_for_admin:
        return
    user_id = waiting_for_admin.pop(ADMIN_ID)
    try:
        if message.photo:
            bot.send_photo(user_id, message.photo[-1].file_id, caption=f"💬 Адміністратор:\n{message.caption or ''}")
        elif message.video:
            bot.send_video(user_id, message.video.file_id, caption=f"💬 Адміністратор:\n{message.caption or ''}")
        elif message.document:
            bot.send_document(user_id, message.document.file_id, caption=f"💬 Адміністратор:\n{message.caption or ''}")
        elif message.voice:
            bot.send_voice(user_id, message.voice.file_id, caption="💬 Голосове повідомлення від адміністратора")
        else:
            bot.send_message(user_id, f"💬 Адміністратор:\n{message.text or ''}")

        bot.send_message(ADMIN_ID, f"✅ Відповідь надіслано користувачу {user_id}")
    except Exception:
        logging.exception(f"Помилка під час відповіді користувачу {user_id}")
        bot.send_message(ADMIN_ID, f"❌ Помилка при надсиланні відповіді користувачу {user_id}")

# ====== Webhook endpoint ======
@app.route(f"/webhook/{API_TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

# ====== Запуск Flask и установка вебхука ======
if __name__ == "__main__":
    bot.remove_webhook()
    bot.set_webhook(url=f"{WEBHOOK_URL}/webhook/{API_TOKEN}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
