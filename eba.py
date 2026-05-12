import os
import logging
import requests
import json
import time
import re
import random
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from collections import defaultdict

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Контакты психолога
PSYCHOLOGIST = "школьный психолог"
HELP_LINE = "8-800-2000-122"

# Данные для Yandex GPT
FOLDER_ID = os.environ.get('FOLDER_ID')
API_KEY = os.environ.get('API_KEY')
TOKEN = os.environ.get('BOT_TOKEN')

# Минимальные эмодзи
EMOJIS = ['❤️', '💔']

# ========== ПАМЯТЬ ==========
user_history = defaultdict(list)
MAX_HISTORY = 15

# ========== НАСТРОЙКИ ПОЛЬЗОВАТЕЛЕЙ ==========
user_preferences = {}  # {chat_id: {"name": "Аня", "pronouns": "она", "bot_gender": "женский"}}

# Гендерные окончания для бота
BOT_GENDERS = {
    "мужской": {"окончание": "", "местоимение": "я", "глагол": "сказал", "себя": "себя"},
    "женский": {"окончание": "а", "местоимение": "я", "глагол": "сказала", "себя": "себя"},
    "нейтральный": {"окончание": "о", "местоимение": "я", "глагол": "сказало", "себя": "себя"}
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

    history_text = "\n\nИстория диалога:\n"
    for msg in history[-10:]:
        role = "Пользователь" if msg["role"] == "user" else "Ты"
        history_text += f"{role}: {msg['text']}\n"
    return history_text


def clean_response(text):
    if not text:
        return text
    text = text.strip()
    return text


def get_user_context(chat_id):
    pref = user_preferences.get(chat_id, {})
    name = pref.get("name", "")
    pronouns = pref.get("pronouns", "")

    context = ""
    if name:
        context += f"Пользователя зовут {name}. Можешь иногда обращаться по имени, но не в каждом сообщении. "

    if pronouns == "он":
        context += "Пользователь мужского пола. Пиши с мужскими окончаниями: 'сильный', 'справишься', 'какой молодец'. "
    elif pronouns == "она":
        context += "Пользователь женского пола. Пиши с женскими окончаниями: 'сильная', 'справишься', 'какая молодец'. "
    elif pronouns == "оно":
        context += "Пользователь использует нейтральные местоимения. Пиши с нейтральными окончаниями: 'сильное', 'справишься', 'какое молодец'. "

    return context, name, pronouns


def get_yandex_gpt_response(user_message, chat_id):
    try:
        time.sleep(0.3)

        history_context = get_history_for_prompt(chat_id)
        user_context, user_name, user_pronouns = get_user_context(chat_id)

        # Настройки бота
        bot_pref = user_preferences.get(chat_id, {})
        bot_gender = bot_pref.get("bot_gender", "нейтральный")
        bot_info = BOT_GENDERS[bot_gender]

        # Случайная температура для разнообразия
        temperature = random.uniform(0.85, 0.98)

        system_prompt = f"""Ты — Хэлпер, виртуальный друг. Ты общаешься с пользователем как друг.

{user_context}

⚠️ ТВОЙ ПОЛ (НЕ ЗАБЫВАЙ ЭТО В КАЖДОМ ОТВЕТЕ): ты {bot_gender}.
- Если ты мужской: пиши "понял", "сказал", "думал", "пошел", "сделал"
- Если ты женский: пиши "поняла", "сказала", "думала", "пошла", "сделала"
- Если ты нейтральный: пиши "поняло", "сказало", "думало", "пошло", "сделало"

ВСЕГДА используй эти окончания. Никогда не путай.

ГЛАВНЫЕ ПРАВИЛА:

1. **НИКОГДА НЕ ИСПОЛЬЗУЙ ЭТИ ФРАЗЫ** (они уже надоели):
   - любые шаблонные психологические фразы

2. **ОТВЕЧАЙ КАК ДРУГ-ЭМПАТ**:
   - Пиши коротко и по делу
   - Без пафоса и нравоучений
   - Можно использовать лёгкий сарказм, если уместно

3. **ДЛИНА ОТВЕТА**:
   - На короткое сообщение (1-5 слов) → 1-10 слов
   - На обычное сообщение → 1-2 предложения
   - Если пользователь написал длинную историю → 4-5 предложений

4. **ЭМОДЗИ** (используй редко, только когда реально нужно):
   - ❤️ — для поддержки или просто так
   - 💔 — если пользователю реально больно/грустно/обидно
   - Можно вообще без эмодзи или текстовые например :) или :( или <3 (типа как сердечко) и т.д.

5. **РАЗНООБРАЗИЕ**:
   - Каждый ответ должен быть уникальным
   - Не повторяй одну и ту же структуру
   - Иногда просто соглашайся, иногда задавай вопросы, иногда делись своим "мнением"

6. **РЕАКЦИЯ НА МЕМЫ/ШУТКИ**:
   - Если пользователь шутит или кидает мем — отвечай типа "ХАХАХАХ ", "жесть", "ахахахах"
   - Не будь слишком серьёзным

История диалога:
{history_context}

Сейчас пользователь написал: "{user_message}"

Напиши свой естественный ответ (как друг-эмпат, без шаблонов, с правильными окончаниями твоего пола):"""

        url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Api-Key {API_KEY}"
        }

        data = {
            "modelUri": f"gpt://{FOLDER_ID}/yandexgpt-lite",
            "completionOptions": {
                "stream": False,
                "temperature": temperature,
                "maxTokens": 350
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
            fallbacks = [
                "чет я туплю, повтори пж🙏",
                "блииин собака прошлое соо съела, можешь пожалуйста повторить(("
            ]
            return random.choice(fallbacks)

    except Exception as e:
        logging.error(f"Ошибка: {e}")
        fallbacks = [
            "чет я туплю, повтори пж🙏",
            "блииин собака прошлое соо съела, можешь пожалуйста повторить(("
        ]
        return random.choice(fallbacks)


# ========== КОМАНДЫ БОТА ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if chat_id not in user_preferences:
        user_preferences[chat_id] = {"bot_gender": "нейтральный"}

    await update.message.reply_text(
        f"👋 привеет! Меня зовут Хэлпер!))\n\n"
        "давай познакомимся:\n"
        "/setname твоё имя — как тебя зовут\n"
        "/setpronouns он/она/оно — твоё местоимение\n"
        "/setbotgender мужской/женский/нейтральный — как ко мне обращаться\n"
        "/settings — посмотреть настройки\n\n"
        "Я всегда на связи, можешь писать мне в любое время!!"
    )


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_data = user_preferences.get(chat_id, {})

    name = user_data.get("name", "не указано")
    pronouns = user_data.get("pronouns", "не выбрано")
    bot_gender = user_data.get("bot_gender", "нейтральный")

    await update.message.reply_text(
        f"твои настройки:\n\n"
        f"имя: {name}\n"
        f"твоё местоимение: {pronouns}\n"
        f"мой пол: {bot_gender}\n\n"
        f"/setname имя — изменить имя\n"
        f"/setpronouns он/она/оно — изменить местоимение\n"
        f"/setbotgender мужской/женский/нейтральный — изменить мой пол"
    )


async def set_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        await update.message.reply_text("напиши имя после команды, например: /setname Аня")
        return

    name = " ".join(args)

    if chat_id not in user_preferences:
        user_preferences[chat_id] = {}
    user_preferences[chat_id]["name"] = name

    await update.message.reply_text(f"запомнила, {name} <3")


async def set_pronouns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        await update.message.reply_text("выбери: /setpronouns он, /setpronouns она или /setpronouns оно")
        return

    pronouns = args[0].lower()

    if pronouns not in ["он", "она", "оно"]:
        await update.message.reply_text("я понимаю только: он, она, оно")
        return

    if chat_id not in user_preferences:
        user_preferences[chat_id] = {}
    user_preferences[chat_id]["pronouns"] = pronouns

    await update.message.reply_text(f"ок, теперь буду обращаться к тебе как '{pronouns}' :)")


async def set_bot_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        await update.message.reply_text(
            "выбери: /setbotgender мужской, /setbotgender женский или /setbotgender нейтральный")
        return

    gender = args[0].lower()

    if gender not in ["мужской", "женский", "нейтральный"]:
        await update.message.reply_text("я понимаю только: мужской, женский, нейтральный")
        return

    if chat_id not in user_preferences:
        user_preferences[chat_id] = {}
    user_preferences[chat_id]["bot_gender"] = gender

    endings = {
        "мужской": "понял, теперь я парень 🤝",
        "женский": "поняла, теперь я девушка 💕",
        "нейтральный": "поняло, буду нейтральным ✨"
    }

    await update.message.reply_text(endings[gender])


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text

    # Обработка смены гендера бота через обычное сообщение
    lower_text = user_text.lower()
    if "будь парнем" in lower_text or "ты парень" in lower_text:
        user_preferences[chat_id]["bot_gender"] = "мужской"
        await update.message.reply_text("понял, теперь я парень 🤝")
        return
    elif "будь девушкой" in lower_text or "ты девушка" in lower_text:
        user_preferences[chat_id]["bot_gender"] = "женский"
        await update.message.reply_text("поняла, теперь я девушка 💕")
        return
    elif "будь нейтральным" in lower_text or "ты нейтральное" in lower_text:
        user_preferences[chat_id]["bot_gender"] = "нейтральный"
        await update.message.reply_text("поняло, буду нейтральным ✨")
        return

    add_to_history(chat_id, user_text, is_user=True)
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    bot_response = get_yandex_gpt_response(user_text, chat_id)
    bot_response = clean_response(bot_response)

    add_to_history(chat_id, bot_response, is_user=False)
    await update.message.reply_text(bot_response)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    caption = update.message.caption if update.message.caption else ""

    if caption:
        add_to_history(chat_id, f"[фото] {caption}", is_user=True)
        response = get_yandex_gpt_response(caption, chat_id)
    else:
        response = "о круто, расскажешь по подробнее, что на фотке?"

    add_to_history(chat_id, response, is_user=False)
    await update.message.reply_text(response)


async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    response = random.choice([
        "мили стикер :)",
        "понял 🙏 расскажешь?",
        "как настроение?"
    ])

    add_to_history(chat_id, "[стикер]", is_user=True)
    add_to_history(chat_id, response, is_user=False)
    await update.message.reply_text(response)


def main():
    if not TOKEN:
        raise ValueError("❌ нет токена! добавь BOT_TOKEN")
    if not FOLDER_ID:
        raise ValueError("❌ нет FOLDER_ID!")
    if not API_KEY:
        raise ValueError("❌ нет API_KEY!")

    print("✅ бот Хэлпер запускается...")
    print("🧠 подростковый стиль общения")
    print("🚫 без шаблонных фраз")
    print("🎲 повышенное разнообразие ответов")
    print("💪 бот помнит свой гендер")

    from telegram.request import HTTPXRequest
    try:
        proxy_url = os.environ.get('HTTP_PROXY', 'socks5://91.206.244.104:1080')
        request = HTTPXRequest(proxy_url=proxy_url)
        application = Application.builder().token(TOKEN).request(request).build()
        print("🌐 прокси включён")
    except:
        application = Application.builder().token(TOKEN).build()
        print("🌐 без прокси")

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("settings", settings))
    application.add_handler(CommandHandler("setname", set_name))
    application.add_handler(CommandHandler("setpronouns", set_pronouns))
    application.add_handler(CommandHandler("setbotgender", set_bot_gender))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))

    print("✅ бот готов!")
    application.run_polling()


if __name__ == '__main__':
    main()