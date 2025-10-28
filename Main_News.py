import asyncio
import json
from dotenv import load_dotenv
import os
import requests
import feedparser
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
import pytz
load_dotenv()

# ------------------ CONFIG ------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
NEWSDATA_API_KEY = os.env("NEWSDATA_API_KEY")
THENEWSAPI_KEY = os.env("THENEWSAPI_KEY")
SUBSCRIBERS_FILE = "subscribers.json"
NEWS_TRACKER_FILE = "news_tracker.json"

ADMIN_CHAT_ID = "1601297908"

NEWSDATA_URL = "https://newsdata.io/api/1/news"
THENEWSAPI_URL = "https://newsapi.org/v2/top-headlines"

IST = pytz.timezone("Asia/Kolkata")

# ------------------ FILE HELPERS ------------------
def load_json(file):
    if not os.path.exists(file):
        return {}
    try:
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ------------------ IMPORTANT: load subscribers globally ------------------
subscribers = load_json(SUBSCRIBERS_FILE)  # <-- ensures 'subscribers' exists before any handler uses it

# Load existing data
news_tracker = load_json(NEWS_TRACKER_FILE)

# ------------------ NEWS FETCHING ------------------
def fetch_from_newsdata(country="in", language="en"):
    try:
        params = {"apikey": NEWSDATA_API_KEY, "country": country, "language": language, "category": "general"}
        r = requests.get(NEWSDATA_URL, params=params, timeout=10)
        data = r.json() if r.status_code == 200 else {}
        return data.get("results", [])
    except Exception as e:
        print(f"⚠️ NewsData.io fetch error: {e}")
        return []

def fetch_from_thenewsapi(country="in"):
    try:
        params = {"apiKey": THENEWSAPI_KEY, "country": country, "pageSize": 10}
        r = requests.get(THENEWSAPI_URL, params=params, timeout=10)
        data = r.json()
        return data.get("articles", [])
    except Exception as e:
        print(f"⚠️ TheNewsAPI fetch error: {e}")
        return []
    print(f"🌐 Fetching news for country={country}")
    print(f"➡️ Status Code: {r.status_code}")

# ------------------ RSS SOURCES ------------------
def fetch_rss_india():
    """Fetch India news headlines."""
    feeds = [
        "https://timesofindia.indiatimes.com/rssfeeds/-2128936835.cms",
        "https://www.thehindu.com/news/national/feeder/default.rss",
        "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml",
        "https://indianexpress.com/section/india/feed/"
    ]
    all_items = []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                all_items.append({"title": entry.title, "link": entry.link})
        except Exception as e:
            print(f"⚠️ RSS India fetch failed: {e}")
    return all_items

def fetch_rss_global():
    feeds = [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "http://rss.cnn.com/rss/edition_world.rss",
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://www.theguardian.com/world/rss",
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "https://rss.dw.com/rdf/rss-en-world"
    ]
    all_items = []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            if not feed.entries:
                print(f"⚠️ Empty feed: {url}")
                continue
            for entry in feed.entries[:5]:
                all_items.append({"title": entry.title, "link": entry.link})
        except Exception as e:
            print(f"⚠️ RSS Global fetch failed for {url}: {e}")
    return all_items

def fetch_from_rss(category="india"):
    """Return India or Global headlines based on category."""
    if category.lower() == "world":
        news_items = fetch_rss_global()
    else:
        news_items = fetch_rss_india()
    unique = {item["link"]: item for item in news_items}.values()
    return list(unique)

def fetch_trending_news(country="in", language="en"):
    try:
        params = {"apikey": NEWSDATA_API_KEY, "country": country, "language": language}
        r = requests.get(NEWSDATA_URL, params=params, timeout=10)
        data = r.json()
        return data.get("results", [])[:10]
    except Exception as e:
        print(f"⚠️ Failed to fetch trending news: {e}")
        return []

# ------------------ UI HELPERS ------------------
def get_main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇮🇳 India", callback_data="india_news"),
            InlineKeyboardButton("🌎 World", callback_data="world_news")
        ],
        [
            InlineKeyboardButton("🔥 Trending", callback_data="show_trending"),
            InlineKeyboardButton("🌐 Language", callback_data="select_language")
        ]
    ])

def get_language_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton("🇮🇳 Hindi", callback_data="lang_hi")],
        [InlineKeyboardButton("🧡 Bengali", callback_data="lang_bn")],
        [InlineKeyboardButton("💜 Telugu", callback_data="lang_te")],
        [InlineKeyboardButton("❤️ Tamil", callback_data="lang_ta")],
        [InlineKeyboardButton("💙 Kannada", callback_data="lang_kn")]
    ])

def get_persistent_menu():
    keyboard = [
        [KeyboardButton("🇮🇳 India"), KeyboardButton("🌎 World")],
        [KeyboardButton("🔥 Trending"), KeyboardButton("🌐 Language")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

# ------------------ TRACKER HELPERS ------------------
def mark_news_sent(user_id, category, url):
    user_id = str(user_id)
    if user_id not in news_tracker:
        news_tracker[user_id] = {}
    if category not in news_tracker[user_id]:
        news_tracker[user_id][category] = []
    if url not in news_tracker[user_id][category]:
        news_tracker[user_id][category].append(url)
        save_json(NEWS_TRACKER_FILE, news_tracker)

def is_news_sent(user_id, category, url):
    return url in news_tracker.get(str(user_id), {}).get(category, [])

# ------------------ TELEGRAM COMMANDS ------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user = update.effective_user

    if chat_id not in subscribers:
        subscribers[chat_id] = {
            "name": user.full_name,
            "username": user.username or "unknown",
            "country": "in",
            "language": "en",
            "subscribed": True,
            "joined": datetime.now().isoformat()
        }
        save_json(SUBSCRIBERS_FILE, subscribers)
        print(f"✅ New subscriber added: {chat_id} ({user.first_name})")

    total = len(subscribers)
    msg = (
        f"👋 Hi {user.first_name}!\n"
        f"Welcome to *Breaking News Bot!*\n\n"
        f"📊 *Total Subscribers:* {total}\n\n"
        f"Choose what type of news you want 👇"
    )

    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_persistent_menu())
    await update.message.reply_text("Tap one of the options below:", reply_markup=get_main_menu())

# ------------------ LANGUAGE HANDLERS ------------------
async def select_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("🌐 Choose your preferred language:", reply_markup=get_language_menu())

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    lang_code = query.data.split("_")[1]
    chat_id = str(update.effective_chat.id)
    subscribers[chat_id]["language"] = lang_code
    save_json(SUBSCRIBERS_FILE, subscribers)
    lang_names = {"en": "English", "hi": "Hindi", "bn": "Bengali", "te": "Telugu", "ta": "Tamil", "kn": "Kannada"}
    await query.answer()
    await query.message.reply_text(
        f"✅ Language changed to *{lang_names.get(lang_code, 'English')}*!",
        parse_mode="Markdown",
        reply_markup=get_main_menu()
    )

# ------------------ SHOW NEWS ------------------
async def show_news(update_or_context, context: ContextTypes.DEFAULT_TYPE, country="in", category="general"):
    send_with_chat_id = False
    articles = []  # ✅ Ensure the variable always exists

    if isinstance(update_or_context, Update):
        sender = update_or_context.callback_query.message.reply_text if update_or_context.callback_query else update_or_context.message.reply_text
        chat_id = str(update_or_context.effective_chat.id)
    else:
        send_with_chat_id = True
        chat_id = str(update_or_context)
        sender = context.bot.send_message

    # 🌐 LANGUAGE FEATURE: use user's saved language
    lang = subscribers.get(chat_id, {}).get("language", "en")

    try:
        # Try NewsData first
        articles = fetch_from_newsdata(country=country, language=lang)
        if not articles:
            print(f"ℹ️ Fallback: Using TheNewsAPI for {country}")
            articles = fetch_from_thenewsapi(country=country)

        # 📰 Add RSS support
        if country == "in":
            articles.extend(fetch_rss_india())
        elif country == "us":
            print("🌎 Fallback: Using global RSS feeds")
            articles.extend(fetch_rss_global())

    except Exception as e:
        print(f"⚠️ show_news() fetch error: {e}")
        articles = []

    # ---------------------- Deduplicate ----------------------
    seen = set()
    unique_articles = []
    for a in articles:
        link = a.get("link") or a.get("url")
        if link and link not in seen:
            seen.add(link)
            unique_articles.append(a)
    articles = unique_articles

    # ---------------------- Filter sent news ----------------------
    new_articles = []
    for a in articles:
        link = a.get("link") or a.get("url")
        if link and not is_news_sent(chat_id, category, link):
            new_articles.append(a)

    # ---------------------- Send ----------------------
    if not new_articles:
        msg = "⚠️ No new news available right now."
        if send_with_chat_id:
            await sender(chat_id, msg, reply_markup=get_persistent_menu())
        else:
            await sender(msg, reply_markup=get_persistent_menu())
        return

    text = f"📰 *Top Headlines ({'India' if country == 'in' else 'World'})*\n\n"
    for a in new_articles[:10]:
        title = a.get("title")
        link = a.get("link") or a.get("url")
        if title and link:
            text += f"• [{title}]({link})\n"
            mark_news_sent(chat_id, category, link)

    if send_with_chat_id:
        await sender(chat_id, text, parse_mode="Markdown", reply_markup=get_persistent_menu())
    else:
        await sender(text, parse_mode="Markdown", reply_markup=get_persistent_menu())


# ------------------ TRENDING ------------------
async def show_trending(update_or_context, context: ContextTypes.DEFAULT_TYPE):
    send_with_chat_id = False
    if isinstance(update_or_context, Update):
        sender = update_or_context.callback_query.message.reply_text if update_or_context.callback_query else update_or_context.message.reply_text
        chat_id = str(update_or_context.effective_chat.id)
    else:
        send_with_chat_id = True
        chat_id = str(update_or_context)
        sender = context.bot.send_message

    lang = subscribers.get(chat_id, {}).get("language", "en")
    articles = fetch_trending_news("in", language=lang)
    new_articles = [a for a in articles if not is_news_sent(chat_id, "trending", a.get("link") or a.get("url"))]

    if not new_articles:
        msg = "⚠️ No new trending news available right now."
        await sender(chat_id, msg, reply_markup=get_persistent_menu()) if send_with_chat_id else await sender(msg, reply_markup=get_persistent_menu())
        return

    text = "🔥 *Trending News*\n\n"
    for a in new_articles[:10]:
        title = a.get("title")
        link = a.get("link") or a.get("url")
        if title and link:
            text += f"• [{title}]({link})\n"
            mark_news_sent(chat_id, "trending", link)

    await sender(chat_id, text, parse_mode="Markdown", reply_markup=get_persistent_menu()) if send_with_chat_id else await sender(text, parse_mode="Markdown", reply_markup=get_persistent_menu())

# ------------------ BUTTON HANDLER ------------------
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    if data == "india_news":
        await show_news(update, context, country="in")
    elif data == "world_news":
        await show_news(update, context, country="us")
    elif data == "show_trending":
        await show_trending(update, context)
    elif data == "select_language":
        await select_language(update, context)
    elif data.startswith("lang_"):
        await set_language(update, context)

# ------------------ TEXT HANDLER ------------------
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if "india" in text:
        await show_news(update, context, country="in")
    elif "world" in text:
        await show_news(update, context, country="us")
    elif "trending" in text:
        await show_trending(update, context)
    elif "language" in text:
        await update.message.reply_text("🌐 Choose your preferred language:", reply_markup=get_language_menu())
    else:
        await update.message.reply_text("Please choose an option from the menu 👇", reply_markup=get_persistent_menu())

# ------------------ AUTO UPDATES ------------------
async def scheduled_news(context: ContextTypes.DEFAULT_TYPE):
    # Reload subscribers from file each run so changes (subscribe/unsubscribe) are respected without restarting
    global subscribers
    subscribers = load_json(SUBSCRIBERS_FILE)  # <-- reload before sending

    for chat_id, info in list(subscribers.items()):
        if not info.get("subscribed"):
            continue
        try:
            await show_news(chat_id, context, country="in")
            await show_trending(chat_id, context)
        except Exception as e:
            print(f"⚠️ Error sending scheduled news to {chat_id}: {e}")

# ------------------ SUBSCRIBER COUNT ------------------
async def subscribers_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if chat_id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ You are not authorized to view this command.")
        return
    total = len(subscribers)
    active = sum(1 for s in subscribers.values() if s.get("subscribed"))
    await update.message.reply_text(
        f"👥 *Total Subscribers:* {total}\n✅ *Active:* {active}",
        parse_mode="Markdown"
    )

# ------------------ MAIN ------------------
def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("subscribers", subscribers_count))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.job_queue.run_repeating(scheduled_news, interval=3600, first=5)
    print("🚀 Breaking News Bot Running with Auto Updates every 60 minutes...")
    app.run_polling()

if __name__ == "__main__":
    main()
