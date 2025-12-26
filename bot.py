"""
Auction Car Container Bot на pyTelegramBotAPI (Telebot), без async, один файл, SQLite3.
- Для деплоя на Render: BOT_TOKEN и ADMIN_ID задавать через переменные окружения!
- Минимальный, но production-ready: все аукционы, ставки, выигрыши, заявка, панель админа, FSM-постоянство.

Библиотеки:
  pyTelegramBotAPI
  python-dotenv
"""

import os
import time
import sqlite3
import threading
from datetime import datetime, timedelta
import telebot
from telebot import types

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

assert BOT_TOKEN, "⚠️ Укажи BOT_TOKEN через переменные окружения"
assert ADMIN_ID, "⚠️ Укажи ADMIN_ID (число) через переменные окружения"

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')
DB_PATH = 'bot.sqlite3'
db_lock = threading.Lock()
container_locks = {}

def get_conn():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def get_c_lock(cid):
    if cid not in container_locks:
        container_locks[cid] = threading.Lock()
    return container_locks[cid]

# 1. --- ИНИЦИАЛИЗАЦИЯ БД ---
def init_db():
    with get_conn() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id  INTEGER PRIMARY KEY,
            username     TEXT,
            created_at   TEXT
        );
        CREATE TABLE IF NOT EXISTS containers (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            type         TEXT NOT NULL,
            country      TEXT NOT NULL,
            image_file_id TEXT NOT NULL,
            start_price  REAL NOT NULL,
            current_price REAL NOT NULL,
            status       TEXT NOT NULL,
            last_bid_at  TEXT,
            leader_id    INTEGER,
            created_at   TEXT,
            FOREIGN KEY(leader_id) REFERENCES users(telegram_id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS bids (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            container_id INTEGER NOT NULL,
            user_id      INTEGER NOT NULL,
            amount       REAL NOT NULL,
            created_at   TEXT,
            FOREIGN KEY(container_id) REFERENCES containers(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(telegram_id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS wins (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER,
            container_id INTEGER UNIQUE,
            expires_at   TEXT,
            created_at   TEXT,
            FOREIGN KEY(user_id) REFERENCES users(telegram_id) ON DELETE SET NULL,
            FOREIGN KEY(container_id) REFERENCES containers(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS applications (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            country      TEXT NOT NULL,
            price        REAL NOT NULL,
            image_file_id TEXT NOT NULL,
            description  TEXT NOT NULL,
            status       TEXT NOT NULL,
            created_at   TEXT,
            FOREIGN KEY(user_id) REFERENCES users(telegram_id) ON DELETE SET NULL
        );
        """)
        db.commit()

init_db()

# 2. --- МЕНЮ для user/admin ---
def main_menu(is_admin=False):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Текущие аукционы")
    markup.row("Мои выигрыши", "Мои заявки")
    if is_admin:
        markup.add("🛠 Админ-панель")
    return markup

def admin_menu():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("Выставить контейнер", "Заявки на авто")
    m.add("Активные аукционы")
    m.add("↩️ Назад")
    return m

# 3. --- ХЕЛПЕРЫ ---
def user_is_admin(uid): return uid == ADMIN_ID

def lastbid_expired(last: str):
    # last: str в ISO
    if not last: return False
    try:
        tlast = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
        return datetime.now() > tlast + timedelta(minutes=30)
    except: return False

def expires_in(tillstr):
    till = datetime.strptime(tillstr, "%Y-%m-%d %H:%M:%S") - datetime.now()
    if till.total_seconds() < 0: return "срок вышел"
    return f"{till.seconds//3600}ч {till.seconds%3600//60}м"

# 4. --- ОБРАБОТЧИКИ ---

@bot.message_handler(commands=["start"])
def cmd_start(msg):
    is_admin = user_is_admin(msg.from_user.id)
    with get_conn() as db, db_lock:
        db.execute("INSERT OR IGNORE INTO users (telegram_id, username, created_at) VALUES (?, ?, ?)",
                   (msg.from_user.id, msg.from_user.username, datetime.now().isoformat(sep=" ", timespec="seconds")))
        db.commit()
    bot.send_message(
        msg.chat.id,
        "Добро пожаловать в бот-аукцион контейнеров 🚗📦",
        reply_markup=main_menu(is_admin)
    )

# --- USER: СПИСОК АКТИВНЫХ КОНТЕЙНЕРОВ ---
@bot.message_handler(func=lambda m: m.text == "Текущие аукционы")
def cur_lots(msg):
    with get_conn() as db:
        rows = db.execute(
            "SELECT id, type, country, start_price, current_price, leader_id FROM containers WHERE status='active'"
        ).fetchall()
    if not rows:
        return bot.send_message(msg.chat.id, "Нет активных аукционов.")
    kb = types.InlineKeyboardMarkup()
    for r in rows:
        btn = types.InlineKeyboardButton(
            f"#{r['id']}: {r['type'].title()} {r['country']} ({int(r['current_price'])})",
            callback_data=f"container_{r['id']}"
        )
        kb.add(btn)
    bot.send_message(msg.chat.id, "Активные контейнеры:", reply_markup=kb)

# --- USER: ПРОСМОТР КОНТЕЙНЕРА и СТАВКА ---
@bot.callback_query_handler(func=lambda c: c.data.startswith("container_"))
def view_container(call):
    cid = int(call.data.split("_")[1])
    with get_conn() as db:
        r = db.execute(
            "SELECT * FROM containers WHERE id=?", (cid,)
        ).fetchone()
        if not r:
            return bot.answer_callback_query(call.id, "Контейнер не найден", show_alert=True)
        leader = db.execute("SELECT username FROM users WHERE telegram_id=?", (r["leader_id"],)).fetchone()
        leader_str = f"@{leader['username']}" if leader and leader["username"] else (r["leader_id"] or "—")
    txt = (
        f"<b>Контейнер #{r['id']}</b>\nТип: <b>{r['type']}</b>\nСтрана: <b>{r['country']}</b>\n"
        f"Старт: <b>{int(r['start_price'])}</b>\nТекущая цена: <b>{int(r['current_price'])}</b>\n"
        f"Лидер: <b>{leader_str}</b>"
    )
    kb = types.InlineKeyboardMarkup()
    for delta in [5, 10, 20, 30]:
        kb.add(types.InlineKeyboardButton(f"+{delta}", callback_data=f"bid_{cid}_{delta}"))
    kb.add(types.InlineKeyboardButton("Назад", callback_data="back_to_list"))
    bot.send_photo(call.message.chat.id, r['image_file_id'], caption=txt, reply_markup=kb, parse_mode='HTML')
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("bid_"))
def do_bid(call):
    _, cid, delta = call.data.split("_")
    cid = int(cid)
    delta = int(delta)
    uid = call.from_user.id

    lock = get_c_lock(cid)
    with lock:
        with get_conn() as db:
            r = db.execute("SELECT * FROM containers WHERE id=?", (cid,)).fetchone()
            if not r or r['status'] != "active":
                return bot.answer_callback_query(call.id, "Аукцион завершён!", show_alert=True)
            if lastbid_expired(r['last_bid_at']):
                return bot.answer_callback_query(call.id, "⌛ Аукцион уже завершён.", show_alert=True)
            if uid == r['leader_id']:
                return bot.answer_callback_query(call.id, "Вы и так лидер.", show_alert=True)
            new_price = r['current_price'] + delta
            # Проверка race-condition
            db.execute("BEGIN IMMEDIATE")
            r2 = db.execute("SELECT current_price, leader_id FROM containers WHERE id=?", (cid,)).fetchone()
            if r2['current_price'] != r['current_price']:
                db.rollback()
                return bot.answer_callback_query(call.id, "Кто-то уже повысил ставку!", show_alert=True)
            # OK! Запись
            db.execute(
                "UPDATE containers SET current_price=?, leader_id=?, last_bid_at=? WHERE id=?",
                (new_price, uid, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), cid)
            )
            db.execute(
                "INSERT INTO bids (container_id, user_id, amount, created_at) VALUES (?, ?, ?, ?)",
                (cid, uid, new_price, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            db.execute(
                "INSERT OR IGNORE INTO users (telegram_id, username, created_at) VALUES (?, ?, ?)",
                (uid, call.from_user.username, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            db.commit()
    bot.answer_callback_query(call.id, f"Ваша ставка +{delta} принята!")
    bot.send_message(
        call.from_user.id,
        f"Сделана ставка по контейнеру #{cid}: новая сумма {new_price}",
        disable_notification=True
    )

# --- USER: МОИ ВЫИГРЫШИ ---
@bot.message_handler(func=lambda m: m.text=="Мои выигрыши")
def my_wins(msg):
    uid = msg.from_user.id
    with get_conn() as db:
        cur = db.execute(
            """SELECT w.container_id, w.expires_at, c.type, c.country, c.image_file_id 
               FROM wins w 
               JOIN containers c ON w.container_id = c.id 
               WHERE w.user_id=?
               ORDER BY w.created_at DESC""",
            (uid,))
        wins = cur.fetchall()
    if not wins:
        return bot.send_message(msg.chat.id, "Нет активных выигрышей.")
    for w in wins:
        bot.send_photo(msg.chat.id, w['image_file_id'],
                       caption=f"<b>Контейнер #{w['container_id']}</b> ({w['type']}, {w['country']})\nОсталось: {expires_in(w['expires_at'])}",
                       parse_mode='HTML')

# --- USER: МОИ ЗАЯВКИ (запрос списком) ---
@bot.message_handler(func=lambda m: m.text=="Мои заявки")
def my_apps(msg):
    uid = msg.from_user.id
    with get_conn() as db:
        cur = db.execute(
            "SELECT country, price, status, created_at FROM applications WHERE user_id=? ORDER BY created_at DESC",
            (uid,))
        apps = cur.fetchall()
    if not apps:
        return bot.send_message(msg.chat.id, "У вас нет заявок.")
    for a in apps:
        bot.send_message(msg.chat.id,
                         f"Заявка: {a['country']} за {int(a['price'])} руб. — {a['status']} ({a['created_at']})")

# --- USER: ЗАЯВКА FSM ---
user_fsm = {}
@bot.message_handler(func=lambda m: m.text=="Подать заявку")
def start_app(msg):
    user_fsm[msg.from_user.id] = {"step": "country"}
    bot.send_message(msg.chat.id, "Из какой вы страны?")

@bot.message_handler(func=lambda m: user_fsm.get(m.from_user.id,{}).get("step")=="country")
def fsm_country(msg):
    user_fsm[msg.from_user.id]["country"] = msg.text.strip()
    user_fsm[msg.from_user.id]["step"] = "price"
    bot.send_message(msg.chat.id, "Введите желаемую цену (только число).")

@bot.message_handler(func=lambda m: user_fsm.get(m.from_user.id,{}).get("step")=="price")
def fsm_price(msg):
    try:
        price = float(msg.text.replace(",","."))
        assert price > 0
        user_fsm[msg.from_user.id]["price"] = price
        user_fsm[msg.from_user.id]["step"] = "photo"
        bot.send_message(msg.chat.id, "Пришлите фото/документ автомобиля.")
    except:
        bot.send_message(msg.chat.id, "Введите число больше 0.")

@bot.message_handler(content_types=["photo", "document"])
def fsm_photo(msg):
    st = user_fsm.get(msg.from_user.id, {})
    if st.get("step") != "photo":
        return
    photo_id = None
    if msg.photo:
        photo_id = msg.photo[-1].file_id
    elif msg.document and msg.document.mime_type.startswith("image/"):
        photo_id = msg.document.file_id
    if not photo_id:
        bot.send_message(msg.chat.id, "Пришлите именно фото.")
        return
    user_fsm[msg.from_user.id]["image_file_id"] = photo_id
    user_fsm[msg.from_user.id]["step"] = "desc"
    bot.send_message(msg.chat.id, "Опишите ваши пожелания.")

@bot.message_handler(func=lambda m: user_fsm.get(m.from_user.id,{}).get("step")=="desc")
def fsm_desc(msg):
    user_fsm[msg.from_user.id]["description"] = msg.text.strip()
    d = user_fsm[msg.from_user.id]
    with get_conn() as db:
        db.execute(
            """INSERT INTO applications (user_id, country, price, image_file_id, description, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
            (msg.from_user.id, d["country"], d["price"], d["image_file_id"], d["description"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        db.commit()
    bot.send_message(msg.chat.id, "Заявка принята и отправлена администратору!")
    if ADMIN_ID:
        bot.send_photo(
            ADMIN_ID,
            d["image_file_id"],
            caption=(f"Новая заявка!\nСтрана: {d['country']}\nЦена: {int(d['price'])}\n"
                     f"Описание: {d['description']}\n"
                     f"<a href='tg://user?id={msg.from_user.id}'>{msg.from_user.id}</a>"),
            parse_mode='HTML',
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("Написать пользователю", url=f"tg://user?id={msg.from_user.id}")
            )
        )
    user_fsm.pop(msg.from_user.id, None)

# --- АДМИН-ПАНЕЛЬ ---
@bot.message_handler(func=lambda m: user_is_admin(m.from_user.id) and m.text=="🛠 Админ-панель")
def admin_panel(msg):
    bot.send_message(msg.chat.id, "Добро пожаловать в панель администратора!", reply_markup=admin_menu())

@bot.message_handler(func=lambda m: user_is_admin(m.from_user.id) and m.text=="Выставить контейнер")
def admin_add_cont(msg):
    bot.send_message(msg.chat.id, "Тип (white/gray/black)?")
    user_fsm[msg.from_user.id] = {"astate":"type"}

@bot.message_handler(func=lambda m: user_is_admin(m.from_user.id) and user_fsm.get(m.from_user.id,{}).get("astate")=="type")
def admin_add_type(m):
    if m.text.strip() not in ["white","gray","black"]:
        bot.send_message(m.chat.id, "Введите: white, gray или black.")
        return
    user_fsm[m.from_user.id]["type"] = m.text.strip()
    user_fsm[m.from_user.id]["astate"] = "country"
    bot.send_message(m.chat.id, "Страна происхождения?")

@bot.message_handler(func=lambda m: user_is_admin(m.from_user.id) and user_fsm.get(m.from_user.id,{}).get("astate")=="country")
def admin_add_country(m):
    user_fsm[m.from_user.id]["country"] = m.text.strip()
    user_fsm[m.from_user.id]["astate"] = "price"
    bot.send_message(m.chat.id, "Стартовая цена?")

@bot.message_handler(func=lambda m: user_is_admin(m.from_user.id) and user_fsm.get(m.from_user.id,{}).get("astate")=="price")
def admin_add_price(m):
    try:
        price = float(m.text.replace(",","."))
        assert price > 0
        user_fsm[m.from_user.id]["price"] = price
        user_fsm[m.from_user.id]["astate"] = "photo"
        bot.send_message(m.chat.id, "Пришлите фото-контейнера.")
    except:
        bot.send_message(m.chat.id, "Введите число больше 0.")

@bot.message_handler(content_types=["photo", "document"])
def admin_add_photo(m):
    st = user_fsm.get(m.from_user.id, {})
    if not user_is_admin(m.from_user.id) or st.get("astate") != "photo":
        return
    photo_id = None
    if m.photo:
        photo_id = m.photo[-1].file_id
    elif m.document and m.document.mime_type.startswith("image/"):
        photo_id = m.document.file_id
    if not photo_id:
        bot.send_message(m.chat.id, "Пришлите изображение-контейнера.")
        return
    user_fsm[m.from_user.id]["image_file_id"] = photo_id
    d = user_fsm[m.from_user.id]
    with get_conn() as db:
        db.execute(
            """INSERT INTO containers (type, country, image_file_id, start_price, current_price, status, leader_id, created_at)
            VALUES (?, ?, ?, ?, ?, 'active', NULL, ?)""",
            (d['type'], d['country'], d['image_file_id'], d['price'], d['price'], datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        db.commit()
    bot.send_message(m.chat.id, "Контейнер выставлен на аукцион!", reply_markup=admin_menu())
    user_fsm.pop(m.from_user.id, None)

@bot.message_handler(func=lambda m: user_is_admin(m.from_user.id) and m.text=="Активные аукционы")
def admin_list_lots(msg):
    with get_conn() as db:
        rows = db.execute(
            "SELECT id, type, country, start_price, current_price, leader_id, last_bid_at FROM containers WHERE status='active'"
        ).fetchall()
    if not rows:
        return bot.send_message(msg.chat.id, "Нет активных аукционов.", reply_markup=admin_menu())
    for r in rows:
        txt = (f"<b>#{r['id']} {r['type']}, {r['country']}</b>\n"
               f"Старт: {int(r['start_price'])}, сейчас: {int(r['current_price'])}\n"
               f"Лидер: {r['leader_id'] or '—'}\n"
               f"Последняя ставка: {r['last_bid_at'] or '—'}")
        bot.send_message(msg.chat.id, txt, parse_mode='HTML', reply_markup=None)

@bot.message_handler(func=lambda m: user_is_admin(m.from_user.id) and m.text=="Заявки на авто")
def admin_apps(msg):
    with get_conn() as db:
        apps = db.execute(
            "SELECT id, user_id, country, price, description, image_file_id, status FROM applications WHERE status='pending' ORDER BY created_at"
        ).fetchall()
    if not apps:
        return bot.send_message(msg.chat.id, "Нет новых заявок.", reply_markup=admin_menu())
    for app in apps:
        text = (f"<b>Заявка #{app['id']}</b>\n"
                f"Страна: {app['country']}\nЦена: {app['price']}\n"
                f"Описание: {app['description']}\n"
                f"Пользователь: <a href='tg://user?id={app['user_id']}'>{app['user_id']}</a>")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Принять", callback_data=f"approve_{app['id']}"))
        kb.add(types.InlineKeyboardButton("Отклонить", callback_data=f"reject_{app['id']}"))
        bot.send_photo(msg.chat.id, app['image_file_id'], caption=text, reply_markup=kb, parse_mode='HTML')

@bot.callback_query_handler(func=lambda c: c.data.startswith("approve_") or c.data.startswith("reject_"))
def app_action(call):
    app_id = int(call.data.split("_")[1])
    status = "approved" if call.data.startswith("approve_") else "rejected"
    with get_conn() as db:
        db.execute("UPDATE applications SET status=? WHERE id=?", (status, app_id))
        db.commit()
    bot.answer_callback_query(call.id, f"Заявка {app_id} {'принята' if status=='approved' else 'отклонена'}")
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

# Навигация назад
@bot.message_handler(func=lambda m: m.text=="↩️ Назад")
def back(msg):
    bot.send_message(msg.chat.id, "Главное меню.", reply_markup=main_menu(user_is_admin(msg.from_user.id)))

# --- ФОНОВЫЕ ЗАДАЧИ: завершение аукционов и автоудаление выигрышей ---
def auction_closer():
    while True:
        now = datetime.now()
        with get_conn() as db, db_lock:
            # закрыть все аукционы, где last_bid_at>30 мин назад
            for c in db.execute("SELECT * FROM containers WHERE status='active' AND last_bid_at IS NOT NULL").fetchall():
                if lastbid_expired(c['last_bid_at']):
                    db.execute("UPDATE containers SET status='finished' WHERE id=?", (c['id'],))
                    if c['leader_id']:
                        expires = (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
                        db.execute(
                            "INSERT OR REPLACE INTO wins (user_id, container_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                            (c['leader_id'], c['id'], expires, now.strftime("%Y-%m-%d %H:%M:%S"))
                        )
                        try:
                            bot.send_message(
                                c['leader_id'],
                                f"Вы выиграли аукцион по контейнеру #{c['id']}!\nУ вас 2 часа, чтобы забрать приз."
                            )
                        except: pass
                    db.commit()
        time.sleep(60 if os.getenv("DEBUG") else 120)

def win_cleaner():
    while True:
        now = datetime.now()
        with get_conn() as db, db_lock:
            db.execute("DELETE FROM wins WHERE expires_at < ?", (now.strftime("%Y-%m-%d %H:%M:%S"),))
            db.commit()
        time.sleep(120)

threading.Thread(target=auction_closer, daemon=True).start()
threading.Thread(target=win_cleaner, daemon=True).start()

if __name__ == "__main__":
    print("Bot running.")
    bot.infinity_polling(skip_pending=True)
