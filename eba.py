# Подключаем библиотеки
import os
import logging
import requests
import json
import time
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from collections import defaultdict

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Контакты психолога
PSYCHOLOGIST = "Школьный психолог "
HELP_LINE = "Телефон доверия: 8-800-2000-122"

# Данные для Yandex GPT
FOLDER_ID = os.environ.get('FOLDER_ID')
API_KEY = os.environ.get('API_KEY')
TOKEN = os.environ.get('BOT_TOKEN')

# ========== СИСТЕМА ПАМЯТИ ==========
# Храним историю каждого пользователя: {chat_id: [сообщение1, сообщение2, ...]}
user_history = defaultdict(list)
MAX_HISTORY = 10  # храним последние 10 сообщений


def add_to_history(chat_id, message, is_user=True):
    """Добавляет сообщение в историю чата"""
    role = "user" if is_user else "assistant"
    user_history[chat_id].append({"role": role, "text": message})
    # Оставляем только последние MAX_HISTORY сообщений
    if len(user_history[chat_id]) > MAX_HISTORY:
        user_history[chat_id] = user_history[chat_id][-MAX_HISTORY:]


def get_history_for_prompt(chat_id):
    """Возвращает историю в виде строки для промпта"""
    history = user_history.get(chat_id, [])
    if not history:
        return ""

    history_text = "\n\nВот история вашего разговора (помни её, когда отвечаешь):\n"
    for msg in history[-6:]:  # последние 6 сообщений для контекста
        role = "Пользователь" if msg["role"] == "user" else "Ты"
        history_text += f"{role}: {msg['text']}\n"
    return history_text


# КАТЕГОРИИ КЛЮЧЕВЫХ СЛОВ
CRITICAL_KEYWORDS = [
    "суицид", "убью себя", "покончу с собой", "хочу умереть",
    "лучше бы я умер", "не хочу жить", "самоубийство", "убьюсь",
    "повешусь", "вскрою вены", "спрыгну", "таблетки выпью",
    "жизнь не имеет смысла", "не вижу смысла жить",
    "если б меня не было", "если бы меня не было",
    "всем было бы только лучше", "лучше б меня не было",
    "никому не нужен", "я никому не нужен", "без меня было бы лучше"
]

SERIOUS_KEYWORDS = [
    "депрессия", "ненавижу себя", "никому не нужен", "одиночество",
    "никто не понимает", "постоянно плачу", "безнадежно",
    "плохо с каждым днем", "не вижу выхода", "безысходность"
]

SUPPORT_KEYWORDS = [
    "грустно", "обидно", "плохо", "тоска", "устал", "сложно",
    "тяжело", "не получается", "расстроился", "обидели",
    "поссорился", "умер питомец", "собака умерла", "кошка умерла"
]

# ЛЁГКИЕ ТЕХНИКИ САМОРЕГУЛЯЦИИ (только рабочие)
GROUNDING_TECHNIQUES = [
    "разорвать бумажку на мелкие кусочки",
    "прибрать маленькую частичку комнаты — например, полку или стол",
    "пойти гулять одному на 5-10 минут",
    "умыться холодной водой"
]


def get_random_technique():
    """Возвращает случайную технику"""
    import random
    return random.choice(GROUNDING_TECHNIQUES)


def clean_response(text):
    """Очищает ответ от кавычек и лишних символов"""
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


def get_yandex_gpt_response(user_message, chat_id):
    """Отправляет запрос к Yandex GPT с учётом истории"""
    try:
        time.sleep(0.5)

        crisis_level = detect_crisis_level(user_message)

        # Получаем историю
        history_context = get_history_for_prompt(chat_id)

        if crisis_level == 2:
            support_note = f"⚠️ КРИТИЧЕСКАЯ СИТУАЦИЯ! Обязательно мягко порекомендуй обратиться к специалисту: {PSYCHOLOGIST} или позвонить {HELP_LINE}. Прояви максимальное сочувствие и заботу."
        elif crisis_level == 1:
            support_note = f"⚠️ СЕРЬЁЗНАЯ СИТУАЦИЯ. Прояви особую теплоту и мягко порекомендуй обратиться к {PSYCHOLOGIST}."
        else:
            support_note = "Пользователь нуждается в поддержке."

        # ОБНОВЛЁННЫЙ СИСТЕМНЫЙ ПРОМПТ
        system_prompt = f"""Ты - эмпатичный психолог-консультант для подростков. Твоя задача - внимательно прочитать сообщение пользователя и ответить, учитывая контекст всей переписки.

{support_note}
{history_context}

🌟 ВАЖНО О ТЕХНИКАХ:
Если пользователю тяжело или он в стрессе - предложи ОДНУ КОНКРЕТНУЮ ЛЁГКУЮ ТЕХНИКУ из этого списка (выбери самую уместную):
- разорвать бумажку на мелкие кусочки
- прибрать маленькую частичку комнаты (полку, стол, ящик)
- пойти гулять одному на 5-10 минут
- умыться холодной водой

Правила выбора:
1. Если пользователь злится или переполнен эмоциями → разорвать бумажку
2. Если чувствует хаос или беспорядок в голове → прибрать полку/стол
3. Если "задыхается" или сидит в помещении → пойти гулять одному
4. Если тревога, жар, паника → умыться холодной водой

📏 ДЛИНА ОТВЕТА: 2-4 предложения. БЕЗ ЛИШНИХ СЛОВ.

🤍 КЛЮЧЕВЫЕ ФРАЗЫ (1-2 на ответ):
"Ты не один" / "Ты молодец" / "Ты имеешь право" / "Я рядом" / "Твои чувства нормальны"

💫 ЭМОДЗИ: 1 в конце. 🤍 🫂 ✨ 💫 🌱

ПРИМЕРЫ ХОРОШИХ ОТВЕТОВ:

На злость/переполнение:
"Слышу тебя. Попробуй прямо сейчас разорвать бумажку на мелкие кусочки — это реально помогает выпустить пар 🫂"

На хаос в голове:
"Когда внутри бардак, помогает порядок снаружи. Прибери одну полку или стол — маленькое действие даст чувство контроля ✨"

На тревогу/панику:
"Твои чувства нормальны. Прямо сейчас пойди умойся холодной водой на 10 секунд — это отрезвляет 🤍"

На усталость/душно:
"Ты имеешь право выдохнуть. Просто выйди гулять один на 5 минут. Без цели, без телефона. Воздух помогает 🌱"

Главное: пореже пиши "дыши" и "выдохни" — используй лучше эти 4 техники."""

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
                "maxTokens": 250
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
            return "Ой, я задумалась... Можешь повторить? 🤍"

    except Exception as e:
        print(f"Ошибка: {e}")
        return "Что-то пошло не так... Напиши ещё раз 💫"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    add_to_history(chat_id, "/start", is_user=True)

    await update.message.reply_text(
        "🌟 Привет! Я Хэлпер — твой виртуальный друг и помощник.\n\n"
        "Я всегда на связи и всегда готов тебя поддержать 🤍\n\n"
        "Рассказывай, если у тебя что-то случилось, грустно, тревожно или просто хочется поговорить. "
        "Я никого не осуждаю и всё понимаю ✨\n\n"
        "Пиши — я рядом 💫\n\n"
        f"*Если совсем тяжело — обратись к {PSYCHOLOGIST} или позвони {HELP_LINE}*",
        parse_mode='Markdown'
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text

    # Сохраняем сообщение пользователя в историю
    add_to_history(chat_id, user_text, is_user=True)

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    crisis_level = detect_crisis_level(user_text)

    if crisis_level == 2:
        logging.warning(f"⚠️ КРИТИЧЕСКОЕ СООБЩЕНИЕ от {chat_id}: {user_text[:50]}...")
    elif crisis_level == 1:
        logging.info(f"📌 Серьёзное сообщение от {chat_id}: {user_text[:50]}...")

    # Получаем ответ от нейросети с учётом истории
    bot_response = get_yandex_gpt_response(user_text, chat_id)
    bot_response = clean_response(bot_response)

    # Сохраняем ответ бота в историю
    add_to_history(chat_id, bot_response, is_user=False)

    if crisis_level == 2:
        bot_response += f"\n\n🤍 Пожалуйста, позвони {HELP_LINE} или обратись к {PSYCHOLOGIST}. Это очень важно! Ты не один ✨"

    time.sleep(0.5)
    await update.message.reply_text(bot_response, parse_mode='Markdown')


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    caption = update.message.caption if update.message.caption else ""

    if caption:
        add_to_history(chat_id, f"[Фото] {caption}", is_user=True)
        response = get_yandex_gpt_response(caption, chat_id)
        response = clean_response(response)
        add_to_history(chat_id, response, is_user=False)
    else:
        response = "Ой, я пока не умею видеть картинки 😅 Но если хочешь поделиться тем, что на фото, просто напиши об этом!"

    if caption and detect_crisis_level(caption) == 2:
        response += f"\n\n🤍 Пожалуйста, не оставайся один с этим. Обратись к {PSYCHOLOGIST} или позвони {HELP_LINE}. Ты не один ✨"

    await update.message.reply_text(response)


async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    sticker = update.message.sticker
    sticker_emoji = sticker.emoji if sticker.emoji else None

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    if sticker_emoji == '❤️' or sticker_emoji == '♥️':
        response = "❤️"
    elif sticker_emoji in ['😊', '🙂']:
        response = "Рада, что ты улыбаешься! 😊"
    elif sticker_emoji in ['😢', '😭']:
        response = "Обнимаю тебя 🤗 Попробуй умыться холодной водой, иногда это очень отрезвляет 🫂"
    elif sticker_emoji == '😂':
        response = "Смех — лучшее лекарство! 😄"
    elif sticker_emoji == '😍':
        response = "💫"
    elif sticker_emoji == '🤗':
        response = "🤗 Обнимаю в ответ!"
    elif sticker_emoji == '👍':
        response = "👍"
    elif sticker_emoji == '👎':
        response = "Расскажешь, что случилось? 🤍 Может, разорвёшь бумажку на кусочки?"
    else:
        response = "Милый стикер! 🤍 Как ты себя чувствуешь?"

    add_to_history(chat_id, f"[Стикер {sticker_emoji}]", is_user=True)
    add_to_history(chat_id, response, is_user=False)

    await update.message.reply_text(response)


def main():
    if not TOKEN:
        raise ValueError("❌ Ошибка: нет токена! Добавь BOT_TOKEN в переменные окружения")
    if not FOLDER_ID:
        raise ValueError("❌ Ошибка: нет FOLDER_ID! Добавь FOLDER_ID в переменные окружения")
    if not API_KEY:
        raise ValueError("❌ Ошибка: нет API_KEY! Добавь API_KEY в переменные окружения")

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))

    print("✅ Бот с Яндекс GPT запущен!")
    print("🧠 ПАМЯТЬ ВКЛЮЧЕНА: бот помнит последние 10 сообщений каждого пользователя")
    print("🌿 ТЕХНИКИ ВКЛЮЧЕНЫ: вместо 'дыши' бот предлагает конкретные действия")
    print("📸 Распознавание фото: ДА")
    print("🎨 Распознавание стикеров: ДА")

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()