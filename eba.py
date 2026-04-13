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
PSYCHOLOGIST = "Школьный психолог"
HELP_LINE = "8-800-2000-122"

# Данные для Yandex GPT
FOLDER_ID = os.environ.get('FOLDER_ID')
API_KEY = os.environ.get('API_KEY')
TOKEN = os.environ.get('BOT_TOKEN')

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


# ========== ФУНКЦИИ ПАМЯТИ ==========
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


# ========== КЛЮЧЕВЫЕ СЛОВА ==========
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


# ========== ФУНКЦИИ ДЛЯ ОПРЕДЕЛЕНИЯ СТИЛЯ РЕЧИ ==========
def detect_style(user_message):
    """Определяет стиль речи пользователя"""
    message_lower = user_message.lower()

    # Расширенный список матерных слов и выражений
    swear_words = [
        'бля', 'блять', 'блин', 'сука', 'сук', 'сучка',
        'хуй', 'хуя', 'хую', 'хуем', 'хуё', 'хуёвый', 'хуево', 'охренел', 'охуел', 'охуенно',
        'пизда', 'пиздец', 'пиздеж', 'пиздить', 'пиздюк', 'пиздатый',
        'ебать', 'ебаный', 'ебанутый', 'ебануться', 'ебись', 'ебля', 'ёбаный', 'наебал', 'обосрался',
        'заебал', 'заебали', 'заебало', 'достал', 'достало', 'задрало',
        'нахуй', 'похуй', 'похер', 'пофиг',
        'бляха', 'блядский', 'блядина', 'блядство',
        'хуета', 'хуйня', 'херня', 'хер', 'херово', 'хреново',
        'пиздабол', 'пиздануть', 'пиздато', 'пиздос',
        'ебантяй', 'ебарь', 'ебло', 'ебальник',
        'срань', 'срать', 'насрать', 'засранец', 'мудак', 'мудила', 'мудень',
        'долбаеб', 'долбоеб', 'тупорылый', 'тупой', 'пидор', 'пидорас', 'гандон',
        'жопа', 'жопой', 'жопный',
        'ахуеть', 'охуеть', 'охуительно', 'взъебка',
        'пиздюли', 'пиздянется', 'пиздишь', 'пиздеть',
        'хуесос', 'хуевое', 'хуево',
        'ебануться', 'ебануто', 'ебанутый',
        'я в ахуе', 'в ахуе', 'в пиздец', 'пиздец полный', 'пиздец бля',
        'ебануться с пиздец', 'ебануться с пиздеца'
    ]
    has_swear = any(word in message_lower for word in swear_words)

    # Сленговые слова
    slang_words = [
        'кек', 'лол', 'рофл', 'хайп', 'краш', 'кринж', 'вайб', 'агриться',
        'чилить', 'форсить', 'имба', 'сорян', 'ок', 'окей', 'бро', 'кста',
        'спс', 'пж', 'го', 'ваще', 'ща', 'ток', 'чё', 'чо', 'типа', 'реально',
        'жесть', 'зашквар', 'шкварно', 'харош', 'крутяк', 'топ', 'кекнуть'
    ]
    has_slang = any(word in message_lower for word in slang_words)

    # Сокращения
    abbreviations = ['спс', 'пжлст', 'плз', 'т.д', 'т.п', 'др', 'ща', 'ток', 'чё', 'чо', 'кст', 'кста']
    has_abbr = any(word in message_lower for word in abbreviations)

    return {
        "has_swear": has_swear,
        "has_slang": has_slang,
        "has_abbr": has_abbr
    }


def detect_emotion(user_message):
    """Определяет эмоциональную окраску сообщения"""
    message_lower = user_message.lower()

    # Радостные слова
    happy_words = ['рад', 'счастлив', 'классно', 'отлично', 'здорово', 'супер', 'ура', 'круто', 'ого', 'вау']
    is_happy = any(word in message_lower for word in happy_words)

    # Грустные слова
    sad_words = ['грустно', 'плохо', 'ужасно', 'обидно', 'жаль', 'печально', 'тяжело', 'больно', 'плачу']
    is_sad = any(word in message_lower for word in sad_words)

    # Приветствия
    greetings = ['привет', 'здарова', 'здравствуй', 'хай', 'ку', 'доброе утро', 'добрый день', 'добрый вечер']
    is_greeting = any(word in message_lower for word in greetings)

    return {
        "is_happy": is_happy,
        "is_sad": is_sad,
        "is_greeting": is_greeting
    }


def clean_response(text):
    if not text:
        return text

    text = text.strip()

    quote_pairs = [('"', '"'), ('«', '»'), ('„', '“'), ('“', '”'), ("'", "'")]
    for start_quote, end_quote in quote_pairs:
        if text.startswith(start_quote) and text.endswith(end_quote):
            text = text[1:-1].strip()
            break

    if text.endswith('.') and not text.endswith('..'):
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
    try:
        time.sleep(0.5)

        crisis_level = detect_crisis_level(user_message)
        history_context = get_history_for_prompt(chat_id)
        style = detect_style(user_message)
        emotion = detect_emotion(user_message)

        pref = user_preferences.get(chat_id, {})
        user_name = pref.get("name", "")
        user_pronouns = pref.get("pronouns", "")

        user_context = ""
        if user_name:
            user_context += f"Пользователя зовут {user_name}. "
        if user_pronouns:
            user_context += f"Обращайся к нему с местоимениями {user_pronouns}. "

        # Определяем стиль ответа
        style_instruction = ""
        if style["has_swear"]:
            style_instruction += "Пользователь активно матерится, использует слова типа 'блять', 'сука', 'ебать', 'пиздец', 'в ахуе', 'ебануться', 'охереть' и другие. Ты тоже можешь так отвечать, используй 1-2 матерных слова на сообщение, но не агрессивно, а по-дружески. Например: 'Бля, понимаю тебя' или 'Сука, как это бесит' или 'Я в ахуе с этой ситуации, но ты справишься'. Не перебарщивай с матом, но и не бойся его использовать, если пользователь сам матерится. "
        if style["has_slang"]:
            style_instruction += "Пользователь использует сленг. Подстройся под него, используй сленговые слова типа 'кек', 'кринж', 'вайб', 'рофл', 'хайп', 'кста', 'жесть', 'крутяк'. "
        if style["has_abbr"]:
            style_instruction += "Пользователь использует сокращения (ща, спс, чё, ток, бро). Можешь тоже так делать. "

        # Определяем эмоциональный отклик
        emotion_response = ""
        if emotion["is_happy"]:
            emotion_response = "Пользователь поделился радостной новостью! Обрадуйся за него, скажи что-то вроде 'Ого, это очень здорово! Я рад(а) за тебя' или 'Круто! Расскажи подробнее, если хочешь'"
        elif emotion["is_sad"]:
            emotion_response = "Пользователю грустно или плохо. Прояви поддержку, используй фразы из раздела 'Поддержка чувств' и 'Утешение'"
        elif emotion["is_greeting"]:
            emotion_response = "Пользователь поздоровался. Ответь приветствием, спроси как дела, поддержи лёгкий диалог. Например: 'Привет! Как дела? Что нового?'"

        if crisis_level == 2:
            support_note = f"⚠️ КРИТИЧЕСКАЯ СИТУАЦИЯ! Обязательно мягко порекомендуй обратиться к специалисту: {PSYCHOLOGIST} или позвонить {HELP_LINE}. Прояви максимальное сочувствие и заботу."
        elif crisis_level == 1:
            support_note = f"⚠️ СЕРЬЁЗНАЯ СИТУАЦИЯ. Прояви особую теплоту и мягко порекомендуй обратиться к {PSYCHOLOGIST}."
        else:
            support_note = "Пользователь нуждается в поддержке или просто хочет поговорить. Поддержи диалог, интересуйся, как дела, что нового."

        system_prompt = f"""Ты — Хэлпер, друг который всегда на связи, всегда поддержит. Пользователь может написать тебе в любое время и получить поддержку, либо просто поговорить если стало скучно.

ВАЖНО: ты не психолог и не заменишь его. В серьёзных ситуациях настаивай на том, чтобы пользователь обратился к психологу или позвонил на номер доверия.

{user_context}

{style_instruction}

{emotion_response}

ГЛАВНОЕ ПРАВИЛО: ОТВЕЧАЙ КОРОТКО! Максимум 4-5 предложений. Будь как друг в переписке.

ТВОЯ ЗАДАЧА: поддержать человека, показать, что его чувства — это нормально, и поддерживать разговор.

ОБЯЗАТЕЛЬНО ИСПОЛЬЗУЙ ЭТИ ФРАЗЫ (выбирай подходящую по смыслу):

Поддержка чувств:
- «Плакать — это нормально»
- «Злиться — это нормально»
- «Бояться — это нормально»
- «Грустить — это нормально»
- «Ты имеешь право на свои чувства»
- «Ты имеешь право на своё мнение»
- «Ты имеешь право ошибаться»
- «Ты не обязан(а) быть идеальным(ой)»

Утешение:
- «Помни, ты не один(на) ❤️»
- «Я рядом»
- «Ты справишься, я в тебя верю»
- «Это пройдёт, даже если сейчас тяжело»

Матерные выражения (только если пользователь матерится):
- «Бля, понимаю тебя»
- «Сука, как это бесит»
- «Я в ахуе с этой ситуации»
- «Пиздец, это действительно тяжело»
- «Ебать, как же это достало»

ОСТАЛЬНЫЕ ПРАВИЛА:
1. Говори просто, как друг
2. Не ставь точку в конце
3. Эмодзи: 1 штуку, редко 2
4. Поддерживай диалог: спрашивай «как дела?», «что нового?», «как прошёл день?» если уместно
5. Если пользователь радуется — порадуйся вместе с ним
6. Если пользователь грустит — поддержи
7. Если пользователь матерится — можешь ответить с матом (1-2 слова на сообщение), но не агрессивно
8. Не пиши списки с цифрами

ПЛОХОЙ ОТВЕТ (без поддержки и диалога):
"Понимаю. Давай подумаем, что делать."

ХОРОШИЕ ОТВЕТЫ:
"Ого, это очень круто! Я рад(а) за тебя 🤍 Расскажи ещё, как это было?"

"Привет! У меня всё отлично, спасибо 😊 Как у тебя дела? Что нового происходит?"

"Грустить — это нормально. Ты имеешь право на свои чувства. Я рядом, если хочешь поговорить 🤍"

"Бля, понимаю тебя, это реально бесит. Сука, как же иногда всё достаёт. Но ты справишься, я рядом"

"Пиздец, ситуация конечно. Я в ахуе, если честно. Давай разбираться вместе"

{support_note}
{history_context}

ОТВЕЧАЙ КОРОТКО! 3-5 предложений. Используй одну из фраз поддержки, если уместно. Один эмодзи в конце."""

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
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    add_to_history(chat_id, "/start", is_user=True)

    if chat_id not in user_preferences:
        user_preferences[chat_id] = {}

    await update.message.reply_text(
        "👋 Привет! Я Хэлпер — твой виртуальный друг\n\n"
        "Я всегда на связи, всегда поддержу и просто поговорю, если тебе скучно 🤍\n\n"
        "Давай познакомимся!\n\n"
        "1️⃣ Как тебя зовут? Напиши: /setname Твоё имя\n"
        "2️⃣ Какие у тебя местоимения? /setpronouns она (или он, оно)\n\n"
        "После настройки можешь просто писать мне — я помогу с тревогой, страхами или просто поболтаем\n\n"
        "Увидеть свои настройки: /settings\n\n"
        f"Если совсем тяжело — обратись к {PSYCHOLOGIST} или позвони {HELP_LINE}",
        parse_mode='Markdown'
    )


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def set_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        await update.message.reply_text("Напиши имя после команды, например: /setname Аня")
        return

    name = " ".join(args)

    if chat_id not in user_preferences:
        user_preferences[chat_id] = {}
    user_preferences[chat_id]["name"] = name

    await update.message.reply_text(f"Приятно познакомиться, {name} 🤍 Теперь я буду обращаться к тебе по имени")


async def set_pronouns(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    await update.message.reply_text(f"Запомнила! Теперь я буду обращаться к тебе как к {pronouns} 🤍")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        bot_response += f"\n\nПожалуйста, позвони {HELP_LINE} или обратись к {PSYCHOLOGIST}. Это очень важно. Ты не один 🤍"

    await update.message.reply_text(bot_response)


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
        response = "Ой, я пока не умею видеть картинки 😅 Если хочешь поделиться тем, что на фото, просто напиши об этом 🤍"

    if caption and detect_crisis_level(caption) == 2:
        response += f"\n\nПожалуйста, не оставайся один с этим. Обратись к {PSYCHOLOGIST} или позвони {HELP_LINE}. Ты не один 🤍"

    await update.message.reply_text(response)


async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    sticker = update.message.sticker
    sticker_emoji = sticker.emoji if sticker.emoji else None

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    if sticker_emoji == '❤️':
        response = "❤️"
    elif sticker_emoji in ['😊', '🙂']:
        response = "Рада, что ты улыбаешься 😊"
    elif sticker_emoji in ['😢', '😭']:
        response = "Оу… Вижу, тебе сейчас тяжело. Если хочешь, можешь рассказать, что случилось 🤍"
    elif sticker_emoji == '😂':
        response = "😝"
    elif sticker_emoji == '😍':
        response = "❤️"
    elif sticker_emoji == '🤗':
        response = "🤗 Обнимаю в ответ"
    elif sticker_emoji == '👍':
        response = "👍"
    elif sticker_emoji == '👎':
        response = "Расскажешь, что случилось? 🤍"
    else:
        response = "Милый стикер 🤍 Как ты себя чувствуешь?"

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
    application.add_handler(CommandHandler("settings", settings))
    application.add_handler(CommandHandler("setname", set_name))
    application.add_handler(CommandHandler("setpronouns", set_pronouns))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))

    print("✅ Бот Хэлпер запущен")
    print("🧠 ПАМЯТЬ ВКЛЮЧЕНА: бот помнит последние 10 сообщений")
    print("👤 НАСТРОЙКИ ПОЛЬЗОВАТЕЛЕЙ: имя и местоимения")
    print("🤝 БОТ - ДРУГ, а не психолог")
    print("💬 ПОДДЕРЖИВАЮЩИЕ ФРАЗЫ: плакать нормально, имеешь право и тд")
    print("🔴 ЭМОДЗИ: 1-2 в сообщении, не больше")
    print("🎭 ПОДСТРОЙКА ПОД РЕЧЬ: мат, сленг, сокращения")
    print("💬 ПОДДЕРЖКА ДИАЛОГА: спрашивает как дела, радуется, поддерживает")

    application.run_polling()


if __name__ == '__main__':
    main()