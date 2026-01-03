# -*- coding: utf-8 -*-
"""
Telegram Bot с поддержкой мультиязычности (UK, RU, EN)
Обработка событий, статистика, реклама
"""
import os
import time
import json
import requests
import threading
import traceback
import datetime
from html import escape
from pathlib import Path
from flask import Flask, request

# Библиотека для работы с разными БД (Postgres/SQLite)
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ArgumentError

# ===================================
# ====== СИСТЕМА ЛОКАЛИЗАЦИИ ========
# ===================================

TRANSLATIONS = {
    'uk': {
        'main_menu_main': '✨ Головне',
        'main_menu_about': '📢 Про нас',
        'main_menu_schedule': '🕰️ Графік роботи',
        'main_menu_event': '📝 Повідомити про подію',
        'main_menu_stats': '📊 Статистика подій',
        'main_menu_ads': '📣 Реклама 🔔',
        'welcome_title': '✨ Ласкаво просимо, {name}{vip}! ',
        'welcome_subtitle': 'Ви опинилися у преміальному інтерфейсі нашого сервісу.',
        'welcome_available': 'Що доступно прямо зараз: ',
        'welcome_quick_report': '• 📝 Швидко повідомити про подію',
        'welcome_stats': '• 📊 Переглянути статистику по категоріях',
        'welcome_ads':  '• 📣 Надіслати рекламне повідомлення',
        'welcome_footer': 'Натисніть одну з кнопок внизу, щоб почати.',
        'cat_technogenic': '🏗️ Техногенні',
        'cat_natural': '🌪️ Природні',
        'cat_social': '👥 Соціальні',
        'cat_military': '⚔️ Воєнні',
        'cat_search': '🕵️‍♂️ Розшук',
        'cat_other': '📦 Інше',
        'about_title': '<b>Про нас</b>',
        'about_team': 'Ми — невелика команда розробників і операторів, що створює інструменти для оперативного обміну інформацією.',
        'about_features': '<b>Що ви можете зробити через бота: </b>',
        'about_feature_1': '• <b>Повідомити про подію</b> — надішліть фото/відео/документ і короткий опис; матеріали будуть передані адміністратору.',
        'about_feature_2': '• <b>Реклама</b> — надсилайте рекламні матеріали, ми опрацюємо їх та зв\'яжемося щодо розміщення.',
        'about_feature_3': '• <b>Статистика</b> — перегляд по категоріях за 7 та 30 днів.',
        'about_privacy': '<b>Приватність</b>:  особисті дані передаються адміністратору лише для обробки повідомлення; ми не продаємо їх.',
        'about_contacts': '<b>Контакти</b>: ',
        'about_contact_admin': '• Напишіть адміністратору через кнопку «Написати адміністратору».',
        'about_instagram': '• Instagram: <a href="https://www.instagram.com/creator. bot_official? igsh=cHg1aDRqNXdrb210">@creator.bot_official</a>',
        'about_schedule': '<b>Режим роботи</b>:  відповіді за можливості, термінові питання обробляються першочергово.',
        'event_instructions': 'Надсилайте усі потрібні фото, відео, документи та/або текст (кілька повідомлень). Як закінчите — натисніть ✅ Надіслати.',
        'event_thanks': '✅ Ваші дані відправлено.  Дякуємо! ',
        'event_cancelled': '❌ Скасовано.',
        'event_added': 'Додано до пакету.  Продовжуйте надсилати або натисніть ✅ Надіслати.',
        'event_no_media': 'Немає медіа для надсилання.',
        'stats_category':  'Категорія',
        'stats_week': '7 дн',
        'stats_month': '30 дн',
        'stats_unavailable': 'Наразі статистика недоступна.',
        'media_continue': 'Додано до пакету. Продовжуйте надсилати або натисніть ✅ Надіслати.',
        'media_confirm': 'Додано до події. Продовжуйте надсилати матеріали або натисніть ✅ Підтвердити / ❌ Відмінити',
        'btn_send': '✅ Надіслати',
        'btn_cancel': '❌ Скасувати',
        'btn_confirm': '✅ Підтвердити',
        'btn_reject': '❌ Відмінити',
        'btn_reply': '✉️ Відповісти',
        'btn_add_stat': '➕ Додати до статистики',
        'btn_write_admin': 'Написати адміністратору',
        'admin_new_event': '📩 Нова подія',
        'admin_new_ad': '📣 Рекламне повідомлення',
        'admin_new_message': '📩 Нове повідомлення',
        'admin_profile': 'Профіль',
        'admin_id': 'ID',
        'admin_phone': 'Телефон',
        'admin_location': 'Локація',
        'admin_category': 'Категорія',
        'admin_message_id': 'Message ID',
        'admin_date': 'Дата',
        'admin_text': 'Текст / Опис',
        'admin_reply_text': '✍️ Введіть відповідь для користувача {user_id} (будь-який текст або файл):',
        'admin_add_event_select': 'Оберіть категорію для нової події:',
        'admin_category_select': 'Оберіть категорію для додавання до статистики:',
        'admin_add_confirm': '✅ Повідомлення додано до статистики як:  <b>{category}</b>',
        'admin_add_sent': '✅ Повідомлення надіслано користувачу {user_id}.',
        'admin_add_failed': '❌ Не вдалося надіслати повідомлення користувачу {user_id}.',
        'admin_event_added': '✅ Подія додана',
        'admin_event_cancelled': '❌ Додавання події скасовано.',
        'admin_event_summary': '<b>✅ Подія додана</b>',
        'admin_event_category': '<b>Категорія: </b> {category}',
        'admin_event_photos': '<b>Фото:</b> {count}',
        'admin_event_videos': '<b>Відео:</b> {count}',
        'admin_event_animations': '<b>Анімації:</b> {count}',
        'admin_event_documents':  '<b>Документи:</b> {count}',
        'admin_event_texts': '<b>Тексти:</b> {count}',
        'user_response_header': '💬 Відповідь адміністратора: ',
        'user_response_no_text': '💬 Відповідь адміністратора (без тексту).',
        'user_thanks': 'Дякуємо!  Ваше повідомлення отримано — наш адміністратор перевірить його.',
        'user_stat_added': 'ℹ️ Ваше повідомлення було додано до статистики як: <b>{category}</b>',
        'schedule_24_7': 'Ми працюємо цілодобово.  Звертайтесь у будь-який час.',
        'schedule_response':  'Наш бот приймає повідомлення 24/7. Ми відповідаємо якнайшвидше.',
        'separator':  '━━━━━━━━━━━━━━━━━━━━━━━━━━━━',
        'formatted_message': 'Повідомлення відформатовано для зручного перегляду.',
        'error_invalid_category': 'Невірний індекс категорії.',
        'error_db_save': '❌ Помилка при збереженні події в БД.',
    },
    'ru': {
        'main_menu_main': '✨ Главное',
        'main_menu_about': '📢 О нас',
        'main_menu_schedule': '🕰️ График работы',
        'main_menu_event': '📝 Сообщить о событии',
        'main_menu_stats': '📊 Статистика событий',
        'main_menu_ads': '📣 Реклама 🔔',
        'welcome_title': '✨ Добро пожаловать, {name}{vip}!',
        'welcome_subtitle': 'Вы попали в премиальный интерфейс нашего сервиса.',
        'welcome_available': 'Что доступно прямо сейчас:',
        'welcome_quick_report': '• 📝 Быстро сообщить о событии',
        'welcome_stats': '• 📊 Посмотреть статистику по категориям',
        'welcome_ads': '• 📣 Отправить рекламное сообщение',
        'welcome_footer': 'Нажмите одну из кнопок внизу, чтобы начать.',
        'cat_technogenic': '🏗️ Техногенные',
        'cat_natural': '🌪️ Природные',
        'cat_social': '👥 Социальные',
        'cat_military': '⚔️ Военные',
        'cat_search': '🕵️‍♂️ Поиск',
        'cat_other':  '📦 Прочее',
        'about_title': '<b>О нас</b>',
        'about_team': 'Мы — небольшая команда разработчиков и операторов, создающая инструменты для оперативного обмена информацией.',
        'about_features': '<b>Что вы можете сделать через бота:</b>',
        'about_feature_1': '• <b>Сообщить о событии</b> — отправьте фото/видео/документ и краткое описание; материалы будут переданы администратору.',
        'about_feature_2': '• <b>Реклама</b> — отправляйте рекламные материалы, мы их обработаем и свяжемся по поводу размещения.',
        'about_feature_3': '• <b>Статистика</b> — просмотр по категориям за 7 и 30 дней.',
        'about_privacy': '<b>Приватность</b>: личные данные передаются администратору только для обработки сообщения; мы их не продаём.',
        'about_contacts':  '<b>Контакты</b>:',
        'about_contact_admin': '• Напишите администратору через кнопку «Написать администратору».',
        'about_instagram': '• Instagram: <a href="https://www.instagram.com/creator. bot_official?igsh=cHg1aDRqNXdrb210">@creator. bot_official</a>',
        'about_schedule': '<b>Режим работы</b>: ответы по мере возможности, срочные вопросы обрабатываются в первую очередь.',
        'event_instructions': 'Отправляйте все необходимые фото, видео, документы и/или текст (несколько сообщений). Когда закончите — нажмите ✅ Отправить.',
        'event_thanks': '✅ Ваши данные отправлены. Спасибо! ',
        'event_cancelled':  '❌ Отменено.',
        'event_added': 'Добавлено в пакет. Продолжайте отправлять или нажмите ✅ Отправить.',
        'event_no_media': 'Нет медиа для отправки.',
        'stats_category': 'Категория',
        'stats_week': '7 дн',
        'stats_month':  '30 дн',
        'stats_unavailable': 'Статистика пока недоступна.',
        'media_continue': 'Добавлено в пакет. Продолжайте отправлять или нажмите ✅ Отправить.',
        'media_confirm': 'Добавлено в событие. Продолжайте отправлять материалы или нажмите ✅ Подтвердить / ❌ Отменить',
        'btn_send':  '✅ Отправить',
        'btn_cancel':  '❌ Отменить',
        'btn_confirm': '✅ Подтвердить',
        'btn_reject': '❌ Отменить',
        'btn_reply': '✉️ Ответить',
        'btn_add_stat': '➕ Добавить в статистику',
        'btn_write_admin': 'Написать администратору',
        'admin_new_event': '📩 Новое событие',
        'admin_new_ad': '📣 Рекламное сообщение',
        'admin_new_message': '📩 Новое сообщение',
        'admin_profile': 'Профиль',
        'admin_id': 'ID',
        'admin_phone': 'Телефон',
        'admin_location': 'Локация',
        'admin_category': 'Категория',
        'admin_message_id':  'Message ID',
        'admin_date': 'Дата',
        'admin_text': 'Текст / Описание',
        'admin_reply_text': '✍️ Введите ответ для пользователя {user_id} (любой текст или файл):',
        'admin_add_event_select': 'Выберите категорию для нового события:',
        'admin_category_select': 'Выберите категорию для добавления в статистику:',
        'admin_add_confirm': '✅ Сообщение добавлено в статистику как: <b>{category}</b>',
        'admin_add_sent': '✅ Сообщение отправлено пользователю {user_id}.',
        'admin_add_failed': '❌ Не удалось отправить сообщение пользователю {user_id}.',
        'admin_event_added': '✅ События добавлено',
        'admin_event_cancelled': '❌ Добавление события отменено.',
        'admin_event_summary': '<b>✅ Событие добавлено</b>',
        'admin_event_category': '<b>Категория:</b> {category}',
        'admin_event_photos':  '<b>Фото:</b> {count}',
        'admin_event_videos': '<b>Видео:</b> {count}',
        'admin_event_animations': '<b>Анимации:</b> {count}',
        'admin_event_documents': '<b>Документы:</b> {count}',
        'admin_event_texts': '<b>Тексты:</b> {count}',
        'user_response_header': '💬 Ответ администратора:',
        'user_response_no_text': '💬 Ответ администратора (без текста).',
        'user_thanks': 'Спасибо!  Ваше сообщение получено — наш администратор проверит его.',
        'user_stat_added': 'ℹ️ Ваше сообщение было добавлено в статистику как: <b>{category}</b>',
        'schedule_24_7': 'Мы работаем круглосуточно. Обращайтесь в любое время.',
        'schedule_response': 'Наш бот принимает сообщения 24/7. Мы отвечаем как можно быстрее.',
        'separator': '━━━━━━━━━━━━━━━━━━━━━━━━━━━━',
        'formatted_message': 'Сообщение отформатировано для удобного просмотра.',
        'error_invalid_category': 'Неверный индекс категории.',
        'error_db_save': '❌ Ошибка при сохранении события в БД.',
    },
    'en': {
        'main_menu_main': '✨ Main',
        'main_menu_about': '📢 About Us',
        'main_menu_schedule': '🕰️ Schedule',
        'main_menu_event': '📝 Report Event',
        'main_menu_stats': '📊 Event Statistics',
        'main_menu_ads': '📣 Advertising 🔔',
        'welcome_title': '✨ Welcome, {name}{vip}!',
        'welcome_subtitle': 'You have entered the premium interface of our service.',
        'welcome_available':  'What is available right now:',
        'welcome_quick_report': '• 📝 Quickly report an event',
        'welcome_stats': '• 📊 View statistics by category',
        'welcome_ads': '• 📣 Send advertising message',
        'welcome_footer':  'Click one of the buttons below to get started.',
        'cat_technogenic': '🏗️ Technogenic',
        'cat_natural': '🌪️ Natural',
        'cat_social': '👥 Social',
        'cat_military': '⚔️ Military',
        'cat_search': '🕵️‍♂️ Search',
        'cat_other': '📦 Other',
        'about_title': '<b>About Us</b>',
        'about_team': 'We are a small team of developers and operators creating tools for rapid information exchange.',
        'about_features': '<b>What you can do through the bot:</b>',
        'about_feature_1':  '• <b>Report Event</b> — send photo/video/document and brief description; materials will be sent to the administrator.',
        'about_feature_2': '• <b>Advertising</b> — send advertising materials, we will process them and contact you about placement.',
        'about_feature_3': '• <b>Statistics</b> — view statistics by categories for 7 and 30 days.',
        'about_privacy':  '<b>Privacy</b>: personal data is sent to the administrator only to process your message; we do not sell it.',
        'about_contacts':  '<b>Contacts</b>:',
        'about_contact_admin': '• Write to the administrator using the "Write to Administrator" button.',
        'about_instagram': '• Instagram: <a href="https://www.instagram.com/creator.bot_official? igsh=cHg1aDRqNXdrb210">@creator.bot_official</a>',
        'about_schedule': '<b>Working hours</b>: responses as possible, urgent questions are handled first.',
        'event_instructions': 'Send all necessary photos, videos, documents and/or text (multiple messages). When done — click ✅ Send.',
        'event_thanks': '✅ Your data has been sent. Thank you!',
        'event_cancelled': '❌ Cancelled.',
        'event_added': 'Added to package. Continue sending or click ✅ Send.',
        'event_no_media': 'No media to send.',
        'stats_category': 'Category',
        'stats_week': '7 days',
        'stats_month':  '30 days',
        'stats_unavailable': 'Statistics are not available right now.',
        'media_continue': 'Added to package. Continue sending or click ✅ Send.',
        'media_confirm':  'Added to event. Continue sending materials or click ✅ Confirm / ❌ Cancel',
        'btn_send': '✅ Send',
        'btn_cancel': '❌ Cancel',
        'btn_confirm': '✅ Confirm',
        'btn_reject': '❌ Cancel',
        'btn_reply': '✉️ Reply',
        'btn_add_stat': '➕ Add to Statistics',
        'btn_write_admin': 'Write to Administrator',
        'admin_new_event': '📩 New Event',
        'admin_new_ad': '📣 Advertising Message',
        'admin_new_message': '📩 New Message',
        'admin_profile':  'Profile',
        'admin_id': 'ID',
        'admin_phone': 'Phone',
        'admin_location': 'Location',
        'admin_category': 'Category',
        'admin_message_id': 'Message ID',
        'admin_date': 'Date',
        'admin_text':  'Text / Description',
        'admin_reply_text': '✍️ Enter reply for user {user_id} (any text or file):',
        'admin_add_event_select': 'Select category for new event:',
        'admin_category_select': 'Select category to add to statistics:',
        'admin_add_confirm': '✅ Message added to statistics as: <b>{category}</b>',
        'admin_add_sent': '✅ Message sent to user {user_id}.',
        'admin_add_failed': '❌ Failed to send message to user {user_id}.',
        'admin_event_added': '✅ Event Added',
        'admin_event_cancelled': '❌ Event addition cancelled.',
        'admin_event_summary': '<b>✅ Event Added</b>',
        'admin_event_category': '<b>Category:</b> {category}',
        'admin_event_photos': '<b>Photos:</b> {count}',
        'admin_event_videos': '<b>Videos:</b> {count}',
        'admin_event_animations': '<b>Animations:</b> {count}',
        'admin_event_documents': '<b>Documents:</b> {count}',
        'admin_event_texts': '<b>Texts: </b> {count}',
        'user_response_header': '💬 Administrator Reply:',
        'user_response_no_text': '💬 Administrator Reply (no text).',
        'user_thanks': 'Thank you! Your message has been received — our administrator will check it.',
        'user_stat_added': 'ℹ️ Your message has been added to statistics as: <b>{category}</b>',
        'schedule_24_7': 'We work 24/7. Contact us anytime.',
        'schedule_response': 'Our bot accepts messages 24/7. We respond as quickly as possible.',
        'separator':  '━━━━━━━━━━━━━━━━━━━━━━━━━━━━',
        'formatted_message': 'Message formatted for convenient viewing.',
        'error_invalid_category': 'Invalid category index.',
        'error_db_save': '❌ Error saving event to database.',
    }
}

DEFAULT_LANGUAGE = 'uk'
user_languages = {}

def get_user_language(user_id:  int) -> str:
    return user_languages.get(user_id, DEFAULT_LANGUAGE)

def set_user_language(user_id: int, language: str):
    if language in TRANSLATIONS:
        user_languages[user_id] = language

def t(key: str, language: str = None, **kwargs) -> str:
    """Получить перевод с поддержкой параметров"""
    if language is None:
        language = DEFAULT_LANGUAGE
    if language not in TRANSLATIONS:
        language = DEFAULT_LANGUAGE
    translation = TRANSLATIONS. get(language, {}).get(key, f"[{key}]")
    try:
        if kwargs:
            return translation.format(**kwargs)
        return translation
    except KeyError as e:
        return f"[Missing key: {e}]"

# ====== ОСНОВНАЯ ЛОГИКА БОТА ======

NOTIFY_USER_ON_ADD_STAT = True

def MainProtokol(s, ts='Запис'):
    dt = time.strftime('%d.%m.%Y %H:%M: ') + '00'
    try:
        with open('log.txt', 'a', encoding='utf-8') as f:
            f.write(f"{dt};{ts};{s}\n")
    except Exception as e:
        print("Ошибка записи в лог:", e)

def cool_error_handler(exc, context="", send_to_telegram=False):
    exc_type = type(exc).__name__
    tb_str = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    readable_msg = (
        "\n" + "=" * 40 + "\n"
        f"[ERROR] {exc_type}\n"
        f"Context: {context}\n"
        f"Time: {ts}\n"
        "Traceback:\n"
        f"{tb_str}"
        + "=" * 40 + "\n"
    )
    try:
        with open('critical_errors.log', 'a', encoding='utf-8') as f:
            f.write(readable_msg)
    except Exception as write_err:
        print("Не удалось записать в 'critical_errors.log':", write_err)
    try:
        MainProtokol(f"{exc_type}: {str(exc)}", ts='ERROR')
    except Exception as log_err:
        print("MainProtokol вернул ошибку:", log_err)
    print(readable_msg)
    if send_to_telegram:
        try:
            admin_id = int(os.getenv("ADMIN_ID", "0"))
            token = os.getenv("API_TOKEN")
            if admin_id and token:
                try:
                    r = requests.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        data={
                            "chat_id": admin_id,
                            "text": f"⚠️ Критична помилка!\nТип:  {exc_type}\nКонтекст: {context}\n\n{str(exc)}",
                            "disable_web_page_preview": True
                        },
                        timeout=5
                    )
                    if not r.ok:
                        MainProtokol(f"Telegram notify failed: {r.status_code} {r.text}", ts='WARN')
                except Exception as telegram_err:
                    print("Не удалось отправить уведомление в Telegram:", telegram_err)
        except Exception as env_err:
            print("Ошибка при подготовке уведомления в Telegram:", env_err)

def time_debugger():
    while True:
        print("[DEBUG]", time.strftime('%Y-%m-%d %H:%M:%S'))
        time.sleep(300)

def get_main_menu(language:  str = 'uk'):
    return [
        t('main_menu_main', language),
        t('main_menu_about', language),
        t('main_menu_schedule', language),
        t('main_menu_event', language),
        t('main_menu_stats', language),
        t('main_menu_ads', language),
    ]

def get_admin_subcategories(language: str = 'uk'):
    return [
        t('cat_technogenic', language),
        t('cat_natural', language),
        t('cat_social', language),
        t('cat_military', language),
        t('cat_search', language),
        t('cat_other', language),
    ]

def get_reply_buttons(language: str = 'uk'):
    menu = get_main_menu(language)
    return {
        "keyboard": [
            [{"text": menu[5]}],
            [{"text": menu[1]}, {"text": menu[2]}],
            [{"text": menu[3]}, {"text": menu[4]}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

def build_about_company_detailed(language: str = 'uk') -> str:
    sep = t('separator', language)
    parts = [
        f"<pre>{sep}</pre>",
        f"<b>{t('about_title', language)}</b>",
        "",
        f"{t('about_team', language)}",
        "",
        f"<b>{t('about_features', language)}</b>",
        t('about_feature_1', language),
        t('about_feature_2', language),
        t('about_feature_3', language),
        "",
        f"{t('about_privacy', language)}",
        f"<b>{t('about_contacts', language)}</b>",
        t('about_contact_admin', language),
        t('about_instagram', language),
        "",
        f"{t('about_schedule', language)}",
        f"<pre>{sep}</pre>"
    ]
    return "\n".join(parts)

# Состояния
waiting_for_admin_message = set()
user_admin_category = {}
waiting_for_ad_message = set()
pending_mode = {}
pending_media = {}
waiting_for_admin = {}
admin_adding_event = {}
GLOBAL_LOCK = threading.Lock()

# БД
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL:
    db_url = DATABASE_URL
else: 
    default_sqlite = os.path.join(os.path.dirname(os.path.abspath(__file__)), "events.db")
    db_url = f"sqlite:///{default_sqlite}"

_engine:  Engine = None

def get_engine():
    global _engine
    if _engine is None:
        try:
            if not db_url: 
                raise ValueError("DATABASE_URL is empty")
            if db_url.startswith("sqlite:///"):
                _engine = create_engine(db_url, connect_args={"check_same_thread": False}, future=True)
                print(f"[DEBUG] Using SQLite DB URL: {db_url}")
            else:
                if '://' not in db_url:
                    raise ArgumentError(f"Invalid DB URL (missing scheme): {db_url}")
                _engine = create_engine(db_url, future=True)
                print(f"[DEBUG] Using DB URL: {db_url}")
        except ArgumentError as e: 
            cool_error_handler(e, "get_engine (ArgumentError)")
            MainProtokol(f"Invalid DATABASE_URL: {db_url}", ts='WARN')
            try:
                fallback_sqlite = os.path.join(os.path.dirname(os.path.abspath(__file__)), "events.db")
                fallback_url = f"sqlite:///{fallback_sqlite}"
                _engine = create_engine(fallback_url, connect_args={"check_same_thread": False}, future=True)
                print(f"[WARN] Fallback to SQLite at {fallback_sqlite} due to invalid DATABASE_URL.")
                MainProtokol("Fallback to SQLite due to invalid DATABASE_URL", ts='WARN')
            except Exception as e2:
                cool_error_handler(e2, "get_engine (fallback sqlite)")
                raise
        except Exception as e: 
            cool_error_handler(e, "get_engine")
            MainProtokol(f"get_engine general exception: {str(e)}", ts='ERROR')
            try:
                fallback_sqlite = os.path.join(os. path.dirname(os.path. abspath(__file__)), "events.db")
                fallback_url = f"sqlite:///{fallback_sqlite}"
                _engine = create_engine(fallback_url, connect_args={"check_same_thread": False}, future=True)
                print(f"[WARN] Fallback to SQLite at {fallback_sqlite} due to engine creation error.")
                MainProtokol("Fallback to SQLite due to engine creation error", ts='WARN')
            except Exception as e2:
                cool_error_handler(e2, "get_engine (fallback sqlite after general exception)")
                raise
    return _engine

def init_db():
    try:
        engine = get_engine()
        create_sql = """
        CREATE TABLE IF NOT EXISTS events (
            id SERIAL PRIMARY KEY,
            category TEXT NOT NULL,
            dt TIMESTAMP NOT NULL
        );
        """
        if engine.dialect.name == "sqlite":
            create_sql = """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                dt TEXT NOT NULL
            );
            """
        with engine.begin() as conn:
            conn. execute(text(create_sql))
    except Exception as e:
        cool_error_handler(e, "init_db")

def save_event(category):
    try:
        engine = get_engine()
        now = datetime.datetime.utcnow()
        if engine.dialect.name == "sqlite": 
            dt_val = now.isoformat()
            insert_sql = "INSERT INTO events (category, dt) VALUES (:cat, :dt)"
            with engine.begin() as conn:
                conn.execute(text(insert_sql), {"cat": category, "dt": dt_val})
        else:
            insert_sql = "INSERT INTO events (category, dt) VALUES (:cat, :dt)"
            with engine.begin() as conn:
                conn.execute(text(insert_sql), {"cat": category, "dt": now})
    except Exception as e: 
        cool_error_handler(e, "save_event")

def get_stats(language: str = 'uk'):
    categories = get_admin_subcategories(language)
    res = {cat: {'week': 0, 'month':  0} for cat in categories}
    try:
        engine = get_engine()
        now = datetime.datetime.utcnow()
        week_threshold = now - datetime.timedelta(days=7)
        month_threshold = now - datetime.timedelta(days=30)
        with engine.connect() as conn:
            if engine.dialect.name == "sqlite":
                week_ts = week_threshold.isoformat()
                month_ts = month_threshold.isoformat()
                q_week = text("SELECT category, COUNT(*) as cnt FROM events WHERE dt >= :week GROUP BY category")
                q_month = text("SELECT category, COUNT(*) as cnt FROM events WHERE dt >= :month GROUP BY category")
                wk = conn.execute(q_week, {"week": week_ts}).all()
                mo = conn.execute(q_month, {"month": month_ts}).all()
            else:
                q_week = text("SELECT category, COUNT(*) as cnt FROM events WHERE dt >= : week GROUP BY category")
                q_month = text("SELECT category, COUNT(*) as cnt FROM events WHERE dt >= :month GROUP BY category")
                wk = conn.execute(q_week, {"week":  week_threshold}).all()
                mo = conn. execute(q_month, {"month": month_threshold}).all()
            for row in wk:
                cat = row[0]
                cnt = int(row[1])
                if cat in res:
                    res[cat]['week'] = cnt
            for row in mo: 
                cat = row[0]
                cnt = int(row[1])
                if cat in res:
                    res[cat]['month'] = cnt
        return res
    except Exception as e:
        cool_error_handler(e, "get_stats")
        MainProtokol(str(e), 'get_stats_exception')
        return {cat: {'week': 0, 'month': 0} for cat in categories}

def clear_stats_if_month_passed():
    try:
        engine = get_engine()
        now = datetime.datetime.utcnow()
        month_threshold = now - datetime.timedelta(days=30)
        with engine.begin() as conn:
            if engine.dialect.name == "sqlite": 
                month_ts = month_threshold.isoformat()
                conn.execute(text("DELETE FROM events WHERE dt < :month"), {"month": month_ts})
            else:
                conn.execute(text("DELETE FROM events WHERE dt < :month"), {"month": month_threshold})
    except Exception as e:
        cool_error_handler(e, "clear_stats_if_month_passed")

def stats_autoclear_daemon():
    while True:
        try:
            clear_stats_if_month_passed()
        except Exception as e:
            cool_error_handler(e, "stats_autoclear_daemon")
        time.sleep(3600)

init_db()

TOKEN = os.getenv("API_TOKEN")
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except Exception: 
    ADMIN_ID = 0

WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "").strip()
if TOKEN and WEBHOOK_HOST:
    WEBHOOK_URL = f"https://{WEBHOOK_HOST}/webhook/{TOKEN}"
else:
    WEBHOOK_URL = ""

def set_webhook():
    if not TOKEN: 
        print("[WARN] TOKEN is not set, webhook not initialized.")
        return
    if not WEBHOOK_URL:
        print("[INFO] WEBHOOK_HOST not set; skip setting webhook.")
        return
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/setWebhook",
            params={"url":  WEBHOOK_URL},
            timeout=5
        )
        if r.ok:
            print("Webhook успешно установлен!")
        else:
            print("Ошибка при установке webhook:", r.status_code, r. text)
            MainProtokol(f"setWebhook failed: {r. status_code} {r.text}", ts='WARN')
    except Exception as e:
        cool_error_handler(e, context="set_webhook")

set_webhook()

def send_chat_action(chat_id, action='typing'):
    if not TOKEN:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{TOKEN}/sendChatAction',
            data={'chat_id': chat_id, 'action': action},
            timeout=3
        )
    except Exception: 
        pass

def build_welcome_message(user:  dict, language: str = 'uk') -> str:
    try:
        first = (user. get('first_name') or "").strip()
        last = (user.get('last_name') or "").strip()
        display = (first + (" " + last if last else "")).strip() or "Друже"
        is_premium = user.get('is_premium', False)
        vip_badge = " ✨" if is_premium else ""
        name_html = escape(display)
        
        sep = t('separator', language)
        msg = (
            f"<pre>{sep}</pre>\n"
            f"<b>{t('welcome_title', language, name=name_html, vip=vip_badge)}</b>\n\n"
            f"<i>{t('welcome_subtitle', language)}</i>\n\n"
            f"<b>{t('welcome_available', language)}</b>\n"
            f"{t('welcome_quick_report', language)}\n"
            f"{t('welcome_stats', language)}\n"
            f"{t('welcome_ads', language)}\n\n"
            f"<i>{t('welcome_footer', language)}</i>\n"
            f"<pre>{sep}</pre>"
        )
        return msg
    except Exception as e:
        cool_error_handler(e, "build_welcome_message")
        return t('welcome_footer', language)

def send_message(chat_id, text, reply_markup=None, parse_mode=None, timeout=8):
    if not TOKEN:
        print("[WARN] Попытка отправки сообщения без TOKEN")
        return None
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': text
    }
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    if parse_mode:
        payload['parse_mode'] = parse_mode
    try:
        resp = requests.post(url, data=payload, timeout=timeout)
        if not resp.ok:
            MainProtokol(resp.text, 'Помилка надсилання')
        return resp
    except Exception as e:
        cool_error_handler(e, context="send_message")
        MainProtokol(str(e), 'Помилка мережі')
        return None

def _get_reply_markup_for_admin(user_id: int, orig_chat_id: int = None, orig_msg_id: int = None, language: str = 'uk'):
    kb = {
        "inline_keyboard": [
            [{"text": t('btn_reply', language), "callback_data": f"reply_{user_id}"}]
        ]
    }
    if orig_chat_id is not None and orig_msg_id is not None:
        kb["inline_keyboard"][0]. append({"text": t('btn_add_stat', language), "callback_data": f"addstat_{orig_chat_id}_{orig_msg_id}"})
    return kb

def build_admin_info(message:  dict, category: str = None, msg_type: str = None, language: str = 'uk') -> str:
    try:
        final_type = msg_type
        if final_type is None:
            final_type = 'event' if category else 'message'

        if final_type == 'event': 
            title = t('admin_new_event', language)
        elif final_type == 'ad':
            title = t('admin_new_ad', language)
        else:
            title = t('admin_new_message', language)
        
        sep = t('separator', language)

        user = message.get('from', {}) or {}
        first = (user.get('first_name') or "").strip()
        last = (user.get('last_name') or "").strip()
        username = user.get('username')
        user_id = user.get('id')
        is_premium = user.get('is_premium', None)

        display_name = (first + (" " + last if last else "")).strip() or t('admin_profile', language)
        display_html = escape(display_name)

        if username:
            profile_url = f"https://t.me/{username}"
            profile_label = f"@{escape(username)}"
            profile_html = f"<a href=\"{profile_url}\">{profile_label}</a>"
        else:
            profile_url = f"tg://user?id={user_id}"
            profile_label = t('btn_write_admin', language)
            profile_html = f"<a href=\"{profile_url}\">{escape(profile_label)}</a>"

        contact = message.get('contact')
        contact_html = ""
        if isinstance(contact, dict):
            phone = contact.get('phone_number')
            contact_name = (contact.get('first_name') or "") + ((" " + contact.get('last_name')) if contact.get('last_name') else "")
            contact_parts = []
            if contact_name:
                contact_parts. append(escape(contact_name. strip()))
            if phone: 
                contact_parts.append(escape(phone))
            if contact_parts:
                contact_html = ", ".join(contact_parts)

        location = message.get('location')
        location_html = ""
        if isinstance(location, dict):
            lat = location.get('latitude')
            lon = location.get('longitude')
            if lat is not None and lon is not None: 
                location_html = f"{lat}, {lon}"

        msg_id = message.get('message_id', '-')
        msg_date = message.get('date')
        try:
            date_str = datetime.datetime.utcfromtimestamp(int(msg_date)).strftime('%Y-%m-%d %H:%M:%S UTC') if msg_date else '-'
        except Exception:
            date_str = str(msg_date or '-')

        text = message.get('text') or message.get('caption') or ''
        category_html = escape(category) if category else None

        parts = []
        parts.append(f"<pre>{sep}</pre>")
        parts.append(f"<b>{title}</b>")
        parts.append("")

        name_line = f"<b>{display_html}</b>"
        if is_premium:
            name_line += " ✨"
        parts.append(name_line)
        parts.append(f"<b>{t('admin_profile', language)}:</b> {profile_html}")
        parts.append(f"<b>{t('admin_id', language)}:</b> {escape(str(user_id)) if user_id is not None else '-'}")

        if contact_html:
            parts.append(f"<b>{t('admin_phone', language)}:</b> {contact_html}")
        if location_html:
            parts.append(f"<b>{t('admin_location', language)}:</b> {escape(location_html)}")

        if category_html:
            parts. append(f"<b>{t('admin_category', language)}:</b> {category_html}")

        parts.append("")
        parts.append(f"<b>{t('admin_message_id', language)}:</b> {escape(str(msg_id))}")
        parts.append(f"<b>{t('admin_date', language)}:</b> {escape(str(date_str))}")

        if text:
            display_text = text if len(text) <= 2000 else text[:1997] + "..."
            parts. append("")
            parts.append(f"<b>{t('admin_text', language)}:</b>")
            parts.append("<pre>{}</pre>".format(escape(display_text)))

        parts.append("")
        parts.append(f"<i>{t('formatted_message', language)}</i>")
        parts.append(f"<pre>{sep}</pre>")

        return "\n". join(parts)
    except Exception as e:
        cool_error_handler(e, "build_admin_info")
        return t('admin_new_message', language)

def _post_request(url, data=None, files=None, timeout=10):
    try:
        r = requests.post(url, data=data, files=files, timeout=timeout)
        if not r.ok:
            MainProtokol(f"Request failed: {url} -> {r.status_code} {r.text}", ts='WARN')
        return r
    except Exception as e:
        MainProtokol(f"Network error for {url}: {str(e)}", ts='ERROR')
        return None

def forward_admin_message_to_user(user_id: int, admin_msg:  dict, language: str = 'uk'):
    try:
        if not user_id:
            return False
        caption = admin_msg.get('caption') or admin_msg.get('text') or ""
        safe_caption = escape(caption) if caption else None

        if 'photo' in admin_msg:
            file_id = admin_msg['photo'][-1]. get('file_id')
            url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
            payload = {"chat_id": user_id, "photo": file_id}
            if safe_caption:
                payload["caption"] = f"{t('user_response_header', language)}\n<pre>{safe_caption}</pre>"
                payload["parse_mode"] = "HTML"
            else:
                payload["caption"] = t('user_response_no_text', language)
            _post_request(url, data=payload)
            return True

        if 'video' in admin_msg:
            file_id = admin_msg['video'].get('file_id')
            url = f"https://api.telegram.org/bot{TOKEN}/sendVideo"
            payload = {"chat_id": user_id, "video": file_id}
            if safe_caption: 
                payload["caption"] = f"{t('user_response_header', language)}\n<pre>{safe_caption}</pre>"
                payload["parse_mode"] = "HTML"
            else:
                payload["caption"] = t('user_response_no_text', language)
            _post_request(url, data=payload)
            return True

        if 'document' in admin_msg:
            file_id = admin_msg['document'].get('file_id')
            url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
            payload = {"chat_id": user_id, "document": file_id}
            if safe_caption: 
                payload["caption"] = f"{t('user_response_header', language)}\n<pre>{safe_caption}</pre>"
                payload["parse_mode"] = "HTML"
            _post_request(url, data=payload)
            return True

        if caption: 
            send_message(user_id, f"{t('user_response_header', language)}\n<pre>{escape(caption)}</pre>", parse_mode="HTML")
            return True

        send_message(user_id, t('user_response_no_text', language))
        return True
    except Exception as e:
        cool_error_handler(e, "forward_admin_message_to_user")
        return False

def send_media_collection_keyboard(chat_id, language: str = 'uk'):
    kb = {
        "keyboard": [
            [{"text":  t('btn_send', language)}],
            [{"text": t('btn_cancel', language)}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }
    send_message(
        chat_id,
        t('event_instructions', language),
        reply_markup=kb
    )

def _collect_media_summary_and_payloads(msgs):
    media_items = []
    doc_msgs = []
    leftover_texts = []

    captions_for_media = []
    other_texts = []

    for m in msgs:
        txt = m.get('text') or m.get('caption') or ''
        if 'photo' in m:
            try:
                file_id = m['photo'][-1]['file_id']
            except Exception:
                file_id = None
            if file_id:
                media_items.append({"type": "photo", "media":  file_id, "orig_text": txt})
                if txt:
                    captions_for_media.append(txt)
        elif 'video' in m: 
            file_id = m['video'].get('file_id')
            if file_id:
                media_items.append({"type": "video", "media": file_id, "orig_text": txt})
                if txt:
                    captions_for_media.append(txt)
        elif 'document' in m:
            doc_msgs.append({"file_id": m['document'].get('file_id'), "file_name": m['document'].get('file_name'), "text": txt})
        else:
            if txt:
                other_texts. append(txt)

    combined_caption = None
    if media_items:
        if captions_for_media: 
            joined = "\n\n".join(captions_for_media)
            if len(joined) > 1000:
                joined = joined[:997] + "..."
            combined_caption = joined
        for idx, mi in enumerate(media_items):
            if idx == 0 and combined_caption:
                mi['caption'] = combined_caption
            else:
                mi['caption'] = ""
    leftover_texts = other_texts
    return media_items, doc_msgs, leftover_texts

def send_compiled_media_to_admin(chat_id, language: str = 'uk'):
    with GLOBAL_LOCK:
        msgs = list(pending_media.get(chat_id, []))
    if not msgs:
        send_message(chat_id, t('event_no_media', language))
        return
    
    m_category = None
    with GLOBAL_LOCK:
        if pending_mode.get(chat_id) == "event":
            m_category = user_admin_category.get(chat_id, t('cat_other', language))
        current_mode = pending_mode.get(chat_id)
    
    if m_category:
        try:
            save_event(m_category)
        except Exception as e:
            cool_error_handler(e, "save_event in send_compiled_media_to_admin")

    media_items, doc_msgs, leftover_texts = _collect_media_summary_and_payloads(msgs)
    orig_chat_id = msgs[0]['chat']['id']
    orig_msg_id = msgs[0]. get('message_id')
    orig_user_id = msgs[0].get('from', {}).get('id')

    if current_mode == "event":
        admin_msg_type = "event"
    elif current_mode == "ad": 
        admin_msg_type = "ad"
    else: 
        admin_msg_type = "message"

    admin_info = build_admin_info(msgs[0], category=m_category, msg_type=admin_msg_type, language=language)
    reply_markup = _get_reply_markup_for_admin(orig_user_id, orig_chat_id, orig_msg_id, language=language)
    send_message(ADMIN_ID, admin_info, reply_markup=reply_markup, parse_mode="HTML")

    try:
        if media_items:
            if len(media_items) > 1:
                sendmedia = []
                for mi in media_items:
                    obj = {"type": mi["type"], "media": mi["media"]}
                    if mi.get("caption"):
                        obj["caption"] = mi["caption"]
                        obj["parse_mode"] = "HTML"
                    sendmedia. append(obj)
                url = f"https://api.telegram.org/bot{TOKEN}/sendMediaGroup"
                payload = {"chat_id":  ADMIN_ID, "media":  json.dumps(sendmedia)}
                try:
                    r = requests.post(url, data=payload, timeout=10)
                    if not r. ok:
                        MainProtokol(f"sendMediaGroup failed: {r.status_code} {r.text}", "MediaGroupFail")
                except Exception as e: 
                    MainProtokol(f"sendMediaGroup error: {str(e)}", "MediaGroupFail")
            else:
                mi = media_items[0]
                if mi["type"] == "photo":
                    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
                    payload = {"chat_id": ADMIN_ID, "photo": mi["media"]}
                    if mi.get("caption"):
                        payload["caption"] = mi["caption"]
                        payload["parse_mode"] = "HTML"
                    try:
                        r = requests. post(url, data=payload, timeout=10)
                        if not r.ok:
                            MainProtokol(f"sendPhoto failed: {r.status_code} {r.text}", "PhotoFail")
                    except Exception as e:
                        MainProtokol(f"sendPhoto error: {str(e)}", "PhotoFail")
    except Exception as e:
        cool_error_handler(e, "send_compiled_media_to_admin:  media send")

    for d in doc_msgs:
        try:
            payload = {
                "chat_id":  ADMIN_ID,
                "document": d["file_id"]
            }
            if d. get("text"):
                payload["caption"] = d["text"] if len(d["text"]) <= 1000 else d["text"][: 997] + "..."
            r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendDocument", data=payload, timeout=10)
        except Exception as e:
            MainProtokol(f"sendDocument error: {str(e)}", "DocumentFail")

    with GLOBAL_LOCK:
        pending_media.pop(chat_id, None)
        pending_mode.pop(chat_id, None)

def format_stats_message(stats: dict, language: str = 'uk') -> str:
    categories = get_admin_subcategories(language)
    max_cat_len = max(len(escape(c)) for c in categories) + 1
    col1 = f"{t('stats_category', language)}". ljust(max_cat_len)
    header = f"{col1}  {t('stats_week', language):>6}  {t('stats_month', language):>6}"
    lines = [header, "-" * (max_cat_len + 16)]
    for cat in categories:
        name = escape(cat)
        week = stats.get(cat, {}).get('week', 0)
        month = stats.get(cat, {}).get('month', 0)
        lines.append(f"{name. ljust(max_cat_len)}  {str(week):>6}  {str(month):>6}")
    content = "\n".join(lines)
    sep = t('separator', language)
    return f"<pre>{sep}\n{content}\n{sep}</pre>"

app = Flask(__name__)

@app.errorhandler(Exception)
def flask_global_error_handler(e):
    cool_error_handler(e, context="Flask global error handler")
    return "Internal server error.", 500

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    global pending_media, pending_mode, admin_adding_event
    try:
        data_raw = request.get_data(as_text=True)
        update = json.loads(data_raw)

        if 'callback_query' in update:
            call = update['callback_query']
            chat_id = call['from']['id']
            data = call. get('data', '')
            user_lang = get_user_language(chat_id)

            if data. startswith("reply_") and chat_id == ADMIN_ID: 
                try:
                    user_id = int(data.split("_", 1)[1])
                    with GLOBAL_LOCK:
                        waiting_for_admin[ADMIN_ID] = user_id
                    send_message(
                        ADMIN_ID,
                        t('admin_reply_text', user_lang, user_id=user_id)
                    )
                except Exception as e:
                    cool_error_handler(e, context="webhook:  callback_query reply_")

            elif data.startswith("addstat_") and chat_id == ADMIN_ID:
                try:
                    parts = data.split("_", 2)
                    if len(parts) == 3:
                        orig_chat_id = int(parts[1])
                        orig_msg_id = int(parts[2])
                        categories = get_admin_subcategories(user_lang)
                        kb = {"inline_keyboard": []}
                        row = []
                        for idx, cat in enumerate(categories):
                            row.append({"text": cat, "callback_data": f"confirm_addstat|{orig_chat_id}|{orig_msg_id}|{idx}"})
                            if len(row) == 2:
                                kb["inline_keyboard"]. append(row)
                                row = []
                        if row: 
                            kb["inline_keyboard"].append(row)
                        send_message(ADMIN_ID, t('admin_category_select', user_lang), reply_markup=kb)
                except Exception as e:
                    cool_error_handler(e, context="webhook: addstat callback")

            elif data.startswith("confirm_addstat|") and chat_id == ADMIN_ID:
                try: 
                    parts = data.split("|")
                    if len(parts) == 4:
                        orig_chat_id = int(parts[1])
                        orig_msg_id = int(parts[2])
                        cat_idx = int(parts[3])
                        categories = get_admin_subcategories(user_lang)
                        if 0 <= cat_idx < len(categories):
                            category = categories[cat_idx]
                            save_event(category)
                            send_message(ADMIN_ID, t('admin_add_confirm', user_lang, category=escape(category)), parse_mode="HTML", reply_markup=get_reply_buttons(user_lang))
                            if NOTIFY_USER_ON_ADD_STAT:
                                try:
                                    send_message(orig_chat_id, t('user_stat_added', user_lang, category=escape(category)), parse_mode="HTML")
                
