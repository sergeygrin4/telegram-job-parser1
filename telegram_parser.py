import os
import asyncio
import logging
import requests
from dotenv import load_dotenv
from telethon import TelegramClient, events

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("parser")

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION_PATH = os.getenv("TELETHON_SESSION", "parser.session")
BOT_API = os.getenv("BOT_API", "http://localhost:8000/post")
CHANNELS = [c.strip() for c in os.getenv("CHANNELS", "").split(",") if c.strip()]
SHARED_SECRET = os.getenv("SHARED_SECRET")

if not API_ID or not API_HASH:
    log.error("Не заданы TELEGRAM_API_ID/TELEGRAM_API_HASH.")
    raise SystemExit(1)
if not CHANNELS:
    log.warning("Переменная CHANNELS пуста. Задай список каналов через запятую.")

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
