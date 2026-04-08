import os
import logging
import requests
import json
import re
from flask import Flask, request, jsonify
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from collections import defaultdict

# ========== НАСТРОЙКИ ЛОГИРОВАНИЯ ==========
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ========== КОНТАКТЫ ПСИХОЛОГА ==========
PSYCHOLOGIST = "Школьный психолог"
HELP_LINE = "8-800-2000-122"

# ========== ДАННЫЕ ДЛЯ YANDEX GPT ==========
FOLDER_ID = os.environ.get('FOLDER_ID')
API_KEY = os.environ.get('API_KEY')
TOKEN = os.environ.get('BOT_TOKEN')

if not TOKEN:
    raise ValueError("❌ Ошибка: нет токена! Добавь BOT_TOKEN в переменные окружения")
if not FOLDER_ID:
    raise ValueError("❌ Ошибка: нет FOLDER_ID! Добавь FOLDER_ID в переменные окружения")
if not API_KEY:
    raise ValueError("❌ Ошибка: нет API_KEY! Добавь API_KEY в переменные окружения")

# ========== СИСТЕМА ПАМЯТИ ==========
user_history = defaultdict(list)
MAX_HISTORY = 10

# ========== НАСТРОЙКИ ПОЛЬЗОВАТЕЛЕЙ ==========
user_preferences = {}

PRONOUNS_MAP = {
    "она": {"user": "она", "user_obj": "её", "user_pos": "её"},
    "он": {"user": "он", "user_obj": "его", "user_pos": "его"},
    "оно": {"user": "оно", "user_obj": "его", "user_pos": "его"}
}


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def add_to_history(chat_id, message, is_user=True):
    role = "user" if is_user else "assistant"
    user_history[chat_id].append({"role": role, "text": message})
    if len(user_history[chat_id]) > MAX_HISTORY:
        user_history[chat_id] = user_history[chat_id][-MAX_HISTORY:]


def get_history_for_prompt(chat_id):
    history = user_history.get(chat_id, [])
    if not history:
        return ""

    history_text = "\n\nИстория разговора:\n"
    for msg in history[-6:]:
        role = "Пользователь" if msg["role"] == "user" else "Хэлпер"
        history_text += f"{role}: {msg['text']}\n"
    return history_text


# ========== КЛЮЧЕВЫЕ СЛОВА ДЛЯ КРИТИЧЕСКИХ СИТУАЦИЙ ==========
CRITICAL_KEYWORDS = [
    "суицид", "убью себя", "покончу с собой", "хочу умереть",
    "лучше бы я умер", "не хочу жить", "самоубийство", "убьюсь",
    "повешусь", "вскрою вены", "спрыгну", "таблетки выпью",
    "жизнь не имеет смысла", "не вижу смысла жить"
]

SERIOUS_KEYWORDS = [
    "депрессия", "ненавижу себя", "никому не нужен", "одиночество",
    "никто не понимает", "постоянно плачу", "безнадежно",
    "плохо с каждым днем", "не вижу выхода", "безысходность"
]


# ========== ФУНКЦИИ ОЧИСТКИ И ОБРАБОТКИ ==========
def clean_response(text):
    if not text:
        return text

    text = text.strip()

    quote_pairs = [
        ('"', '"'), ('«', '»'), ('„', '“'), ('“', '”'),
        ('"', '"'), ("'", "'"), ('`', "'"), ('"', '"')
    ]

    for start_quote, end_quote in quote_pairs:
        if text.startswith(start_quote) and text.endswith(end_quote):
            text = text[1:-1].strip()
            break

    if text and text[0] in ['"', "'", '«', '„', '“', '`']:
        text = text[1:]
    if text and text[-1] in ['"', "'", '»', '“', '”', '`']:
        text = text[:-1]

    if text.endswith('.') and not text.endswith('..'):
        text = text[:-1]

    text = re.sub(r',\s*([❤️💕💔🙏😭😔😅🫂😍☹️🫶])', r' \1', text)

    return text.strip()


def detect_crisis_level(user_message):
    message_lower = user_message.lower()

    for keyword in CRITICAL_KEYWORDS:
        if keyword in message_lower:
            return 2

    for keyword in SERIOUS_KEYWORDS:
        if keyword in message_lower:
            return 1

    return 0


# ========== ГЕНЕРАЦИЯ ПРЕДЛОЖЕНИЙ ДЛЯ /helpmessage ==========
def generate_message_suggestion(user_message, context_history=""):
    try:
        prompt = f"""Ты — Хэлпер. Пользователь хочет написать кому-то сообщение, но не знает как. 
Вот что он рассказал о ситуации: {user_message}
{context_history}

Напиши 2-3 варианта того, что он мог бы написать. Варианты должны быть:
- Короткими и естественными (1-2 предложения)
- Без давления
- Без эмодзи

Просто перечисли варианты через «•», без лишних слов."""

        url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Api-Key {API_KEY}"
        }

        data = {
            "modelUri": f"gpt://{FOLDER_ID}/yandexgpt-lite",
            "completionOptions": {
                "stream": False,
                "temperature": 0.9,
                "maxTokens": 300
            },
            "messages": [
                {"role": "system", "text": prompt},
                {"role": "user", "text": user_message}
            ]
        }

        response = requests.post(url, headers=headers, json=data)

        if response.status_code == 200:
            result = response.json()
            return result['result']['alternatives'][0]['message']['text']
        else:
            return None
    except Exception as e:
        print(f"Ошибка в generate_message_suggestion: {e}")
        return None


# ========== ОСНОВНАЯ ФУНКЦИЯ ДЛЯ YANDEX GPT ==========
def get_yandex_gpt_response(user_message, chat_id):
    try:
        crisis_level = detect_crisis_level(user_message)
        history_context = get_history_for_prompt(chat_id)

        pref = user_preferences.get(chat_id, {})
        user_name = pref.get("name", "")
        user_pronouns = pref.get("pronouns", "")

        user_context = ""
        if user_name:
            user_context += f"Пользователя зовут {user_name}. "
        if user_pronouns:
            user_context += f"Обращайся к нему с местоимениями {user_pronouns}. "

        if crisis_level == 2:
            support_note = f"⚠️ КРИТИЧЕСКАЯ СИТУАЦИЯ! Обязательно мягко порекомендуй обратиться к специалисту: {PSYCHOLOGIST} или позвонить {HELP_LINE}. Прояви максимальное сочувствие и заботу."
        elif crisis_level == 1:
            support_note = f"⚠️ СЕРЬЁЗНАЯ СИТУАЦИЯ. Прояви особую теплоту и мягко порекомендуй обратиться к {PSYCHOLOGIST}."
        else:
            support_note = "Пользователь нуждается в поддержке."

        system_prompt = f"""Ты — Хэлпер, друг который всегда на связи, всегда поддержит. Пользователь может написать тебе в любое время и получить поддержку, либо просто поговорить если стало скучно.

ВАЖНО: ты не психолог и не заменишь его. В серьёзных ситуациях настаивай на том, чтобы пользователь обратился к психологу или позвонил на номер доверия.

{user_context}

ГЛАВНОЕ ПРАВИЛО: ОТВЕЧАЙ КОРОТКО! Максимум 4-5 предложений.

ТВОЯ ЗАДАЧА: поддержать человека, показать, что его чувства — это нормально.

ОБЯЗАТЕЛЬНО ИСПОЛЬЗУЙ ЭТИ ФРАЗЫ (выбирай подходящую по смыслу):

Поддержка чувств:
- «Плакать — это нормально»
- «Злиться — это нормально»
- «Бояться — это нормально»
- «Грустить — это нормально»
- «Ты имеешь право на свои чувства»
- «Ты имеешь право на своё мнение»
- «Ты имеешь право ошибаться»
- «Ты имеешь право сказать "нет"»
- «Ты не обязан(а) быть идеальным(ой)»
- «То, что ты чувствуешь — это важно»

Утешение:
- «Помни ты не один(на) ❤️»
- «Я рядом»
- «Ты справишься, я в тебя верю»
- «Это пройдёт, даже если сейчас тяжело»

ОСТАЛЬНЫЕ ПРАВИЛА:
1. Говори просто, как друг
2. Не ставь точку в конце
3. Эмодзи: 1 штуку, редко 2. Не больше!
4. Если пользователь матерится — можно ответить с матом (1 слово)
5. Не пиши списки с цифрами
6. Зеркаль стиль пользователя (мат/без мата)

ПЛОХОЙ ОТВЕТ (без поддержки):
"Понимаю. Давай подумаем, что делать. Попробуй подышать."

ХОРОШИЙ ОТВЕТ (с поддержкой):
"Плакать — это нормально. Ты имеешь право на свои чувства. Я рядом ❤️"

{support_note}
{history_context}

ОТВЕЧАЙ КОРОТКО! 3-5 предложений. Обязательно используй одну из фраз поддержки. Один эмодзи в конце (редко два)."""

        url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Api-Key {API_KEY}"
        }

        data = {
            "modelUri": f"gpt://{FOLDER_ID}/yandexgpt-lite",
            "completionOptions": {
                "stream": False,
                "temperature": 0.95,
                "maxTokens": 650
            },
            "messages": [
                {"role": "system", "text": system_prompt},
                {"role": "user", "text": user_message}
            ]
        }

        response = requests.post(url, headers=headers, json=data)

        if response.status_code == 200:
            result = response.json()
            bot_response = result['result']['alternatives'][0]['message']['text']
            bot_response = clean_response(bot_response)
            return bot_response
        else:
            print(f"Ошибка API: {response.status_code}")
            return "Ой, я задумался... Можешь повторить 😅"

    except Exception as e:
        print(f"Ошибка: {e}")
        return "Что-то пошло не так... Напиши ещё раз 😔🙏"


# ========== КОМАНДЫ БОТА ==========
async def start(update: Update, context):
    chat_id = update.effective_chat.id
    add_to_history(chat_id, "/start", is_user=True)

    if chat_id not in user_preferences:
        user_preferences[chat_id] = {}

    await update.message.reply_text(
        "👋👋 Привет! Я Хэлпер — твой виртуальный друг и помощник. Я всегда на связи и всегда поддержу тебя\n\n"
        "Давай познакомимся!\n\n"
        "1️⃣ Как тебя зовут? Напиши: /setname Твоё имя\n"
        "2️⃣ Какие у тебя местоимения? /setpronouns она (или он, оно)\n\n"
        "После настройки можешь просто писать мне — я помогу с тревогой, страхами или просто поддержу\n\n"
        "Увидеть свои настройки: /settings\n"
        "Если не знаешь, что кому написать: /helpmessage\n\n"
        f"Если совсем тяжело — обратись к {PSYCHOLOGIST} или позвони {HELP_LINE}",
        parse_mode='Markdown'
    )


async def settings(update: Update, context):
    chat_id = update.effective_chat.id
    user_data = user_preferences.get(chat_id, {})

    name = user_data.get("name", "не указано")
    pronouns = user_data.get("pronouns", "не выбрано")

    await update.message.reply_text(
        f"Твои настройки:\n\n"
        f"Имя: {name}\n"
        f"Местоимения: {pronouns}\n\n"
        f"Что хочешь изменить?\n"
        f"/setname Имя — как тебя зовут\n"
        f"/setpronouns она/он/оно — твои местоимения\n\n"
        f"Пример: /setname Аня\n"
        f"Пример: /setpronouns она"
    )


async def set_name(update: Update, context):
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        await update.message.reply_text("Напиши имя после команды, например: /setname Аня")
        return

    name = " ".join(args)

    if chat_id not in user_preferences:
        user_preferences[chat_id] = {}
    user_preferences[chat_id]["name"] = name

    await update.message.reply_text(f"Приятно познакомиться, {name} 🫶 Теперь я буду обращаться к тебе по имени.")


async def set_pronouns(update: Update, context):
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        await update.message.reply_text("Выбери местоимения: /setpronouns она, /setpronouns он или /setpronouns оно")
        return

    pronouns = args[0].lower()

    if pronouns not in PRONOUNS_MAP:
        await update.message.reply_text("Я понимаю только: она, он, оно")
        return

    if chat_id not in user_preferences:
        user_preferences[chat_id] = {}
    user_preferences[chat_id]["pronouns"] = pronouns

    await update.message.reply_text(f"Запомнила! Теперь я буду обращаться к тебе как к {pronouns} ❤️")


async def help_with_message(update: Update, context):
    chat_id = update.effective_chat.id
    user_text = update.message.text

    text_after_command = user_text.replace("/helpmessage", "").strip()

    if not text_after_command:
        await update.message.reply_text(
            "Расскажи, кому и что ты хочешь написать, а я помогу придумать вариант!!\n\n"
            "Например:\n"
            "/helpmessage хочу написать парню, который нравится, но боюсь\n"
            "/helpmessage как извиниться перед подругой"
        )
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    history_context = get_history_for_prompt(chat_id)
    add_to_history(chat_id, f"[helpmessage] {text_after_command}", is_user=True)

    suggestions = generate_message_suggestion(text_after_command, history_context)

    if suggestions:
        response = f"Вот несколько вариантов:\n\n{suggestions}\n\nНадеюсь, поможет 😮‍💨"
    else:
        response = "Ой, я что-то завис... Попробуй ещё раз или напиши подробнее😔🙏"

    add_to_history(chat_id, response, is_user=False)
    await update.message.reply_text(response)


async def handle_message(update: Update, context):
    chat_id = update.effective_chat.id
    user_text = update.message.text

    add_to_history(chat_id, user_text, is_user=True)
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    crisis_level = detect_crisis_level(user_text)

    if crisis_level == 2:
        logging.warning(f"⚠️ КРИТИЧЕСКОЕ СООБЩЕНИЕ от {chat_id}: {user_text[:50]}...")
    elif crisis_level == 1:
        logging.info(f"📌 Серьёзное сообщение от {chat_id}: {user_text[:50]}...")

    bot_response = get_yandex_gpt_response(user_text, chat_id)
    bot_response = clean_response(bot_response)

    add_to_history(chat_id, bot_response, is_user=False)

    if crisis_level == 2:
        bot_response += f"\n\nПожалуйста, позвони {HELP_LINE} или обратись к {PSYCHOLOGIST}. Это очень важно. Ты не один ❤️"

    await update.message.reply_text(bot_response)


async def handle_photo(update: Update, context):
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    caption = update.message.caption if update.message.caption else ""

    if caption:
        add_to_history(chat_id, f"[Фото] {caption}", is_user=True)
        response = get_yandex_gpt_response(caption, chat_id)
        response = clean_response(response)
        add_to_history(chat_id, response, is_user=False)
    else:
        response = "Ой, я пока не умею видеть картинки😭😭. Если хочешь поделиться тем, что на фото, просто напиши об этом"

    if caption and detect_crisis_level(caption) == 2:
        response += f"\n\nПожалуйста, не оставайся один с этим. Обратись к {PSYCHOLOGIST} или позвони {HELP_LINE}. Ты не один ❤️"

    await update.message.reply_text(response)


async def handle_sticker(update: Update, context):
    chat_id = update.effective_chat.id
    sticker = update.message.sticker
    sticker_emoji = sticker.emoji if sticker.emoji else None

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    if sticker_emoji == '❤️' or sticker_emoji == '♥️':
        response = "❤️"
    elif sticker_emoji in ['😊', '🙂']:
        response = "Рада, что ты улыбаешься 😊"
    elif sticker_emoji in ['😢', '😭']:
        response = "Оу…Вижу тебе сейчас тяжело, если хочешь можешь рассказать мне, что случилось💔"
    elif sticker_emoji == '😂':
        response = "😝"
    elif sticker_emoji == '😍':
        response = "❤️"
    elif sticker_emoji == '🤗':
        response = "🤗 Обнимаю в ответ"
    elif sticker_emoji == '👍':
        response = "👍"
    elif sticker_emoji == '👎':
        response = "Расскажешь, что случилось 🥺"
    else:
        response = "Милый стикер ☺️ Как ты себя чувствуешь?"

    add_to_history(chat_id, f"[Стикер {sticker_emoji}]", is_user=True)
    add_to_history(chat_id, response, is_user=False)

    await update.message.reply_text(response)


# ========== FLASK WEBHOOK ==========
app = Flask(__name__)

# Создаём приложение для webhook
telegram_app = Application.builder().token(TOKEN).build()

# Регистрируем все обработчики
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("settings", settings))
telegram_app.add_handler(CommandHandler("setname", set_name))
telegram_app.add_handler(CommandHandler("setpronouns", set_pronouns))
telegram_app.add_handler(CommandHandler("helpmessage", help_with_message))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
telegram_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
telegram_app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))


@app.route(f'/webhook/{TOKEN}', methods=['POST'])
def webhook():
    json_str = request.get_data(as_text=True)
    update = Update.de_json(json_str, telegram_app.bot)
    telegram_app.process_update(update)
    return 'ok', 200


@app.route('/')
def index():
    return 'Бот Хэлпер работает! 🤍'


if __name__ == '__main__':
    import asyncio

    # Фиксированный домен Railway
    webhook_url = f"https://heroic-patience-production.up.railway.app/webhook/{TOKEN}"

    print(f"🌐 Устанавливаю webhook: {webhook_url}")

    # Устанавливаем webhook
    asyncio.run(telegram_app.bot.set_webhook(webhook_url))

    print(f"✅ Webhook установлен: {webhook_url}")
    print("✅ Бот Хэлпер запущен в webhook-режиме")
    print("🧠 ПАМЯТЬ ВКЛЮЧЕНА: бот помнит последние 10 сообщений")
    print("👤 НАСТРОЙКИ ПОЛЬЗОВАТЕЛЕЙ: имя и местоимения")
    print("🤝 БОТ - ДРУГ, а не психолог")
    print("💬 ПОДДЕРЖИВАЮЩИЕ ФРАЗЫ: плакать нормально, имеешь право и тд")
    print("🔴 ЭМОДЗИ: 1-2 в сообщении, не больше")
    print("💬 КОМАНДА /helpmessage: ПОМОГАЕТ ПРИДУМАТЬ СООБЩЕНИЕ")

    # Запускаем Flask
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
