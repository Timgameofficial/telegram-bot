import os
import html
import logging
from flask import Flask, request
import telebot
from telebot import types

# ====== Конфигурация ======
API_TOKEN = os.getenv("API_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not API_TOKEN:
    raise ValueError("Не задан API_TOKEN!")
if not ADMIN_ID:
    logging.warning("ADMIN_ID не задан! Сообщения админу не будут доставляться.")

bot = telebot.TeleBot(API_TOKEN, parse_mode="HTML")
app = Flask(name)

# ====== Логирование ======
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ====== Хранилища ======
waiting_for_admin = {}   # {admin_id: user_id}
waiting_for_message = {} # {user_id: True}

# ====== Главное меню ======
def get_main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("📢 Про нас", "Графік роботи")
    markup.add("📝 Написати адміну")
    return markup

# ====== Хендлеры ======
@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(message.chat.id, "Ласкаво просимо! Виберіть дію в меню 👇", reply_markup=get_main_menu())

@bot.message_handler(func=lambda msg: msg.text == "📢 Про нас", content_types=["text"])
def about_company(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🏠 Додому")
    bot.send_message(
        message.chat.id,
        "Ми створюємо телеграм ботів. Детальніше: https://www.instagram.com/p/DOEpwuEiLuC/?igsh=MTdjY3l4Mmt1d2VoeQ==",
        reply_markup=markup
    )

@bot.message_handler(func=lambda msg: msg.text == "Графік роботи", content_types=["text"])
def quick_answer(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🏠 Додому")
    bot.send_message(
        message.chat.id,
        "Наш бот приймає повідомлення 25/8! Адмін може спати, але обов’язково відповість 😉",
        reply_markup=markup
    )

@bot.message_handler(func=lambda msg: msg.text == "🏠 Додому", content_types=["text"])
def go_home(message):
    bot.send_message(message.chat.id, "Ви повернулися до головного меню 👇", reply_markup=get_main_menu())

@bot.message_handler(func=lambda msg: msg.text == "📝 Написати адміну", content_types=["text"])
def write_admin(message):
    waiting_for_message[message.from_user.id] = True
    bot.send_message(message.chat.id, "✍️ Напишіть повідомлення адміністратору (текст/фото/відео/документ):")

@bot.message_handler(content_types=["text", "photo", "video", "document", "voice"])
def forward_to_admin(message):
    user_id = message.from_user.id

    # Если пользователь не в режиме отправки админу — пропускаем
    if user_id not in waiting_for_message:
        return

    waiting_for_message.pop(user_id)

    name = html.escape(message.from_user.first_name or "Без имени")
    username = html.escape(f"@{message.from_user.username}" if message.from_user.username else "—")

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
            bot.send_message(ADMIN_ID, f"{caption}\n\n{html.escape(message.text or '')}", reply_markup=markup)

        bot.send_message(user_id, "✅ Повідомлення надіслано адміну!")
    except Exception:
        logging.exception(f"Помилка при надсиланні адміну(user_id={user_id})")
        bot.send_message(user_id, "❌ Помилка надсилання повідомлення. Спробуйте пізніше.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("reply_"))
def admin_reply(call):
    if call.from_user.id != ADMIN_ID:
        return
    user_id = int(call.data.split("_")[1])
    waiting_for_admin[ADMIN_ID] = user_id
    bot.send_message(ADMIN_ID, f"✍️ Введіть відповідь для користувача {user_id}:")

@bot.message_handler(func=lambda msg: msg.from_user.id == ADMIN_ID, content_types=["text", "photo", "video", "document", "voice"])
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
    try:
        json_string = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
    except Exception:
        logging.exception("Ошибка при обработке апдейта")
    return "OK", 200

# ====== Настройка webhook ======
@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    webhook_url = f"https://telegram-bot-1-g3bw.onrender.com/webhook/{API_TOKEN}"
    if bot.set_webhook(url=webhook_url):
        return "Webhook установлен"
    else:
        return "Ошибка установки webhook"

if name == "main":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=False)
