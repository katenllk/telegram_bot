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

# Нормальные эмодзи
EMOJIS = ['❤️', '🔥', '👎', '👍', '🙏', '💕', '🫶', '🥺', '👋', '💔', '❤️‍🩹', '😊', '😔', '💪', '✨']


def get_random_emojis(count=1):
    selected = random.sample(EMOJIS, min(count, len(EMOJIS)))
    return ' '.join(selected)


# ========== ПАМЯТЬ ==========
user_history = defaultdict(list)
MAX_HISTORY = 15

# ========== НАСТРОЙКИ ПОЛЬЗОВАТЕЛЕЙ ==========
user_preferences = {}  # {chat_id: {"name": "Ваня", "pronouns": "он", "bot_gender": "нейтральный"}}

# Гендерные окончания для бота
BOT_GENDERS = {
    "мужской": {"я": "я", "окончание": "", "себя": "себя"},
    "женский": {"я": "я", "окончание": "а", "себя": "себя"},
    "нейтральный": {"я": "я", "окончание": "о", "себя": "себя"}
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
    """Возвращает контекст пользователя с правильными склонениями"""
    pref = user_preferences.get(chat_id, {})
    name = pref.get("name", "")
    pronouns = pref.get("pronouns", "")

    context = ""
    if name:
        context += f"Пользователя зовут {name}. "

    if pronouns == "он":
        context += "Пользователь мужского пола. В общении используй: он, его, ему. Пиши окончания 'ый', 'ой', 'ешься' (например: сильный, справишься, молодец). "
    elif pronouns == "она":
        context += "Пользователь женского пола. В общении используй: она, её, ей. Пиши окончания 'ая', 'ая', 'ешься' (например: сильная, справишься, молодец). "
    elif pronouns == "оно":
        context += "Пользователь использует нейтральные местоимения. В общении используй: оно, его, ему. Пиши окончания 'ое', 'ое', 'ешься' (например: сильное, справишься, молодец). "

    return context, name, pronouns


def get_yandex_gpt_response(user_message, chat_id):
    try:
        time.sleep(0.3)

        history_context = get_history_for_prompt(chat_id)
        user_context, user_name, user_pronouns = get_user_context(chat_id)

        # Настройки бота
        bot_pref = user_preferences.get(chat_id, {})
        bot_gender = bot_pref.get("bot_gender", "нейтральный")
        bot_ending = BOT_GENDERS[bot_gender]["окончание"]

        system_prompt = f"""Ты — Хэлпер, виртуальный друг. Ты общаешься с пользователем как настоящий друг.

{user_context}

Твой пол: {bot_gender}. Пиши с окончаниями: понял{bot_ending}, сказал{bot_ending}, подумал{bot_ending}.

ГЛАВНОЕ ПРАВИЛО:
Ты сам анализируешь ситуацию. Не используешь заготовленные фразы. Ты смотришь на:
- о чём пишет пользователь (тема разговора)
- как он пишет (коротко или длинно)
- его эмоции (грусть, радость, злость)
- контекст из истории диалога

И на основе этого ты генерируешь СВОЙ уникальный ответ, а не берёшь из примеров.

ДЛИНА ОТВЕТА:
- Если пользователь написал коротко (1-5 слов) → отвечай коротко (1-10 слов)
- Если пользователь написал длинно (предложение или больше) → отвечай 3-5 предложениями

КАК ИСПОЛЬЗОВАТЬ ИМЯ:
Если знаешь имя пользователя — иногда используй его в ответе, но не в каждом сообщении. Например: "Ваня, не переживай" или "Слушай, Ваня, всё будет нормально"

КАК ИСПОЛЬЗОВАТЬ МЕСТОИМЕНИЯ:
Пользователь выбрал местоимения (он/она/оно). Пиши в соответствии с ними:
- он → "ты сильный", "ты справишься", "какой ты молодец"
- она → "ты сильная", "ты справишься", "какая ты молодец"
- оно → "ты сильное", "ты справишься", "какое ты молодец"

ЭМОДЗИ (используй РАЗНООБРАЗНО, но не в каждом сообщении):
❤️ 🔥 👍 👎 🙏 💕 🫶 🥺 👋 💔 ❤️‍🩹 💪 ✨
- К грустному: 💔
- К поддержке: ❤️‍🩹
- К радостному: ❤️ или 🔥
- Не используй радуги, солнышки, цветочки

Если пользователь просит сменить твой пол фразами "будь парнем", "ты парень", "будь девушкой", "ты нейтральное" — соглашайся и пиши "Хорошо, я понял" или "Хорошо, я поняла"

ВАЖНО: Никогда не копируй фразы из этого промта в ответы. Генерируй уникальные ответы каждый раз.

История диалога (для контекста):
{history_context}

Пользователь написал: "{user_message}"

Напиши свой естественный ответ:"""

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
                "maxTokens": 400
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
            return f"Не врубился, сори 🙏 Повтори?"

    except Exception as e:
        logging.error(f"Ошибка: {e}")
        return f"Что-то пошло не так 😔 Напиши ещё раз"


# ========== КОМАНДЫ БОТА ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if chat_id not in user_preferences:
        user_preferences[chat_id] = {"bot_gender": "нейтральный"}

    await update.message.reply_text(
        f"👋 Привет! Я Хэлпер — твой друг\n\n"
        "Давай познакомимся:\n"
        "/setname Твоё имя — как тебя зовут\n"
        "/setpronouns он/она/оно — твоё местоимение (одно, не несколько)\n"
        "/setbotgender мужской/женский/нейтральный — как ко мне обращаться\n"
        "/settings — посмотреть настройки\n\n"
        f"Если тяжело — {PSYCHOLOGIST} или {HELP_LINE} ❤️",
        parse_mode='Markdown'
    )


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_data = user_preferences.get(chat_id, {})

    name = user_data.get("name", "не указано")
    pronouns = user_data.get("pronouns", "не выбрано")
    bot_gender = user_data.get("bot_gender", "нейтральный")

    await update.message.reply_text(
        f"Твои настройки:\n\n"
        f"Имя: {name}\n"
        f"Твоё местоимение: {pronouns}\n"
        f"Мой пол: {bot_gender}\n\n"
        f"/setname Имя — изменить имя\n"
        f"/setpronouns он/она/оно — изменить местоимение\n"
        f"/setbotgender мужской/женский/нейтральный — изменить мой пол"
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

    await update.message.reply_text(f"Запомнил, {name} 🤝")


async def set_pronouns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        await update.message.reply_text("Выбери: /setpronouns он, /setpronouns она или /setpronouns оно")
        return

    pronouns = args[0].lower()

    if pronouns not in ["он", "она", "оно"]:
        await update.message.reply_text("Я понимаю только: он, она, оно")
        return

    if chat_id not in user_preferences:
        user_preferences[chat_id] = {}
    user_preferences[chat_id]["pronouns"] = pronouns

    await update.message.reply_text(f"Понял, теперь буду обращаться к тебе как к '{pronouns}' 💪")


async def set_bot_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        await update.message.reply_text(
            "Выбери: /setbotgender мужской, /setbotgender женский или /setbotgender нейтральный")
        return

    gender = args[0].lower()

    if gender not in ["мужской", "женский", "нейтральный"]:
        await update.message.reply_text("Я понимаю только: мужской, женский, нейтральный")
        return

    if chat_id not in user_preferences:
        user_preferences[chat_id] = {}
    user_preferences[chat_id]["bot_gender"] = gender

    if gender == "мужской":
        await update.message.reply_text("Хорошо, я понял, теперь я парень 🤝")
    elif gender == "женский":
        await update.message.reply_text("Хорошо, я поняла, теперь я девушка 💕")
    else:
        await update.message.reply_text("Хорошо, я понял, буду нейтральным ✨")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text

    # Обработка смены гендера бота через обычное сообщение
    lower_text = user_text.lower()
    if "будь парнем" in lower_text or "ты парень" in lower_text:
        user_preferences[chat_id]["bot_gender"] = "мужской"
        await update.message.reply_text("Хорошо, я понял, теперь я парень 🤝")
        return
    elif "будь девушкой" in lower_text or "ты девушка" in lower_text:
        user_preferences[chat_id]["bot_gender"] = "женский"
        await update.message.reply_text("Хорошо, я поняла, теперь я девушка 💕")
        return
    elif "будь нейтральным" in lower_text or "ты нейтральное" in lower_text:
        user_preferences[chat_id]["bot_gender"] = "нейтральный"
        await update.message.reply_text("Хорошо, я понял, буду нейтральным ✨")
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
        add_to_history(chat_id, f"[Фото] {caption}", is_user=True)
        response = get_yandex_gpt_response(caption, chat_id)
    else:
        response = f"Красивое фото 👋 Расскажи, что на нём?"

    add_to_history(chat_id, response, is_user=False)
    await update.message.reply_text(response)


async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    response = random.choice([
        f"Милый стикер 👋 Как ты?",
        f"Понял 🙏 Рассказывай",
        f"😊 Как настроение?"
    ])

    add_to_history(chat_id, f"[Стикер]", is_user=True)
    add_to_history(chat_id, response, is_user=False)
    await update.message.reply_text(response)


def main():
    if not TOKEN:
        raise ValueError("❌ Ошибка: нет BOT_TOKEN в переменных окружения")
    if not FOLDER_ID:
        raise ValueError("❌ Ошибка: нет FOLDER_ID в переменных окружения")
    if not API_KEY:
        raise ValueError("❌ Ошибка: нет API_KEY в переменных окружения")

    print("✅ Бот Хэлпер запускается...")
    print("🧠 Анализирует контекст сам, без примеров")
    print("👤 Учитывает имя и местоимение пользователя")
    print("🔄 Можно менять пол бота")
    print("❤️ Эмодзи: только нормальные")

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
    application.add_handler(CommandHandler("setbotgender", set_bot_gender))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))

    print("✅ Бот готов!")
    application.run_polling()


if __name__ == '__main__':
    main()