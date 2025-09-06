
import os
from flask import Flask, request, abort
import telebot

# Получите токен и URL из переменных окружения
API_TOKEN = os.environ.get("API_TOKEN")  # <-- обязательно установить
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")        # <-- e.g. https://your-app.onrender.com/webhook
USE_POLLING = os.environ.get("USE_POLLING", "false").lower() == "true"

if not API_TOKEN:
    raise RuntimeError("API_TOKEN environment variable is not set")

bot = telebot.TeleBot(API_TOKEN)
app = Flask(__name__)

# -------- Bot handlers (тестовые) --------
@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    bot.reply_to(message, "Привет! Я тестовый бот. Отвечаю на /start и эхо-сообщения.")

@bot.message_handler(func=lambda m: True)
def echo_all(message):
    # простой эхо — для теста
    bot.reply_to(message, f"Echo: {message.text}")

# -------- Webhook routes (для Render) --------
@app.route("/")
def index():
    return "Telegram bot running", 200

@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    """
    Вручную установить webhook: откройте /set_webhook в браузере после установки WEBHOOK_URL
    Или вызывайте этот URL при деплое.
    """
    if not WEBHOOK_URL:
        return "WEBHOOK_URL not set", 400
    # сначала удалим старые
    bot.remove_webhook()
    ok = bot.set_webhook(url=WEBHOOK_URL)
    return ("Webhook set" if ok else "Failed to set webhook"), (200 if ok else 500)

# Telegram будет POSTить сюда обновления
@app.route("/webhook", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        json_string = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "", 200
    else:
        abort(403)

# -------- Starter: polling fallback (локально) --------
def start_polling():
    print("Запуск в режиме polling (локально). Ctrl+C для остановки.")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

# -------- Entry point для gunicorn/render --------
if __name__ == "__main__":
    # если запуск напрямую: либо polling, либо flask dev
    if USE_POLLING:
        start_polling()
    else:
        # dev Flask (не для production): если хотите запустить быстро локально
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

