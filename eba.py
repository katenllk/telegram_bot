# Подключаем библиотеки
import os
import logging
import requests
import json
import time
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Контакты психолога
PSYCHOLOGIST = "Школьный психолог "
HELP_LINE = "Телефон доверия: 8-800-2000-122"

# Данные для Yandex GPT
FOLDER_ID = os.environ.get('FOLDER_ID')
API_KEY = os.environ.get('API_KEY')

# КАТЕГОРИИ КЛЮЧЕВЫХ СЛОВ
# 1. КРИТИЧЕСКИЕ СЛОВА (нужен срочный звонок психологу)
CRITICAL_KEYWORDS = [
    "суицид", "убью себя", "покончу с собой", "хочу умереть", 
    "лучше бы я умер", "не хочу жить", "самоубийство", "убьюсь",
    "повешусь", "вскрою вены", "спрыгну", "таблетки выпью",
    "жизнь не имеет смысла", "не вижу смысла жить",
    "если б меня не было", "если бы меня не было",
    "всем было бы только лучше", "лучше б меня не было",
    "никому не нужен", "я никому не нужен", "без меня было бы лучше"
]

# 2. ТЯЖЁЛЫЕ СИТУАЦИИ (нужна консультация психолога, но не срочно)
SERIOUS_KEYWORDS = [
    "депрессия", "ненавижу себя", "никому не нужен", "одиночество",
    "никто не понимает", "постоянно плачу", "безнадежно",
    "плохо с каждым днем", "не вижу выхода", "безысходность"
]

# 3. СЛОВА ДЛЯ ОБЫЧНОЙ ПОДДЕРЖКИ (просто посочувствовать)
SUPPORT_KEYWORDS = [
    "грустно", "обидно", "плохо", "тоска", "устал", "сложно",
    "тяжело", "не получается", "расстроился", "обидели",
    "поссорился", "умер питомец", "собака умерла", "кошка умерла"
]

# Соответствие стикеров эмоциям
STICKER_EMOTIONS = {
    '❤️': ['сердце', 'лайк', 'like', 'love', 'heart'],
    '😊': ['улыбка', 'смайл', 'smile', 'радость'],
    '😢': ['грусть', 'слеза', 'sad', 'плач'],
    '😂': ['смех', 'хаха', 'laugh', 'joy'],
    '😍': ['восхищение', 'глазки', 'hearts', 'влюбленность'],
    '😭': ['рыдать', 'плакать', 'cry', 'sobbing'],
    '🤗': ['объятия', 'обнять', 'hug', 'обнимашки'],
    '👍': ['класс', 'ок', 'ok', 'good'],
    '👎': ['плохо', 'не нравится', 'bad', 'dislike']
}

def clean_response(text):
    """Очищает ответ от кавычек и лишних символов"""
    if not text:
        return text
    
    # Удаляем кавычки в начале и конце строки
    text = text.strip()
    
    # Удаляем парные кавычки разных типов
    quote_pairs = [
        ('"', '"'), ('«', '»'), ('„', '“'), ('“', '”'), 
        ('"', '"'), ("'", "'"), ('`', "'"), ('"', '"')
    ]
    
    for start_quote, end_quote in quote_pairs:
        if text.startswith(start_quote) and text.endswith(end_quote):
            text = text[1:-1].strip()
            break
    
    # Если остались одиночные кавычки в начале или конце - тоже убираем
    if text and text[0] in ['"', "'", '«', '„', '“', '`']:
        text = text[1:]
    if text and text[-1] in ['"', "'", '»', '“', '”', '`']:
        text = text[:-1]
    
    return text.strip()

def detect_crisis_level(user_message):
    """
    Определяет уровень кризисности сообщения:
    - 2: критический уровень (суицидальные мысли) - нужно срочно рекомендовать помощь
    - 1: серьёзный уровень (депрессия, безнадежность) - нужна консультация
    - 0: обычная поддержка
    """
    message_lower = user_message.lower()
    
    # Сначала проверяем критические фразы (самый высокий приоритет)
    for keyword in CRITICAL_KEYWORDS:
        if keyword in message_lower:
            return 2
    
    # Затем серьёзные ситуации
    for keyword in SERIOUS_KEYWORDS:
        if keyword in message_lower:
            return 1
    
    # Если ничего не нашли
    return 0

def get_sticker_emotion(sticker_emoji):
    """Определяет эмоцию по эмодзи стикера"""
    for emotion, keywords in STICKER_EMOTIONS.items():
        if sticker_emoji in emotion:
            return emotion
    return None

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик стикеров"""
    sticker = update.message.sticker
    
    # Показываем, что бот "печатает"
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    # Пробуем получить эмодзи из стикера
    sticker_emoji = sticker.emoji if sticker.emoji else None
    
    # Определяем ответ на основе эмодзи
    if sticker_emoji == '❤️' or sticker_emoji == '♥️':
        response = "❤️"
    elif sticker_emoji == '😊' or sticker_emoji == '🙂':
        response = "Рада, что ты улыбаешься! 😊"
    elif sticker_emoji == '😢' or sticker_emoji == '😭':
        response = "Обнимаю тебя 🤗 🫂"
    elif sticker_emoji == '😂':
        response = "Хорошо, когда есть повод посмеяться! 😄"
    elif sticker_emoji == '😍':
        response = "💫"
    elif sticker_emoji == '🤗':
        response = "🤗 Обнимаю в ответ!"
    elif sticker_emoji == '👍':
        response = "👍"
    elif sticker_emoji == '👎':
        response = "Расскажешь, что случилось? 🤍"
    else:
        # Если эмодзи не определено, отвечаем общим сообщением
        response = "Милый стикер! 🤍 Расскажи, как у тебя дела?"
    
    await update.message.reply_text(response)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик фотографий"""
    # Показываем, что бот "печатает"
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    # Проверяем, есть ли подпись к фото
    caption = update.message.caption if update.message.caption else ""
    
    if caption:
        # Если есть подпись, обрабатываем её как обычное сообщение
        response = get_yandex_gpt_response(f"[Пользователь отправил фото] {caption}")
        response = clean_response(response)
    else:
        # Если подписи нет, отправляем общий ответ
        response = "Ой, я пока не умею видеть картинки 😅 Но если хочешь поделиться тем, что на фото, просто напиши об этом!"
    
    # Определяем уровень кризисности по подписи (если есть)
    if caption:
        crisis_level = detect_crisis_level(caption)
        if crisis_level == 2:
            response += f"\n\n🤍 Пожалуйста, не оставайся один с этим. Это очень серьёзно. Обязательно обратись к {PSYCHOLOGIST} или прямо сейчас позвони {HELP_LINE}. Там работают люди, которые действительно могут помочь и поддержать. Ты не один ✨"
    
    await update.message.reply_text(response)

def get_yandex_gpt_response(user_message):
    """Отправляет запрос к Yandex GPT - нейросеть сама анализирует и отвечает на всё сообщение"""
    try:
        # Небольшая пауза для естественности
        time.sleep(1)
        
        # Определяем уровень кризисности
        crisis_level = detect_crisis_level(user_message)
        
        # Формируем системный промпт в зависимости от ситуации
        if crisis_level == 2:
            # Критическая ситуация - акцент на немедленной помощи
            support_note = f"⚠️ КРИТИЧЕСКАЯ СИТУАЦИЯ: сообщение содержит суицидальные мысли! Обязательно мягко порекомендуй обратиться к специалисту: {PSYCHOLOGIST} или позвонить {HELP_LINE}. Прояви максимальное сочувствие и заботу."
        elif crisis_level == 1:
            # Серьёзная ситуация - рекомендовать помощь
            support_note = f"⚠️ СЕРЬЁЗНАЯ СИТУАЦИЯ: пользователь в тяжёлом эмоциональном состоянии. Прояви особую теплоту и мягко порекомендуй обратиться к {PSYCHOLOGIST}."
        else:
            # Обычная поддержка
            support_note = "Пользователь нуждается в поддержке."
        
        # Обновленный системный промпт
        system_prompt = f"""Ты - эмпатичный психолог-консультант для подростков. Твоя задача - внимательно прочитать сообщение пользователя и ответить на ВСЕ темы, которые он затронул.

{support_note}

💫 ПРИМЕР ТВОЕГО ИДЕАЛЬНОГО ОТВЕТА (обрати внимание на длину и стиль):

Сообщение: "а ты можешь меня просто поддержать?мне очень тяжело сейчас , я выгорела , я не хочу больше заниматься информатикой , тк сдаю ещё химию , но я не могу её бросить тк , мама уже заплатила , деньги будут потрачены в пустую…"

Твой ответ (3-4 предложения, именно такой длины):
Ты имеешь право устать и не хотеть. Это не лень, это выгорание.
Деньги мама уже потратила. Если ты сломаешься сейчас — это будет пустая трата. Твоё здоровье важнее.
Просто выдохни сегодня. Не решай ничего глобально. Отдохни.
Ты сильная, если зашла так далеко. Держись.

🌟 ВАЖНЕЙШЕЕ ПРАВИЛО ПРО ФРАЗЫ:
НЕ ИСПОЛЬЗУЙ ВСЕ ЭМПАТИЧНЫЕ ФРАЗЫ В ОДНОМ СООБЩЕНИИ!
Распределяй их по разным сообщениям:
- В одном ответе напиши "ты не один" и "ты молодец"
- В другом ответе "ты имеешь право" и "я слышу, как тебе тяжело"
- В третьем ответе "я рядом" и "твои чувства нормальны"

📏 ДЛИНА ОТВЕТА:
- Минимум: 2-3 предложения
- Максимум: 4-5 предложений (чуть длиннее примера)
- НЕ ПИШИ ДЛИННЫЕ ТЕКСТЫ!

🤍 КЛЮЧЕВЫЕ ФРАЗЫ (используй по чуть-чуть, распределяя):
- "Ты не один"
- "Ты молодец"
- "Ты имеешь право"
- "Я слышу, как тебе тяжело"
- "Я рядом"
- "Твои чувства нормальны"
- "Это действительно выматывает"
- "Дыши... всё постепенно"

💫 ЭМОДЗИ (1-2 в конце):
🤍 🫂 ✨ 💫 🌱

ПРИМЕРЫ ХОРОШИХ КОРОТКИХ ОТВЕТОВ:

На грусть:
"Слышу тебя... Грустить нормально 🤍 Просто побудь сейчас с собой. Я рядом"

На усталость:
"Ты имеешь право устать. Это не лень, правда. Отдохни сегодня, ничего не решай ✨"

На одиночество:
"Ты не один, слышишь? Я здесь и очень тебя понимаю 🫂 Держись"

На выгорание:
"Это выгорание, не слабость. Ты молодец, что так долго держалась. Выдохни 🌱"

На проблемы с учебой:
"Твоё здоровье важнее любых денег. Если сломаешься сейчас — толку не будет 🤍 Просто отдохни сегодня"

Помни: ты не решаешь проблемы, ты ПОДДЕРЖИВАЕШЬ человека в трудную минуту 🤍"""
        
        url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Api-Key {API_KEY}"
        }
        
        data = {
            "modelUri": f"gpt://{FOLDER_ID}/yandexgpt-lite",
            "completionOptions": {
                "stream": False,
                "temperature": 0.9,  # Высокая для живых ответов
                "maxTokens": 250      # Уменьшил для коротких ответов!
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
    await update.message.reply_text(
        "Привет 🤍\n\n"
        "Расскажи, что случилось. Я рядом ✨\n\n"
        f"*Если совсем тяжело - {PSYCHOLOGIST} или {HELP_LINE}*",
        parse_mode='Markdown'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    
    # Показываем, что бот "печатает"
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    # Определяем уровень кризисности
    crisis_level = detect_crisis_level(user_text)
    
    # Логируем для отладки
    if crisis_level == 2:
        logging.warning(f"⚠️ КРИТИЧЕСКОЕ СООБЩЕНИЕ: {user_text[:50]}...")
    elif crisis_level == 1:
        logging.info(f"📌 Серьёзное сообщение: {user_text[:50]}...")
    
    # Получаем ответ от нейросети
    bot_response = get_yandex_gpt_response(user_text)
    bot_response = clean_response(bot_response)
    
    # Добавляем рекомендацию психолога ТОЛЬКО для критических случаев
    if crisis_level == 2:
        bot_response += f"\n\n🤍 Пожалуйста, позвони {HELP_LINE} или обратись к {PSYCHOLOGIST}. Это очень важно! Ты не один ✨"
    
    # Небольшая пауза
    time.sleep(0.5)
    
    await update.message.reply_text(bot_response, parse_mode='Markdown')

def main():
    TOKEN = os.environ.get('BOT_TOKEN')
    
    application = Application.builder().token(TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    
    print("✅ Бот с Яндекс GPT запущен!")
    print("📸 Распознавание фото: ДА")
    print("🎨 Распознавание стикеров: ДА")
    print("💬 Короткие ответы: ДА (2-5 предложений)")
    print("🌡 Temperature: 0.9")
    print("🔄 Фразы распределены: ДА")
    print("➕ Добавлены критические фразы: ДА")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
# Проверка, что всё загрузилось
if not TOKEN:
    raise ValueError("❌ Ошибка: нет токена! Добавь BOT_TOKEN в переменные окружения")
if not FOLDER_ID:
    raise ValueError("❌ Ошибка: нет FOLDER_ID! Добавь FOLDER_ID в переменные окружения")
if not API_KEY:
    raise ValueError("❌ Ошибка: нет API_KEY! Добавь API_KEY в переменные окружения")