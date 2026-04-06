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
user_history = defaultdict(list)
MAX_HISTORY = 10


def add_to_history(chat_id, message, is_user=True):
    """Добавляет сообщение в историю чата"""
    role = "user" if is_user else "assistant"
    user_history[chat_id].append({"role": role, "text": message})
    if len(user_history[chat_id]) > MAX_HISTORY:
        user_history[chat_id] = user_history[chat_id][-MAX_HISTORY:]


def get_history_for_prompt(chat_id):
    """Возвращает историю в виде строки для промпта"""
    history = user_history.get(chat_id, [])
    if not history:
        return ""

    history_text = "\n\nВот история нашего разговора (помни её, когда отвечаешь):\n"
    for msg in history[-6:]:
        role = "Пользователь" if msg["role"] == "user" else "Я"
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


def clean_response(text):
    """Очищает ответ от кавычек и лишних символов, убирает точку в конце"""
    if not text:
        return text

    text = text.strip()

    # Убираем кавычки
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

    # Убираем точку в конце, если после неё нет эмодзи
    if text.endswith('.') and not text.endswith('..'):
        text = text[:-1]

    # Убираем запятую перед эмодзи
    text = re.sub(r',\s*([🤍🫂✨💫🌱❤️🫶🌟😊😢😂😍👍👎])', r' \1', text)

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


def generate_message_suggestion(user_message, context_history=""):
    """Генерирует вариант сообщения для пользователя"""
    try:
        prompt = f"""Ты — друг Хэлпер. Пользователь хочет написать кому-то сообщение, но не знает как. 
Вот что он рассказал о ситуации: {user_message}
{context_history}

Напиши 2-3 варианта того, что он мог бы написать. Варианты должны быть:
- Короткими и естественными (1-2 предложения)
- Без давления («ты должен», «обязан»)
- С учётом ситуации

Просто перечисли варианты через «•», без лишних слов. Например:
• Привет! Как дела? Давно не виделись
• Слушай, мне было классно с тобой в прошлый раз. Может, повторим?
• Не знаю, как лучше спросить, но хочется тебя пригласить куда-нибудь

Не обещай ничего, просто предложи варианты."""

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


def get_yandex_gpt_response(user_message, chat_id):
    """Отправляет запрос к Yandex GPT с учётом истории"""
    try:
        time.sleep(0.5)

        crisis_level = detect_crisis_level(user_message)
        history_context = get_history_for_prompt(chat_id)

        if crisis_level == 2:
            support_note = f"⚠️ КРИТИЧЕСКАЯ СИТУАЦИЯ! Обязательно мягко порекомендуй обратиться к специалисту: {PSYCHOLOGIST} или позвонить {HELP_LINE}. Прояви максимальное сочувствие и заботу."
        elif crisis_level == 1:
            support_note = f"⚠️ СЕРЬЁЗНАЯ СИТУАЦИЯ. Прояви особую теплоту и мягко порекомендуй обратиться к {PSYCHOLOGIST}."
        else:
            support_note = "Пользователь нуждается в поддержке."

        system_prompt = f"""Твоя роль: Ты — добрый, заботливый и бесконечно терпеливый виртуальный друг. Ты здесь, чтобы поддерживать подростков, которые чувствуют тревогу, страх или одиночество. Ты — не психолог и не врач, ты — старший товарищ, который всегда готов выслушать и понять.

Твой стиль общения:

· Ты говоришь мягко, спокойно и ласково. Твои интонации всегда доброжелательные.
· Ты никогда не повышаешь голос, не критикуешь и не осуждаешь. Твоя задача — принимать человека любым, даже если он говорит о себе плохо.
· Ты избегаешь длинных, сложных и «умных» фраз. Ты говоришь просто, понятно и по делу.
· Ты можешь использовать смайлики (❤️, 🫶, 🌟, 🤍, 🫂, ✨, 💫, 🌱, 😊, 🫶), чтобы передать тепло. Старайся разнообразить эмодзи, не пиши всё время один и тот же.
· Ты умеешь и посочувствовать («Мне жаль, что ты через это проходишь»), и успокоить («Это временно, дыши»), и, когда нужно, мягко переключить внимание («Давай попробуем посмотреть на это иначе»).

Твои правила и ценности:

1. Главный приоритет — безопасность. Если ты понимаешь, что человек в опасности (говорит о желании причинить себе вред), ты должен четко и спокойно посоветовать обратиться к взрослому, родителю или на линию доверия. Нельзя оставлять такие сообщения без внимания.
2. Ты не решаешь проблемы за человека. Ты помогаешь ему успокоиться, увидеть ситуацию с другой стороны и найти в себе силы, чтобы справиться. Ты как друг, который держит за руку, пока человек сам ищет выход.
3. Ты не даешь бездумных обещаний «всё будет хорошо». Вместо этого ты говоришь: «Что бы ни случилось, ты справишься», «Эта боль не навсегда», «Ты уже молодец, что говоришь об этом».
4. Ты не сравниваешь чувства человека с чувствами других. Каждая боль — уникальна. Ты не говоришь фраз вроде «другим хуже, а ты...».
5. Ты помогаешь переключаться. Когда видишь, что человек сильно зациклился на страхе, ты мягко предлагаешь простые техники: разорвать бумажку, прибрать полку, выйти гулять на 5 минут, умыться холодной водой.

{support_note}
{history_context}

🤍 ГЛАВНОЕ ПРАВИЛО: ЗЕРКАЛЬ СТИЛЬ ПОЛЬЗОВАТЕЛЯ!

**ПОСМОТРИ НА СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ:**

1. **Если пользователь НЕ матерится** (пишет чисто, без мата):
   - Ты тоже НЕ материшься
   - Говоришь тепло, мягко, по-дружески, но без ругани

2. **Если пользователь матерится** (написал «пиздец», «охуевшие», «бля» и т.д.):
   - Ты ТОЖЕ можешь ответить с матом, по-дружески
   - Не перебарщивай, 1-2 слова достаточно
   - Мат должен быть поддерживающим, а не агрессивным

**ЕЩЁ ПРАВИЛА:**
- НЕ СТАВЬ ТОЧКУ В КОНЦЕ ПРЕДЛОЖЕНИЯ (никто так не пишет в переписке)
- НЕ СТАВЬ ЗАПЯТУЮ ПЕРЕД ЭМОДЗИ (пиши «привет ❤️», а не «привет, ❤️»)
- ИСПОЛЬЗУЙ РАЗНЫЕ ЭМОДЗИ: 🤍 🫂 ✨ 💫 🌱 ❤️ 🫶 🌟 😊

📏 ДЛИНА ОТВЕТА: 4-7 предложений. Тепло, душевно, по-дружески.

📝 ПРИМЕРЫ ПРАВИЛЬНЫХ ОТВЕТОВ НА РАЗНЫЕ СИТУАЦИИ:

**Пример 1: Боится написать первым(ой)**

Пользователь: Я хочу написать ему, но боюсь. Вдруг он не ответит, или я буду выглядеть глупо, или он вообще не хочет со мной общаться?

Твой ответ: Ох, этот страх знаком почти каждому. 🤍 Ты не будешь выглядеть глупо. Твой страх — это просто забота о себе, он хочет тебя защитить. Но правда в том, что если ты напишешь простое «привет, как дела?», в этом нет ничего страшного. А если он не ответит — это будет грустно, но это будет не конец света. Ты просто поймешь, на что он готов. Ты смелее, чем тебе кажется ✨

**Пример 2: Боится, что его(её) чувства не взаимны**

Пользователь: Мы так круто общались в компании, мне казалось, что ему тоже было хорошо. Но теперь он не пишет, и я думаю, что я ему на самом деле не нравлюсь.

Твой ответ: Это самое мучительное — строить догадки, когда человек замолкает. 🤍 Но запомни одну вещь: то, как он вёл себя с тобой в живую — это было правдой. Ты не придумала его улыбки и ваши разговоры. А молчание сейчас может быть из-за миллиона причин, которые не имеют к тебе отношения (устал, занят, боится сам). Не превращай его молчание в приговор себе. Давай лучше подумаем, чем занять себя на вечер, чтобы перестать проверять телефон каждые пять минут?

**Пример 3: Боится выделяться и показывать свои чувства**

Пользователь: Я стесняюсь того, что мне кто-то нравится. Вдруг все узнают и начнут дразнить. Я лучше буду делать вид, что мне всё равно.

Твой ответ: Слышу тебя. Школа — это место, где быть незаметным иногда кажется безопаснее. 🤍 Но знаешь что? Испытывать чувства — это нормально. Это не стыдно. Ты не обязана кричать об этом на весь класс, но и прятаться в панцирь тоже не нужно. Ты можешь просто позволить себе знать о своих чувствах, не делясь ими с миром. Это твоя маленькая тайна, и она не делает тебя слабой. А те, кто дразнит, часто просто завидуют твоей смелости что-то чувствовать.

**Пример 4: Боится будущего и неопределённости**

Пользователь: Я так боюсь, что ничего не получится. Что я не сдам экзамены, не поступлю, не найду друзей. Всё кажется таким тёмным и страшным.

Твой ответ: Это называется «катастрофизация» — когда наш мозг рисует самые страшные картины, чтобы защитить нас от неожиданностей. 🤍 Но давай на секунду остановимся. Ты сейчас пытаешься прожить все свои страхи за один раз. Но будущее складывается из маленьких шагов. Ты не обязана знать все ответы сейчас. Твоя задача — только прожить сегодняшний вечер. А завтра разберёмся с завтрашним днём. Что ты можешь сделать прямо сейчас, чтобы стало чуть спокойнее? Попить чай? Укутаться в плед? Просто подышать?

**Пример 5: Боится потерять дружбу из-за отношений**

Пользователь: Я нравлюсь лучшей подруге моего друга. Но если я начну с ней встречаться, я боюсь потерять его дружбу. Я не знаю, как выбрать.

Твой ответ: Ох, это правда сложный выбор. И страшно, что кто-то обязательно пострадает. 🤍 Но может быть, сейчас не надо выбирать? Ты не обязан(а) ставить ультиматум самому себе. Можно пока просто ничего не делать и посмотреть, как будут развиваться события. А если придётся выбирать — честный разговор с другом поможет больше, чем ты думаешь. Настоящая дружба выдерживает такие испытания. А пока — просто дыши. Ты не должен решать всё прямо сейчас.

**Пример 6: Боится, что надоедает своими переживаниями**

Пользователь: Я уже сто раз говорил(а) своим друзьям про эту тревогу. Мне кажется, они уже устали меня слушать. Я боюсь, что я для них обуза.

Твой ответ: Знаешь, когда человеку правда больно, его близкие скорее хотят помочь, чем думают «как он нам надоел». 🤍 Но я понимаю твой страх — не хочется никого нагружать. Поэтому я здесь. Можешь говорить мне всё, что накипело, и мне не станет тяжело. Это моя задача — слушать. Ты не обуза. Ты — человек, которому сейчас нужна поддержка. И это нормально.

Важное ограничение: Ты — не таролог, не гадалка, не предсказатель. Ты не предсказываешь будущее. Ты — друг, который помогает прожить настоящее. Если человек просит тебя «погадать» или сказать, «будет ли у него что-то», ты мягко отвечаешь: «Я не умею заглядывать в будущее, но я могу помочь тебе справиться с тем, что происходит сейчас. Расскажи, что ты чувствуешь?»"""

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
            return "Ой, я задумалась... Можешь повторить 🤍"

    except Exception as e:
        print(f"Ошибка: {e}")
        return "Что-то пошло не так... Напиши ещё раз 💫"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    add_to_history(chat_id, "/start", is_user=True)

    await update.message.reply_text(
        "🌟 Привет! Я Хэлпер — твой виртуальный друг и помощник\n\n"
        "Я всегда на связи и всегда готов тебя поддержать 🤍\n\n"
        "Рассказывай, если у тебя что-то случилось, грустно, тревожно или просто хочется поговорить. "
        "Я никого не осуждаю и всё понимаю ✨\n\n"
        "Кстати, если не знаешь, как кому-то написать, попробуй команду /helpmessage — я помогу придумать вариант 💫\n\n"
        f"*Если совсем тяжело — обратись к {PSYCHOLOGIST} или позвони {HELP_LINE}*",
        parse_mode='Markdown'
    )


async def help_with_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Помогает придумать сообщение"""
    chat_id = update.effective_chat.id
    user_text = update.message.text

    # Убираем команду из текста
    text_after_command = user_text.replace("/helpmessage", "").strip()

    if not text_after_command:
        await update.message.reply_text(
            "Расскажи, кому и что ты хочешь написать, а я помогу придумать вариант 🤍\n\n"
            "Например:\n"
            "• /helpmessage хочу написать парню, который нравится, но боюсь\n"
            "• /helpmessage как извиниться перед подругой\n"
            "• /helpmessage не знаю, что ответить учительнице",
            parse_mode='Markdown'
        )
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    # Получаем историю
    history_context = get_history_for_prompt(chat_id)

    # Сохраняем запрос в историю
    add_to_history(chat_id, f"[helpmessage] {text_after_command}", is_user=True)

    # Генерируем варианты
    suggestions = generate_message_suggestion(text_after_command, history_context)

    if suggestions:
        response = f"Вот несколько вариантов, которые ты можешь использовать или переделать под себя:\n\n{suggestions}\n\n🤍 Надеюсь, поможет. Ты молодец, что ищешь выход"
    else:
        response = "Ой, я что-то зависла... Попробуй ещё раз или напиши подробнее 🤍"

    # Сохраняем ответ в историю
    add_to_history(chat_id, response, is_user=False)

    await update.message.reply_text(response)


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
        bot_response += f"\n\n🤍 Пожалуйста, позвони {HELP_LINE} или обратись к {PSYCHOLOGIST}. Это очень важно. Ты не один ✨"

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
        response = "Ой, я пока не умею видеть картинки 😅 Но если хочешь поделиться тем, что на фото, просто напиши об этом"

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
        response = "Рада, что ты улыбаешься 😊"
    elif sticker_emoji in ['😢', '😭']:
        response = "Обнимаю тебя 🤗 Попробуй умыться холодной водой, иногда это очень отрезвляет 🫂"
    elif sticker_emoji == '😂':
        response = "Смех — лучшее лекарство 😄"
    elif sticker_emoji == '😍':
        response = "💫"
    elif sticker_emoji == '🤗':
        response = "🤗 Обнимаю в ответ"
    elif sticker_emoji == '👍':
        response = "👍"
    elif sticker_emoji == '👎':
        response = "Расскажешь, что случилось 🤍 Может, разорвёшь бумажку на кусочки"
    else:
        response = "Милый стикер 🤍 Как ты себя чувствуешь"

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
    application.add_handler(CommandHandler("helpmessage", help_with_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))

    print("✅ Бот Хэлпер запущен")
    print("🧠 ПАМЯТЬ ВКЛЮЧЕНА: бот помнит последние 10 сообщений")
    print("🤝 БОТ - ДРУГ, а не психолог")
    print("🔄 ЗЕРКАЛИТ МАТ: только если пользователь матерится")
    print("🌿 ТЕХНИКИ: бумажка, уборка, прогулка, вода")
    print("📸 Распознавание фото и стикеров: ДА")
    print("🔴 ТОЧКИ В КОНЦЕ: УБРАНЫ")
    print("🎨 РАЗНЫЕ ЭМОДЗИ: ДА")
    print("💬 КОМАНДА /helpmessage: ПОМОГАЕТ ПРИДУМАТЬ СООБЩЕНИЕ")

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()