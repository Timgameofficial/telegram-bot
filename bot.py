
import os
from flask import Flask, request, abort
import telebot

# --- Настройки ---
API_TOKEN = os.environ.get("API_TOKEN")  # токен бота
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")        # например https://your-app.onrender.com
USE_POLLING = os.environ.get("USE_POLLING", "false").lower() == "true"

if not API_TOKEN:
    raise RuntimeError("API_TOKEN not set")

bot = telebot.TeleBot(API_TOKEN)
app = Flask(__name__)

# --- Хендлеры ---
@bot.message_handler(commands=["start", "help"])
def start_handler(message):
    bot.reply_to(message, "Привет! ✅ Я тестовый бот и уже отвечаю на команды.")

@bot.message_handler(func=lambda m: True)
def echo_handler(message):
    bot.reply_to(message, f"Echo: {message.text}")

# --- Webhook маршруты ---
@app.route("/")
def index():
    return "Bot is running!", 200

@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    """ Установить вебхук вручную через браузер """
    if not WEBHOOK_URL:
        return "WEBHOOK_URL not set", 400
    bot.remove_webhook()
    ok = bot.set_webhook(url=WEBHOOK_URL + "/webhook")
    return ("Webhook set" if ok else "Failed to set webhook"), (200 if ok else 500)

@app.route("/webhook", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        json_string = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "", 200
    else:
        abort(403)

# --- Локальный режим (polling) ---
def start_polling():
    print("Запуск polling (локально). Нажми Ctrl+C для остановки.")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

if __name__ == "__main__":
    if USE_POLLING:
        start_polling()
    else:
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
