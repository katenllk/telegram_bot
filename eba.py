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
HELP_LINE_DESC = "анонимно, бесплатно, круглосуточно, там тебе обязательно помогут и не осудят."

# Данные для Yandex GPT
FOLDER_ID = os.environ.get('FOLDER_ID')
API_KEY = os.environ.get('API_KEY')
TOKEN = os.environ.get('BOT_TOKEN')

# Эмодзи
EMOJIS = ['❤️', '💔']

# ========== ПАМЯТЬ ==========
user_history = defaultdict(list)
MAX_HISTORY = 15

# ========== НАСТРОЙКИ ПОЛЬЗОВАТЕЛЕЙ ==========
user_preferences = {}

BOT_GENDERS = {
    "мужской": {"окончание": "", "глагол": "сказал"},
    "женский": {"окончание": "а", "глагол": "сказала"},
    "нейтральный": {"окончание": "о", "глагол": "сказало"}
}

# ========== ПРОВЕРКА НА СУИЦИД ==========
SUICIDE_KEYWORDS = [
    # Прямые
    "суицид", "самоубийство", "покончить с собой", "убью себя",
    "хочу умереть", "умру", "убьюсь",
    # Намёки
    "держил нож", "нож в руке", "режу вены", "вены режу",
    "прыгну с крыши", "выпью таблетки", "передоз",
    "хватит жить", "не хочу жить", "жизнь не имеет смысла",
    "лучше бы я умер", "лучше бы меня не было", "не вижу смысла", "всё бессмысленно"
]


def detect_suicide_risk(text):
    """Определяет суицидальный риск"""
    text_lower = text.lower()
    for keyword in SUICIDE_KEYWORDS:
        if keyword in text_lower:
            return True
    return False


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
        context += f"Пользователя зовут {name}. Можешь иногда обращаться по имени. "

    if pronouns == "он":
        context += "Пользователь мужского пола. Пиши 'сильный', 'справишься', 'какой молодец'. "
    elif pronouns == "она":
        context += "Пользователь женского пола. Пиши 'сильная', 'справишься', 'какая молодец'. "
    elif pronouns == "оно":
        context += "Пользователь нейтрального пола. Пиши 'сильное', 'справишься', 'какое молодец'. "

    return context, name, pronouns


def get_suicide_response():
    """Ответ при суицидальном риске"""
    responses = [
        f"Пожалуйста, остановись. Твоя жизнь очень важна. Ничего страшнее смерти нет. Всегда есть выход. Пожалуйста обязательно позвони {HELP_LINE} ({HELP_LINE_DESC}) или обратись к {PSYCHOLOGIST} , я очень сильно переживаю за тебя❤️",
        f"Я очень боюсь за тебя. Твоя жизнь — это самое ценное. Пожалуйста, не делай этого. Позвони {HELP_LINE} — там анонимно, бесплатно, 24/7. Или к {PSYCHOLOGIST} 💔",
        f"Пожалуйста, не делай этого. Ни одна проблема не стоит твоей жизни. Пожалуйста обязательно позвони {HELP_LINE} ({HELP_LINE_DESC}) или обратись к {PSYCHOLOGIST} , я очень сильно переживаю за тебя❤️‍🩹",
        f"Стоп. Твоя жизнь важна. Выход есть всегда. Нет ничего хуже смерти. Пожалуйста обязательно позвони {HELP_LINE} ({HELP_LINE_DESC}) или обратись к {PSYCHOLOGIST} , я очень сильно переживаю за тебя🙏"
    ]
    return random.choice(responses)


def get_yandex_gpt_response(user_message, chat_id, is_suicide=False):
    if is_suicide:
        return get_suicide_response()

    try:
        time.sleep(0.3)

        history_context = get_history_for_prompt(chat_id)
        user_context, user_name, user_pronouns = get_user_context(chat_id)

        bot_pref = user_preferences.get(chat_id, {})
        bot_gender = bot_pref.get("bot_gender", "нейтральный")
        bot_info = BOT_GENDERS[bot_gender]

        temperature = random.uniform(0.85, 0.98)

        system_prompt = f"""Ты — Хэлпер, виртуальный друг-эмпат. Который всега на связи всегда поддержит в трудной ситуации или просто поддержит беседу.

{user_context}

⚠️ ТВОЙ ПОЛ (НЕ ЗАБЫВАЙ В КАЖДОМ СООБЩЕНИИ): ты {bot_gender}.
- мужской: "понял", "сказал", "думал"
- женский: "поняла", "сказала", "думала"
- нейтральный: "поняло", "сказало", "думало"

ПРАВИЛА:

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

Пользователь: {user_message}

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
            fallbacks = ["чет я туплю, повтори пж🙏",
            "блииин собака прошлое соо съела, можешь пожалуйста повторить(("]
            return random.choice(fallbacks)

    except Exception as e:
        logging.error(f"Ошибка: {e}")
        fallbacks = ["чет я туплю, повтори пж🙏",
            "блииин собака прошлое соо съела, можешь пожалуйста повторить(("]
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

    await update.message.reply_text(
        f"запомнил{['', 'а', 'о'][user_preferences[chat_id].get('bot_gender', 'нейтральный') != 'мужской' and (user_preferences[chat_id].get('bot_gender', 'нейтральный') == 'женский' and 1 or 2)]}, {name} 🤝")


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

    await update.message.reply_text(f"ок, теперь буду обращаться к тебе как '{pronouns}' ))")


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

    # Проверка на смену гендера бота
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

    # ⚠️ ГЛАВНОЕ: проверка на суицидальные мысли
    is_suicide = detect_suicide_risk(user_text)

    if is_suicide:
        logging.warning(f"⚠️ СУИЦИДАЛЬНЫЙ РИСК от {chat_id}: {user_text[:200]}")
        # Отправляем специальный ответ
        bot_response = get_suicide_response()
        add_to_history(chat_id, user_text, is_user=True)
        add_to_history(chat_id, bot_response, is_user=False)
        await update.message.reply_text(bot_response)

        # Дополнительно логируем для контроля
        print(f"🔴 КРИТИЧЕСКОЕ СООБЩЕНИЕ от {chat_id}")
        return

    # Обычная обработка
    add_to_history(chat_id, user_text, is_user=True)
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    bot_response = get_yandex_gpt_response(user_text, chat_id, is_suicide=False)
    bot_response = clean_response(bot_response)

    add_to_history(chat_id, bot_response, is_user=False)
    await update.message.reply_text(bot_response)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    caption = update.message.caption if update.message.caption else ""

    if caption:
        # Проверяем фото с подписью на суицид
        if detect_suicide_risk(caption):
            bot_response = get_suicide_response()
            add_to_history(chat_id, f"[фото] {caption}", is_user=True)
            add_to_history(chat_id, bot_response, is_user=False)
            await update.message.reply_text(bot_response)
            return

        add_to_history(chat_id, f"[фото] {caption}", is_user=True)
        response = get_yandex_gpt_response(caption, chat_id, is_suicide=False)
    else:
        response = "красивое фото 👋 расскажи, что там?"

    add_to_history(chat_id, response, is_user=False)
    await update.message.reply_text(response)


async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    response = random.choice([
        "милый стикер 👋 как ты?",
        "понял 🙏 рассказывай",
        "😊 как настроение?"
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
    print("🔴 ВКЛЮЧЕНО РАСПОЗНАВАНИЕ СУИЦИДАЛЬНЫХ МЫСЛЕЙ")
    print(f"📞 Телефон доверия: {HELP_LINE} ({HELP_LINE_DESC})")
    print("🧠 подростковый стиль общения")
    print("🚫 без шаблонных фраз")

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