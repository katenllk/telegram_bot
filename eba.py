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


def detect_style(user_message):
    """Определяет стиль речи пользователя"""
    message_lower = user_message.lower()

    swear_words = [
        'бля', 'блять', 'сука', 'сучка', 'хуй', 'хуя', 'пизда', 'пиздец',
        'ебать', 'ебаный', 'ебанутый', 'ебануться', 'заебал', 'заебали',
        'нахуй', 'похуй', 'пиздос', 'долбаеб', 'мудак', 'пидор', 'жопа',
        'ахуеть', 'охуеть', 'пиздабол', 'хуесос', 'срань', 'гандон',
        'я в ахуе', 'в ахуе', 'в пиздец', 'пиздец полный', 'ебануться с пиздец'
    ]
    has_swear = any(word in message_lower for word in swear_words)

    slang_words = ['кек', 'лол', 'рофл', 'хайп', 'краш', 'кринж', 'вайб', 'чилить', 'сорян', 'бро', 'кста']
    has_slang = any(word in message_lower for word in slang_words)

    abbreviations = ['спс', 'плз', 'ща', 'чё', 'чо', 'ток', 'кст']
    has_abbr = any(word in message_lower for word in abbreviations)

    return {"has_swear": has_swear, "has_slang": has_slang, "has_abbr": has_abbr}


def detect_emotion(user_message):
    """Определяет эмоциональную окраску сообщения"""
    message_lower = user_message.lower()

    happy_words = ['рад', 'счастлив', 'классно', 'отлично', 'здорово', 'супер', 'ура', 'круто', 'ого', 'вау']
    is_happy = any(word in message_lower for word in happy_words)

    sad_words = ['грустно', 'плохо', 'ужасно', 'обидно', 'жаль', 'печально', 'тяжело', 'больно', 'плачу']
    is_sad = any(word in message_lower for word in sad_words)

    greetings = ['привет', 'здарова', 'хай', 'ку', 'доброе утро', 'добрый день', 'добрый вечер']
    is_greeting = any(word in message_lower for word in greetings)

    return {"is_happy": is_happy, "is_sad": is_sad, "is_greeting": is_greeting}


def clean_response(text):
    if not text:
        return text
    text = text.strip()
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

        style_instruction = ""
        if style["has_swear"]:
            style_instruction += "Пользователь активно матерится, использует слова типа 'блять', 'сука', 'ебать', 'пиздец', 'в ахуе', 'ебануться', 'охереть' и другие. Ты тоже можешь так отвечать, используй 1-2 матерных слова на сообщение, но не агрессивно, а по-дружески. Например: 'Бля, понимаю тебя' или 'Сука, как это бесит' или 'Я в ахуе с этой ситуации, но ты справишься'. Не перебарщивай с матом, но и не бойся его использовать, если пользователь сам матерится. "
        if style["has_slang"]:
            style_instruction += "Пользователь использует сленг. Подстройся под него, используй сленговые слова типа 'кек', 'кринж', 'вайб', 'рофл', 'хайп', 'кста', 'жесть', 'крутяк'. "
        if style["has_abbr"]:
            style_instruction += "Пользователь использует сокращения (ща, спс, чё, ток, бро). Можешь тоже так делать. "

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
        "Я всегда на связи, всегда поддержу и просто поговорю 🤍\n\n"
        "Давай познакомимся!\n\n"
        "1️⃣ Как тебя зовут? Напиши: /setname Твоё имя\n"
        "2️⃣ Какие у тебя местоимения? /setpronouns она (или он, оно)\n\n"
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
        f"Твои настройки:\n\nИмя: {name}\nМестоимения: {pronouns}\n\n"
        f"/setname Имя — как тебя зовут\n"
        f"/setpronouns она/он/оно — твои местоимения"
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

    await update.message.reply_text(f"Приятно познакомиться, {name} 🤍")


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
        logging.warning(f"⚠️ КРИТИЧЕСКОЕ СООБЩЕНИЕ от {chat_id}")
    elif crisis_level == 1:
        logging.info(f"📌 Серьёзное сообщение от {chat_id}")

    bot_response = get_yandex_gpt_response(user_text, chat_id)
    bot_response = clean_response(bot_response)

    add_to_history(chat_id, bot_response, is_user=False)

    if crisis_level == 2:
        bot_response += f"\n\nПожалуйста, позвони {HELP_LINE} или обратись к {PSYCHOLOGIST}. Ты не один 🤍"

    await update.message.reply_text(bot_response)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    caption = update.message.caption if update.message.caption else ""

    if caption:
        add_to_history(chat_id, f"[Фото] {caption}", is_user=True)
        response = get_yandex_gpt_response(caption, chat_id)
        response = clean_response(response)
        add_to_history(chat_id, response, is_user=False)
    else:
        response = "Ой, я пока не умею видеть картинки 😅 Если хочешь поделиться тем, что на фото, просто напиши об этом 🤍"

    await update.message.reply_text(response)


async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    sticker = update.message.sticker
    sticker_emoji = sticker.emoji if sticker.emoji else None

    if sticker_emoji in ['😢', '😭']:
        response = "Оу… Вижу, тебе сейчас тяжело. Если хочешь, можешь рассказать, что случилось 🤍"
    elif sticker_emoji in ['😊', '🙂']:
        response = "Рада, что ты улыбаешься 😊"
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

    print("✅ BOT_TOKEN найден")
    print("✅ FOLDER_ID найден")
    print("✅ API_KEY найден")

    # Прокси для России (если нужно)
    from telegram.request import HTTPXRequest
    try:
        proxy_url = os.environ.get('HTTP_PROXY', 'socks5://91.206.244.104:1080')
        request = HTTPXRequest(proxy_url=proxy_url)
        application = Application.builder().token(TOKEN).request(request).build()
        print("🌐 Прокси включён")
    except:
        application = Application.builder().token(TOKEN).build()
        print("🌐 Без прокси")

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("settings", settings))
    application.add_handler(CommandHandler("setname", set_name))
    application.add_handler(CommandHandler("setpronouns", set_pronouns))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))

    print("✅ Бот Хэлпер запущен")
    print("🧠 ПАМЯТЬ ВКЛЮЧЕНА")
    print("💬 ПОДДЕРЖКА ДИАЛОГА")

    application.run_polling()


if __name__ == '__main__':
    main()