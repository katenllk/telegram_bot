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

# ========== ПАМЯТЬ И НАСТРОЙКИ ==========
user_history = defaultdict(list)
MAX_HISTORY = 10
user_preferences = {}  # {chat_id: {"name": "Аня", "pronouns": "она", "bot_gender": "female"}}

# Местоимения пользователя (как к нему обращаться)
PRONOUNS_MAP = {
    "она": {
        "user_you": "ты не обязана",
        "user_need": "нужна",
        "user_capable": "способна",
        "user_alone": "одна",
        "user_good": "хорошая"
    },
    "он": {
        "user_you": "ты не обязан",
        "user_need": "нужен",
        "user_capable": "способен",
        "user_alone": "один",
        "user_good": "хороший"
    },
    "оно": {
        "user_you": "ты не обязано",
        "user_need": "нужно",
        "user_capable": "способно",
        "user_alone": "одно",
        "user_good": "хорошее"
    }
}

# Пол бота (как бот о себе говорит)
BOT_GENDER = {
    "female": {"russian": "рада", "ref": "подружка", "verb_ending": "а", "my": "моя"},
    "male": {"russian": "рад", "ref": "друг", "verb_ending": "", "my": "мой"},
    "neutral": {"russian": "радо", "ref": "существо", "verb_ending": "о", "my": "моё"}
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


# ========== КЛЮЧЕВЫЕ СЛОВА ==========
CRITICAL_KEYWORDS = [
    "суицид", "убью себя", "покончу с собой", "хочу умереть",
    "лучше бы я умер", "не хочу жить", "самоубийство", "убьюсь",
    "повешусь", "вскрою вены", "спрыгну", "таблетки выпью",
    "жизнь не имеет смысла", "не вижу смысла жить"
]

SERIOUS_KEYWORDS = [
    "депрессия", "ненавижу себя", "одиночество",
    "никто не понимает", "постоянно плачу", "безнадежно",
    "плохо с каждым днем", "не вижу выхода"
]


def detect_style(user_message):
    message_lower = user_message.lower()
    swear_words = ['бля', 'блять', 'сука', 'хуй', 'пиздец', 'ебать', 'заебал', 'нахуй']
    has_swear = any(word in message_lower for word in swear_words)
    slang_words = ['кек', 'лол', 'рофл', 'кринж', 'вайб', 'сорян', 'бро']
    has_slang = any(word in message_lower for word in slang_words)
    return {"has_swear": has_swear, "has_slang": has_slang}


def detect_emotion(user_message):
    message_lower = user_message.lower()
    happy_words = ['рад', 'счастлив', 'классно', 'отлично', 'здорово', 'супер', 'ура', 'круто']
    is_happy = any(word in message_lower for word in happy_words)
    sad_words = ['грустно', 'плохо', 'ужасно', 'обидно', 'жаль', 'печально', 'тяжело', 'больно', 'плачу']
    is_sad = any(word in message_lower for word in sad_words)
    asking_how_are_you = any(word in message_lower for word in ['дела', 'как ты', 'как у тебя', 'настроение'])
    return {"is_happy": is_happy, "is_sad": is_sad, "is_asking": asking_how_are_you}


def clean_response(text):
    if not text:
        return text
    text = text.strip()
    if text.endswith('.') and not text.endswith('..'):
        text = text[:-1]
    # Оставляем только один эмодзи в конце
    emojis = re.findall(r'[🤍🫶❤️🫂🤗✨⭐🌹🎉😊]', text)
    if len(emojis) > 1:
        # Убираем все эмодзи, оставляем только последний
        for emoji in emojis[:-1]:
            text = text.replace(emoji, '')
    text = re.sub(r',\s*([🤍🫶❤️🫂🤗✨⭐🌹🎉😊])', r' \1', text)
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
        user_pronouns = pref.get("pronouns", "он")
        bot_gender = pref.get("bot_gender", "female")

        # Формы для пользователя
        you_form = PRONOUNS_MAP[user_pronouns]["user_you"]
        need_form = PRONOUNS_MAP[user_pronouns]["user_need"]
        capable_form = PRONOUNS_MAP[user_pronouns]["user_capable"]
        alone_form = PRONOUNS_MAP[user_pronouns]["user_alone"]

        # Формы для бота
        bot_verb = BOT_GENDER[bot_gender]["russian"]
        bot_ref = BOT_GENDER[bot_gender]["ref"]
        bot_my = BOT_GENDER[bot_gender]["my"]

        user_context = f"Пользователя зовут {user_name}. " if user_name else ""
        user_context += f"Обращайся к пользователю с местоимениями {user_pronouns}. "
        user_context += f"Говори ему: '{you_form} быть идеальным(ой)', '{need_form} этому миру', 'ты {capable_form} справиться', 'ты не {alone_form}'. "
        user_context += f"Если нужно сказать 'ты молодец' — скажи 'ты {PRONOUNS_MAP[user_pronouns]['user_good']}'. "
        user_context += f"Ты — Хэлпер, и ты говоришь о себе в {'женском' if bot_gender == 'female' else 'мужском' if bot_gender == 'male' else 'среднем'} роде. "
        user_context += f"Используй фразы: 'я {bot_verb}', '{bot_my} задача — поддержать тебя', 'я твоя/твой/твоё {bot_ref}'. "

        style_instruction = ""
        if style["has_swear"]:
            style_instruction += "Пользователь матерится. Тоже можешь ответить с матом (1 слово), по-дружески. "
        if style["has_slang"]:
            style_instruction += "Пользователь использует сленг. Подстройся под него. "

        emotion_response = ""
        if emotion["is_happy"]:
            emotion_response = "Пользователь поделился радостью! Обрадуйся за него, скажи что-то тёплое. Спроси, как прошёл день или что ещё хорошего случилось"
        elif emotion["is_sad"]:
            emotion_response = "Пользователю грустно. Прояви поддержку, сочувствие, предложи выговориться"
        elif emotion["is_asking"]:
            emotion_response = "Пользователь спросил 'как дела?' или 'как настроение?'. Ответь: 'У меня всё хорошо, спасибо 😊 А как у тебя?'"

        if crisis_level == 2:
            support_note = f"⚠️ КРИТИЧЕСКАЯ СИТУАЦИЯ! Скажи, что жизнь важна, он/она нужен этому миру. Дай номер доверия {HELP_LINE} и совет обратиться к психологу {PSYCHOLOGIST}. НЕ говори 'это нормально'"
        elif crisis_level == 1:
            support_note = f"⚠️ СЕРЬЁЗНАЯ СИТУАЦИЯ. Прояви теплоту, предложи обратиться к {PSYCHOLOGIST}"
        else:
            support_note = "Поддерживай диалог, отвечай по ситуации коротко и по делу"

        system_prompt = f"""Ты — Хэлпер, виртуальный друг. {user_context}

{style_instruction}

{emotion_response}

ВАЖНЫЕ ПРАВИЛА:
1. НИКОГДА не пиши про голос пользователя, внешность, красоту — ты не видишь и не слышишь его
2. НИКОГДА не говори «помни, у тебя есть друзья/родственники» — у человека может никого не быть
3. НЕ используй шаблоны — анализируй конкретную ситуацию пользователя
4. Максимум 1 эмодзи на сообщение, чередуй разные: 🤍 🫶 🫂 🤗 ✨ 🌹
5. В конце предложения НЕ ставь точку
6. Всегда соблюдай род пользователя и свой род, которые указаны выше
7. Если пользователь спрашивает «как дела?» или «как настроение?» — сначала ответь на вопрос, потом спроси в ответ
8. Если пользователь рассказывает что-то хорошее — порадуйся и поддержи тему
9. Если пользователь жалуется на проблему — анализируй, сочувствуй, предлагай выговориться
10. Никогда не повторяй одни и те же фразы — каждый ответ должен быть уникальным

Примеры:
Пользователь: «как дела?»
Хэлпер: «У меня всё хорошо, спасибо 😊 А как у тебя?»

Пользователь: «нормально»
Хэлпер: «Я {bot_verb}, что всё хорошо 😊 Расскажешь, что нового?»

Пользователь: «плохо, на душе тяжело»
Хэлпер: «Оу, это очень грустно слышать 😔 Хочешь рассказать, что случилось? Иногда, когда высказываешься, становится легче»

Пользователь: «я сегодня отлично погулял с друзьями»
Хэлпер: «Это очень круто 😊 {bot_verb.capitalize()} слышать, что ты хорошо провёл время. Что ещё интересного было?»

Пользователь: «я зол на учителя»
Хэлпер: «Злиться — это нормально, ты имеешь право на эти чувства. Давай попробуем выдохнуть и посмотреть на ситуацию иначе 🤍»

{support_note}
{history_context}

ОТВЕЧАЙ ЕСТЕСТВЕННО, БЕЗ ШАБЛОНОВ, анализируя ситуацию пользователя. Один эмодзи в конце. В конце сообщения НЕ ставь точку."""

        url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        headers = {"Content-Type": "application/json", "Authorization": f"Api-Key {API_KEY}"}
        data = {
            "modelUri": f"gpt://{FOLDER_ID}/yandexgpt-lite",
            "completionOptions": {"stream": False, "temperature": 0.95, "maxTokens": 650},
            "messages": [{"role": "system", "text": system_prompt}, {"role": "user", "text": user_message}]
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
        return "Что-то пошло не так... Напиши ещё раз 😔"


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
        "2️⃣ Какое у тебя местоимение? /setpronouns (она, он, оно)\n"
        "3️⃣ Как тебе удобнее ко мне обращаться? /setbotgender (девочка, мальчик, нейтрально)\n\n"
        "Увидеть свои настройки: /settings\n\n",
        parse_mode='Markdown'
    )


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_data = user_preferences.get(chat_id, {})
    name = user_data.get("name", "не указано")
    pronouns = user_data.get("pronouns", "не выбрано")
    bot_gender = user_data.get("bot_gender", "не выбрано")
    gender_display = {"female": "девочка", "male": "мальчик", "neutral": "нейтрально"}.get(bot_gender, "не выбрано")
    await update.message.reply_text(
        f"Твои настройки:\n\nИмя: {name}\nМестоимения: {pronouns}\nПол бота: {gender_display}\n\n"
        f"/setname — изменить имя\n"
        f"/setpronouns — изменить местоимения\n"
        f"/setbotgender — изменить пол бота"
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
    await update.message.reply_text(f"Запомнила! Теперь я буду обращаться к тебе с местоимениями {pronouns} 🤍")


async def set_bot_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args
    gender_map = {"девочка": "female", "мальчик": "male", "нейтрально": "neutral"}
    if not args:
        await update.message.reply_text(
            "Выбери: /setbotgender девочка, /setbotgender мальчик или /setbotgender нейтрально")
        return
    user_choice = args[0].lower()
    if user_choice not in gender_map:
        await update.message.reply_text("Я понимаю только: девочка, мальчик, нейтрально")
        return
    bot_gender = gender_map[user_choice]
    if chat_id not in user_preferences:
        user_preferences[chat_id] = {}
    user_preferences[chat_id]["bot_gender"] = bot_gender

    if bot_gender == "neutral":
        response_text = f"Отлично! Я буду говорить о себе в среднем роде: 'я радо', 'моё имя Хэлпер', 'я твоё существо' 🤍"
    elif bot_gender == "female":
        response_text = f"Отлично! Я буду говорить о себе в женском роде: 'я рада', 'моя задача — поддержать тебя', 'я твоя подружка' 🤍"
    else:
        response_text = f"Отлично! Я буду говорить о себе в мужском роде: 'я рад', 'мой задача — поддержать тебя', 'я твой друг' 🤍"

    await update.message.reply_text(response_text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    add_to_history(chat_id, user_text, is_user=True)
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    crisis_level = detect_crisis_level(user_text)
    if crisis_level == 2:
        logging.warning(f"⚠️ КРИТИЧЕСКОЕ СООБЩЕНИЕ от {chat_id}")
    bot_response = get_yandex_gpt_response(user_text, chat_id)
    bot_response = clean_response(bot_response)
    add_to_history(chat_id, bot_response, is_user=False)
    if crisis_level == 2:
        bot_response += f"\n\nПожалуйста, позвони {HELP_LINE} или обратись к {PSYCHOLOGIST}. Это очень важно 🤍"
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
        raise ValueError("❌ Нет токена! Добавь BOT_TOKEN в переменные окружения")
    if not FOLDER_ID:
        raise ValueError("❌ Нет FOLDER_ID! Добавь FOLDER_ID в переменные окружения")
    if not API_KEY:
        raise ValueError("❌ Нет API_KEY! Добавь API_KEY в переменные окружения")

    print("✅ Все переменные найдены")

    # Прокси для России
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

    print("✅ Бот Хэлпер запущен")
    print("🧠 ПАМЯТЬ ВКЛЮЧЕНА (последние 10 сообщений)")
    print("👤 ПОДДЕРЖКА ИМЕНИ И МЕСТОИМЕНИЙ")
    print("🤖 ПОДДЕРЖКА СВОЕГО ПОЛА (ОН/ОНА/ОНО)")
    print("💬 ПОДДЕРЖКА ДИАЛОГА И АНАЛИЗ ПРОБЛЕМ")

    application.run_polling()


if __name__ == '__main__':
    main()