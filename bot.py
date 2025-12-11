# Упрощённый (LIGHT) Telegram webhook бот
# Поддерживает: стартовое меню, приём текст/фото/видео, пересылку админу,
# функция "Написати адміну" с возможностью ответить (текст/медиа).
# Легкий, без БД, без cron и лишней логики.
import os
import json
import requests
import datetime
from html import escape
from flask import Flask, request

API_TOKEN = os.getenv("API_TOKEN", "").strip()
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except Exception:
    ADMIN_ID = 0

WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "").strip()
WEBHOOK_URL = f"https://{WEBHOOK_HOST}/webhook/{API_TOKEN}" if API_TOKEN and WEBHOOK_HOST else ""

app = Flask(__name__)

# Простое логирование в stdout
def log(msg):
    print(f"[BOT] {msg}")

log(f"Starting bot. ADMIN_ID={ADMIN_ID}, API_TOKEN set={'yes' if API_TOKEN else 'no'}")

# ---- UI / клавиатура ----
MAIN_MENU = [
    "Про канал",
    "Реклама",
    "Написати адміну",
    "Надіслати повідомлення"
]

def get_main_keyboard():
    # Две строки по две кнопки для компактности
    kb = {
        "keyboard": [
            [{"text": "Про канал"}, {"text": "Реклама"}],
            [{"text": "Написати адміну"}, {"text": "Надіслати повідомлення"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }
    return kb

# ---- HTTP helpers ----
def _post(url, data=None, files=None, timeout=10):
    try:
        r = requests.post(url, data=data, files=files, timeout=timeout)
        if not r.ok:
            log(f"HTTP {url} failed: {r.status_code} {r.text}")
        return r
    except Exception as e:
        log(f"Network error POST {url}: {e}")
        return None

def _get(url, params=None, timeout=10):
    try:
        r = requests.get(url, params=params, timeout=timeout)
        if not r.ok:
            log(f"HTTP GET {url} failed: {r.status_code} {r.text}")
        return r
    except Exception as e:
        log(f"Network error GET {url}: {e}")
        return None

def send_message(chat_id, text, reply_markup=None, parse_mode=None, timeout=8):
    if not API_TOKEN:
        log("API_TOKEN not set")
        return None
    url = f"https://api.telegram.org/bot{API_TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    if parse_mode:
        payload['parse_mode'] = parse_mode
    return _post(url, data=payload, timeout=timeout)

def forward_message(to_chat_id, from_chat_id, message_id):
    if not API_TOKEN:
        log("API_TOKEN not set for forward")
        return None
    url = f"https://api.telegram.org/bot{API_TOKEN}/forwardMessage"
    payload = {"chat_id": to_chat_id, "from_chat_id": from_chat_id, "message_id": message_id}
    return _post(url, data=payload)

# ---- Простая загрузка файлов в media/ (best-effort) ----
def download_file_by_id(file_id, dest_dir="media"):
    if not API_TOKEN:
        return None
    try:
        os.makedirs(dest_dir, exist_ok=True)
        # getFile via GET with params
        r = _get(f"https://api.telegram.org/bot{API_TOKEN}/getFile", params={"file_id": file_id})
        if not r or not r.ok:
            return None
        info = r.json()
        file_path = info.get("result", {}).get("file_path")
        if not file_path:
            return None
        file_url = f"https://api.telegram.org/file/bot{API_TOKEN}/{file_path}"
        local_name = os.path.basename(file_path)
        timestamp = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
        local_path = os.path.join(dest_dir, f"{timestamp}_{local_name}")
        rr = requests.get(file_url, stream=True, timeout=15)
        if rr.status_code == 200:
            with open(local_path, "wb") as f:
                for chunk in rr.iter_content(1024):
                    f.write(chunk)
            return local_path
        return None
    except Exception as e:
        log(f"download_file_by_id error: {e}")
        return None

# ---- Состояния ----
waiting_for_admin_reply = {}  # admin_id -> {'user_chat_id': int}
pending_contact = set()       # chat_id пользователей, которые нажали "Написати адміну" или "Надіслати повідомлення"

# ---- Формирование карточки для админа ----
def build_admin_card(message, tag="Повідомлення"):
    frm = message.get("from", {}) or {}
    first = (frm.get("first_name") or "").strip()
    last = (frm.get("last_name") or "").strip()
    display = (first + (" " + last if last else "")).strip() or "Без імені"
    username = frm.get("username")
    user_id = frm.get("id")
    msg_id = message.get("message_id", "-")
    date_ts = message.get("date")
    try:
        date_str = datetime.datetime.utcfromtimestamp(int(date_ts)).strftime('%Y-%m-%d %H:%M:%S UTC') if date_ts else '-'
    except Exception:
        date_str = str(date_ts or '-')
    text = message.get("text") or message.get("caption") or ""
    uname = f"@{escape(username)}" if username else "-"
    card_lines = [
        f"<b>📩 {escape(tag)}</b>",
        f"<b>Ім'я:</b> {escape(display)}",
        f"<b>Username:</b> {uname}",
        f"<b>ID:</b> {escape(str(user_id))}",
        f"<b>Дата:</b> {escape(date_str)}",
    ]
    if text:
        safe = escape(text)
        if len(safe) > 1500:
            safe = safe[:1497] + "..."
        card_lines.append("")
        card_lines.append("<b>Текст:</b>")
        card_lines.append(f"<pre>{safe}</pre>")

    # inline button to reply (admin can press to trigger one-time reply flow)
    chat_id = message.get("chat", {}).get("id", user_id)
    reply_button = {
        "inline_keyboard": [
            [{"text": "✉️ Reply", "callback_data": f"reply_{user_id}_{chat_id}_{msg_id}"}]
        ]
    }
    return "\n".join(card_lines), reply_button

# ---- Обработка сообщений администратора, пересылка пользователю ----
def forward_admin_to_user(user_chat_id, admin_message):
    try:
        # photo
        if "photo" in admin_message:
            file_id = admin_message["photo"][-1].get("file_id")
            url = f"https://api.telegram.org/bot{API_TOKEN}/sendPhoto"
            payload = {"chat_id": user_chat_id, "photo": file_id}
            caption = admin_message.get("caption") or admin_message.get("text")
            if caption:
                payload["caption"] = caption
                payload["parse_mode"] = "HTML"
            _post(url, data=payload)
            return True
        # video
        if "video" in admin_message:
            file_id = admin_message["video"].get("file_id")
            url = f"https://api.telegram.org/bot{API_TOKEN}/sendVideo"
            payload = {"chat_id": user_chat_id, "video": file_id}
            caption = admin_message.get("caption") or admin_message.get("text")
            if caption:
                payload["caption"] = caption
                payload["parse_mode"] = "HTML"
            _post(url, data=payload)
            return True
        # document
        if "document" in admin_message:
            file_id = admin_message["document"].get("file_id")
            url = f"https://api.telegram.org/bot{API_TOKEN}/sendDocument"
            payload = {"chat_id": user_chat_id, "document": file_id}
            caption = admin_message.get("caption") or admin_message.get("text")
            if caption:
                payload["caption"] = caption
                payload["parse_mode"] = "HTML"
            _post(url, data=payload)
            return True
        # animation (gif)
        if "animation" in admin_message:
            file_id = admin_message["animation"].get("file_id")
            url = f"https://api.telegram.org/bot{API_TOKEN}/sendAnimation"
            payload = {"chat_id": user_chat_id, "animation": file_id}
            caption = admin_message.get("caption") or admin_message.get("text")
            if caption:
                payload["caption"] = caption
                payload["parse_mode"] = "HTML"
            _post(url, data=payload)
            return True
        # text / fallback
        text = admin_message.get("text") or ""
        if text:
            send_message(user_chat_id, f"✉️ Повідомлення від адміністратора:\n\n{escape(text)}", parse_mode="HTML")
            return True
        # nothing recognizable
        send_message(user_chat_id, "✉️ Повідомлення від адміністратора (без тексту).")
        return True
    except Exception as e:
        log(f"forward_admin_to_user error: {e}")
        return False

# ---- Webhook / обработка апдейтов ----
@app.route(f"/webhook/{API_TOKEN}", methods=["POST"])
def webhook():
    try:
        raw = request.get_data(as_text=True)
        update = json.loads(raw)

        # Callback query (кнопка Reply от админа)
        if "callback_query" in update:
            call = update["callback_query"]
            data = call.get("data", "")
            from_id = call.get("from", {}).get("id")
            callback_id = call.get("id")
            if data.startswith("reply_") and from_id == ADMIN_ID:
                # format: reply_{user_id}_{user_chat_id}_{orig_msg_id}
                parts = data.split("_")
                try:
                    user_id = int(parts[1])
                    user_chat = int(parts[2]) if len(parts) > 2 else user_id
                    waiting_for_admin_reply[ADMIN_ID] = {"user_chat_id": user_chat, "user_id": user_id}
                    send_message(ADMIN_ID, f"✍️ Напишіть відповідь для користувача {user_id} (текст або фото/відео).", reply_markup=get_main_keyboard())
                except Exception as e:
                    log(f"callback reply parse error: {e}")
            # quick ACK optional: answerCallbackQuery to remove loading - keep simple and silent
            return "ok", 200

        # Message handling
        if "message" in update:
            msg = update["message"]
            chat = msg.get("chat", {}) or {}
            chat_id = chat.get("id")
            frm = msg.get("from", {}) or {}
            from_id = frm.get("id")

            # If admin is replying to a user (waiting state)
            if from_id == ADMIN_ID and ADMIN_ID in waiting_for_admin_reply:
                target = waiting_for_admin_reply.pop(ADMIN_ID, None)
                if target:
                    user_chat = target.get("user_chat_id")
                    ok = forward_admin_to_user(user_chat, msg)
                    if ok:
                        send_message(ADMIN_ID, f"✅ Відправлено користувачу {user_chat}.", reply_markup=get_main_keyboard())
                    else:
                        send_message(ADMIN_ID, f"❌ Не вдалося відправити користувачу {user_chat}.", reply_markup=get_main_keyboard())
                    return "ok", 200

            # Команды и меню
            text = msg.get("text", "")

            if text == "/start":
                send_message(chat_id, "Вітаємо! Оберіть дію:", reply_markup=get_main_keyboard())
                return "ok", 200

            if text in MAIN_MENU:
                if text == "Про канал":
                    about = (
                        "<b>Про канал</b>\n\n"
                        "Короткий опис вашого каналу. Публікуємо важливі новини та оголошення."
                    )
                    send_message(chat_id, about, parse_mode="HTML", reply_markup=get_main_keyboard())
                    return "ok", 200
                if text == "Реклама":
                    ad = (
                        "<b>Реклама</b>\n\n"
                        "Інформація про розміщення реклами. Надішліть матеріал — ми його переглянемо."
                    )
                    send_message(chat_id, ad, parse_mode="HTML", reply_markup=get_main_keyboard())
                    return "ok", 200
                if text == "Написати адміну" or text == "Надіслати повідомлення":
                    pending_contact.add(chat_id)
                    send_message(chat_id, "✉️ Надішліть текст або фото/відео — ми пересилаємо адміну. (Надішліть одне повідомлення.)", reply_markup=get_main_keyboard())
                    return "ok", 200

            # Если пользователь помечен как ожидающий пересылки админу
            if from_id != ADMIN_ID and chat_id in pending_contact:
                # Определим тег: реклама или повідомлення, по последней кнопке — не храним отдельно, просто помечаем как "Повідомлення" или "Реклама"
                # Для простоты: если текст содержит слово "реклама" или user нажал "Реклама" раньше - мы не храним это; оставим общий тег.
                tag = "Повідомлення"
                card_text, reply_btn = build_admin_card(msg, tag=tag)
                # Отправим карточку админу с информацией
                if ADMIN_ID and API_TOKEN:
                    send_message(ADMIN_ID, card_text, reply_markup=reply_btn, parse_mode="HTML")
                    # Если есть медиа — пересылаем оригинал (forwardMessage preserves media)
                    orig_msg_id = msg.get("message_id")
                    if "photo" in msg or "video" in msg or "document" in msg or "animation" in msg:
                        try:
                            forward_message(ADMIN_ID, chat_id, orig_msg_id)
                        except Exception as e:
                            log(f"forward_message failed: {e}")
                    # Попытка скачать медиа локально (необязательно) — best-effort
                    try:
                        if "photo" in msg:
                            file_id = msg["photo"][-1].get("file_id")
                            _ = download_file_by_id(file_id)
                        elif "video" in msg:
                            file_id = msg["video"].get("file_id")
                            _ = download_file_by_id(file_id)
                        elif "document" in msg:
                            file_id = msg["document"].get("file_id")
                            _ = download_file_by_id(file_id)
                    except Exception as e:
                        log(f"media download error: {e}")
                    send_message(chat_id, "Дякуємо! Ваше повідомлення отримано та переслано адміну.", reply_markup=get_main_keyboard())
                else:
                    send_message(chat_id, "Відправити адміну тимчасово неможливо (ADMIN_ID або API_TOKEN не налаштовані).", reply_markup=get_main_keyboard())
                pending_contact.discard(chat_id)
                return "ok", 200

            # Если не в режиме отправки — подсказка
            if from_id != ADMIN_ID:
                send_message(chat_id, "Щоб надіслати повідомлення адміну — натисніть кнопку «Надіслати повідомлення» або «Написати адміну».", reply_markup=get_main_keyboard())
                return "ok", 200

        return "ok", 200

    except Exception as e:
        log(f"webhook error: {e}")
        return "ok", 200

@app.route("/", methods=["GET"])
def index():
    return "Bot is running", 200

# Устанавливаем webhook при старте если заданы токен и WEBHOOK_HOST
def set_webhook():
    if not API_TOKEN or not WEBHOOK_URL:
        log("WEBHOOK not configured (missing API_TOKEN or WEBHOOK_HOST)")
        return
    try:
        r = requests.get(f"https://api.telegram.org/bot{API_TOKEN}/setWebhook", params={"url": WEBHOOK_URL}, timeout=6)
        if r.ok:
            log("Webhook установлен")
        else:
            log(f"setWebhook failed: {r.status_code} {r.text}")
    except Exception as e:
        log(f"set_webhook error: {e}")

if __name__ == "__main__":
    set_webhook()
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
