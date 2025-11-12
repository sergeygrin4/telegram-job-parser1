import os
import asyncio
import logging
import requests
import base64
from dotenv import load_dotenv
from telethon import TelegramClient, events

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("parser")

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION_PATH = os.getenv("TELETHON_SESSION", "parser.session")
SESSION_BASE64 = os.getenv("TELETHON_SESSION_BASE64", "")
BOT_API = os.getenv("BOT_API", "http://localhost:8000/post")
CHANNELS = [c.strip() for c in os.getenv("TELEGRAM_CHANNELS", "").split(",") if c.strip()]
SHARED_SECRET = os.getenv("SHARED_SECRET")

# Пробуем загрузить session из session_loader.py
if not os.path.exists(SESSION_PATH):
    try:
        log.info("Пытаемся загрузить session из session_loader.py...")
        from session_loader import load_session
        load_session()
    except ImportError:
        log.debug("session_loader.py не найден, пропускаем")
    except Exception as e:
        log.error(f"Ошибка загрузки из session_loader: {e}")

# Декодируем Base64 сессию если есть
if SESSION_BASE64 and not os.path.exists(SESSION_PATH):
    try:
        session_data = base64.b64decode(SESSION_BASE64)
        os.makedirs(os.path.dirname(SESSION_PATH) if os.path.dirname(SESSION_PATH) else ".", exist_ok=True)
        with open(SESSION_PATH, 'wb') as f:
            f.write(session_data)
        log.info(f"✅ Сессия декодирована из Base64 и сохранена в {SESSION_PATH}")
    except Exception as e:
        log.error(f"❌ Ошибка декодирования сессии: {e}")

if not API_ID or not API_HASH:
    log.error("Не заданы TELEGRAM_API_ID/TELEGRAM_API_HASH.")
    raise SystemExit(1)
if not CHANNELS:
    log.warning("⚠️ TELEGRAM_CHANNELS пуста. Задай список каналов через запятую.")

headers = {"X-SECRET": SHARED_SECRET} if SHARED_SECRET else {}

client = TelegramClient(SESSION_PATH, API_ID, API_HASH)

def _build_link(entity, message_id: int) -> str | None:
    """
    Пытаемся сформировать ссылку на сообщение.
    Работает, если у канала есть username.
    """
    try:
        username = getattr(entity, "username", None)
        if username:
            return f"https://t.me/{username}/{message_id}"
    except Exception:
        pass
    return None

def _post_to_miniapp(chat_title: str, text: str, link: str | None):
    payload = {"chat_title": chat_title, "text": text, "link": link}
    try:
        r = requests.post(BOT_API, json=payload, headers=headers, timeout=8)
        if r.status_code != 200:
            log.warning("miniapp %s: %s", r.status_code, r.text)
    except Exception as e:
        log.exception("Ошибка POST в miniapp: %s", e)

@client.on(events.NewMessage(chats=CHANNELS if CHANNELS else None))
async def handler(event: events.NewMessage.Event):
    try:
        entity = await event.get_chat()
        chat_title = getattr(entity, "title", getattr(entity, "username", "Канал"))
        text = event.message.message or ""
        if not text.strip():
            return
        link = _build_link(entity, event.message.id)
        _post_to_miniapp(chat_title, text, link)
        log.info("Отправлено: %s (%s)", chat_title, f"link={bool(link)}")
    except Exception as e:
        log.exception("Ошибка обработки сообщения: %s", e)

async def main():
    log.info("Запуск парсера. Каналы: %s", ", ".join(CHANNELS) if CHANNELS else "(все доступные чаты не подписываются)")
    await client.start()
    log.info("Telethon подключён.")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
