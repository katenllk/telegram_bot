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
user_preferences = {}  # {chat_id: {"name": "Аня", "pronouns": "она"}}

# Местоимения пользователя (и одновременно пол бота)
PRONOUNS_MAP = {
    "она": {
        # Для пользователя
        "user_you": "ты не обязана",
        "user_need": "нужна",
        "user_capable": "способна",
        "user_alone": "одна",
        "user_good": "хорошая",
        "user_wrote": "написала",
        # Для бота
        "bot_verb": "рада",
        "bot_ref": "подружка",
        "bot_my": "моя"
    },
    "он": {
        "user_you": "ты не обязан",
        "user_need": "нужен",
        "user_capable": "способен",
        "user_alone": "один",
        "user_good": "хороший",
        "user_wrote": "написал",
        "bot_verb": "рад",
        "bot_ref": "друг",
        "bot_my": "мой"
    },
    "оно": {
        "user_you": "ты не обязано",
        "user_need": "нужно",
        "user_capable": "способно",
        "user_alone": "одно",
        "user_good": "хорошее",
        "user_wrote": "написало",
        "bot_verb": "радо",
        "bot_ref": "существо",
        "bot_my": "моё"
    }
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
    emojis = re.findall(r'[🤍🫶❤️🫂🤗✨⭐🌹🎉😊]', text)
    if len(emojis) > 1:
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
        user_pronouns = pref.get("pronouns", "он")  # по умолчанию "он"

        # Получаем формы для местоимения пользователя
        p = PRONOUNS_MAP[user_pronouns]

        # Формы для пользователя
        user_you = p["user_you"]
        user_need = p["user_need"]
        user_capable = p["user_capable"]
        user_alone = p["user_alone"]
        user_good = p["user_good"]
        user_wrote = p["user_wrote"]

        # Формы для бота (те же, что и у пользователя)
        bot_verb = p["bot_verb"]
        bot_ref = p["bot_ref"]
        bot_my = p["bot_my"]

        user_context = f"Пользователя зовут {user_name}. " if user_name else ""
        user_context += f"Обращайся к пользователю с местоимениями {user_pronouns}. "
        user_context += f"Говори ему: '{user_you} быть идеальным(ой)', '{user_need} этому миру', 'ты {user_capable} справиться', 'ты не {user_alone}'. "
        user_context += f"Если нужно сказать 'ты молодец' — скажи 'ты {user_good}'. "
        user_context += f"Пользователь написал тебе — используй форму '{user_wrote}'. "
        user_context += f"Ты — Хэлпер, и ты говоришь о себе в том же роде, что и пользователь. "
        user_context += f"Используй фразы: 'я {bot_verb}', '{bot_my} задача — поддержать тебя', 'я твоя/твой/твоё {bot_ref}'. "
        user_context += f"Пример приветствия: 'Привет! Я {bot_verb}, что ты мне {user_wrote} 🤍 Как твои дела?'"

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
6. НИКОГДА не начинай сообщение с «Хэлпер:», «Хэлпер —», «Я, Хэлпер» — просто пиши сразу текст
7. Всегда соблюдай род пользователя и свой род — они одинаковые
8. Если пользователь спрашивает «как дела?» или «как настроение?» — сначала ответь на вопрос, потом спроси в ответ
9. Если пользователь рассказывает что-то хорошее — порадуйся и поддержи тему
10. Если пользователь жалуется на проблему — анализируй, сочувствуй, предлагай выговориться
11. Никогда не повторяй одни и те же фразы — каждый ответ должен быть уникальным

Примеры правильных ответов:
Пользователь (она): «Привет!»
Хэлпер: «Привет! Я рада, что ты мне написала 🤍 Как твои дела?»

Пользователь (он): «Привет!»
Хэлпер: «Привет! Я рад, что ты мне написал 🤍 Как твои дела?»

Пользователь (оно): «Привет!»
Хэлпер: «Привет! Я радо, что ты мне написало 🤍 Как твои дела?»

Пользователь (она): «как дела?»
Хэлпер: «У меня всё хорошо, спасибо 😊 А как у тебя?»

Пользователь (он): «плохо»
Хэлпер: «Оу, это очень грустно слышать 😔 Хочешь рассказать, что случилось?»

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
        "2️⃣ Какое у тебя местоимение? /setpronouns она (или он, оно)\n\n"
        "Увидеть свои настройки: /settings\n\n",
        parse_mode='Markdown'
    )


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_data = user_preferences.get(chat_id, {})
    name = user_data.get("name", "не указано")
    pronouns = user_data.get("pronouns", "не выбрано")
    await update.message.reply_text(
        f"Твои настройки:\n\nИмя: {name}\nМестоимения: {pronouns}\n\n"
        f"/setname — изменить имя\n"
        f"/setpronouns — изменить местоимения"
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
    # Обновляем историю, чтобы бот перестроился
    add_to_history(chat_id, f"[Смена местоимений на {pronouns}]", is_user=True)
    await update.message.reply_text(
        f"Запомнила! Теперь я буду обращаться к тебе с местоимениями {pronouns} и говорить о себе в том же роде 🤍")


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
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))

    print("✅ Бот Хэлпер запущен")
    print("🧠 ПАМЯТЬ ВКЛЮЧЕНА")
    print("👤 БОТ ПОДСТРАИВАЕТСЯ ПОД МЕСТОИМЕНИЯ ПОЛЬЗОВАТЕЛЯ")

    application.run_polling()


if __name__ == '__main__':
    main()