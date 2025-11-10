import os
import asyncio
import logging
import hashlib
import time
from datetime import datetime, timedelta
import requests
from dotenv import load_dotenv
from telethon import TelegramClient, events
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("universal_parser")

# ==================== КОНФИГУРАЦИЯ ====================
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION_PATH = os.getenv("TELETHON_SESSION", "parser.session")
BOT_API = os.getenv("BOT_API", "http://localhost:8000/post")
SHARED_SECRET = os.getenv("SHARED_SECRET")

# Источники
TELEGRAM_CHANNELS = os.getenv("TELEGRAM_CHANNELS", "")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON", "")

# Настройки парсинга
KEYWORDS = os.getenv("JOB_KEYWORDS", "вакансия,ищу,работа,hiring,job,remote,developer,программист").lower().split(",")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_MINUTES", "5"))

# Дедупликация
seen_hashes = set()
MAX_HASH_CACHE = 10000

headers = {"X-SECRET": SHARED_SECRET, "Content-Type": "application/json"} if SHARED_SECRET else {"Content-Type": "application/json"}

# ==================== УТИЛИТЫ ====================

def hash_post(text: str, source: str) -> str:
    """Создает хеш для проверки дублей"""
    content = f"{source}:{text[:200]}"
    return hashlib.md5(content.encode()).hexdigest()

def is_duplicate(text: str, source: str) -> bool:
    """Проверяет дубликаты"""
    post_hash = hash_post(text, source)
    if post_hash in seen_hashes:
        return True
    seen_hashes.add(post_hash)
    if len(seen_hashes) > MAX_HASH_CACHE:
        seen_hashes.pop()
    return False

def contains_keywords(text: str) -> bool:
    """Проверяет наличие ключевых слов"""
    if not text or not KEYWORDS:
        return True
    text_lower = text.lower()
    return any(keyword.strip() in text_lower for keyword in KEYWORDS)

def send_to_api(chat_title: str, text: str, link: str = None, source_type: str = "telegram"):
    """Отправляет вакансию в API"""
    if is_duplicate(text, chat_title):
        log.info(f"Дубликат пропущен: {chat_title[:30]}...")
        return False
    
    if not contains_keywords(text):
        log.info(f"Не содержит ключевых слов: {text[:50]}...")
        return False
    
    payload = {
        "chat_title": f"[{source_type.upper()}] {chat_title}",
        "text": text,
        "link": link
    }
    
    try:
        r = requests.post(BOT_API, json=payload, headers=headers, timeout=10)
        if r.status_code == 200:
            log.info(f"✅ Отправлено: {chat_title} ({source_type})")
            return True
        else:
            log.warning(f"API ошибка {r.status_code}: {r.text}")
            return False
    except Exception as e:
        log.exception(f"Ошибка отправки в API: {e}")
        return False

# ==================== TELEGRAM PARSER ====================

client = None

async def init_telegram():
    """Инициализация Telegram клиента"""
    global client
    if not API_ID or not API_HASH:
        log.warning("Telegram API креды не заданы, парсинг Telegram пропущен")
        return False
    
    try:
        client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
        await client.start()
        log.info("✅ Telegram клиент подключен")
        return True
    except Exception as e:
        log.error(f"Ошибка подключения к Telegram: {e}")
        return False

def parse_telegram_channels():
    """Возвращает список Telegram каналов"""
    if not TELEGRAM_CHANNELS:
        return []
    return [c.strip() for c in TELEGRAM_CHANNELS.split(",") if c.strip()]

@events.register(events.NewMessage)
async def telegram_message_handler(event: events.NewMessage.Event):
    """Обработчик новых сообщений в Telegram"""
    try:
        entity = await event.get_chat()
        chat_title = getattr(entity, "title", getattr(entity, "username", "Unknown"))
        text = event.message.message or ""
        
        if not text.strip():
            return
        
        # Формируем ссылку
        username = getattr(entity, "username", None)
        link = f"https://t.me/{username}/{event.message.id}" if username else None
        
        send_to_api(chat_title, text, link, "telegram")
    except Exception as e:
        log.exception(f"Ошибка обработки Telegram сообщения: {e}")

# ==================== GOOGLE SHEETS PARSER ====================

def get_google_sheets_channels():
    """Получает список каналов из Google Sheets"""
    if not GOOGLE_SHEET_ID or not GOOGLE_CREDS_JSON:
        log.info("Google Sheets не настроены")
        return []
    
    try:
        # Парсим JSON креды из переменной окружения
        import json
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        
        scopes = ['https://www.googleapis.com/auth/spreadsheets.readonly']
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        
        sheet = gc.open_by_key(GOOGLE_SHEET_ID).sheet1
        records = sheet.get_all_records()
        
        channels = []
        for row in records:
            source_type = row.get('type', 'telegram').lower()
            url = row.get('url', '')
            enabled = str(row.get('enabled', 'yes')).lower() in ['yes', 'true', '1', 'да']
            
            if enabled and url:
                channels.append({'type': source_type, 'url': url})
        
        log.info(f"✅ Загружено {len(channels)} каналов из Google Sheets")
        return channels
    except Exception as e:
        log.error(f"Ошибка чтения Google Sheets: {e}")
        return []

# ==================== FACEBOOK PARSER ====================

def parse_facebook_group(group_url: str, group_name: str = None):
    """Парсит группу Facebook"""
    try:
        from facebook_scraper import get_posts
        
        # Извлекаем ID группы из URL
        group_id = group_url.split('/')[-1].split('?')[0]
        
        posts = get_posts(
            group=group_id,
            pages=1,
            options={"comments": False, "reactors": False}
        )
        
        count = 0
        for post in posts:
            text = post.get('text', '')
            post_id = post.get('post_id', '')
            time_posted = post.get('time', datetime.now())
            
            # Проверяем свежесть поста (не старше 24 часов)
            if isinstance(time_posted, datetime):
                if datetime.now() - time_posted > timedelta(hours=24):
                    continue
            
            if text:
                link = f"https://facebook.com/{post_id}" if post_id else group_url
                title = group_name or f"FB: {group_id}"
                if send_to_api(title, text, link, "facebook"):
                    count += 1
        
        if count > 0:
            log.info(f"✅ Facebook: обработано {count} постов из {group_name or group_id}")
        return count
    except Exception as e:
        log.error(f"Ошибка парсинга Facebook группы {group_url}: {e}")
        return 0

# ==================== MAIN LOOP ====================

async def periodic_check():
    """Периодическая проверка источников"""
    log.info(f"Запуск периодической проверки (интервал: {CHECK_INTERVAL} мин)")
    
    while True:
        try:
            # Получаем каналы из Google Sheets
            sheets_channels = get_google_sheets_channels()
            
            for channel in sheets_channels:
                source_type = channel['type']
                url = channel['url']
                
                if source_type == 'facebook':
                    parse_facebook_group(url, url)
                elif source_type == 'telegram':
                    # Telegram обрабатывается в реальном времени через события
                    pass
            
            await asyncio.sleep(CHECK_INTERVAL * 60)
        except Exception as e:
            log.exception(f"Ошибка в periodic_check: {e}")
            await asyncio.sleep(60)

async def main():
    """Главная функция"""
    log.info("🚀 Запуск универсального парсера")
    log.info(f"BOT_API: {BOT_API}")
    log.info(f"Ключевые слова: {KEYWORDS}")
    
    # Инициализация Telegram
    telegram_enabled = await init_telegram()
    
    if telegram_enabled:
        # Получаем каналы из переменных окружения
        env_channels = parse_telegram_channels()
        # Получаем каналы из Google Sheets
        sheets_channels = get_google_sheets_channels()
        telegram_sheets = [c['url'] for c in sheets_channels if c['type'] == 'telegram']
        
        # Объединяем
        all_telegram_channels = list(set(env_channels + telegram_sheets))
        
        if all_telegram_channels:
            log.info(f"📢 Мониторинг Telegram каналов: {', '.join(all_telegram_channels)}")
            client.add_event_handler(
                telegram_message_handler,
                events.NewMessage(chats=all_telegram_channels if all_telegram_channels else None)
            )
        else:
            log.info("📢 Мониторинг всех доступных Telegram чатов")
            client.add_event_handler(telegram_message_handler, events.NewMessage())
    
    # Запуск периодической проверки для Facebook и других источников
    await periodic_check()

if __name__ == "__main__":
    if not BOT_API:
        log.error("BOT_API не установлен!")
        exit(1)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Остановка парсера...")
