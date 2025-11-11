import os
import logging
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("fb_auth_parser")

# Конфигурация
BOT_API = os.getenv("BOT_API", "http://localhost:8000/post")
SHARED_SECRET = os.getenv("SHARED_SECRET")
FB_GROUPS = os.getenv("FB_GROUPS", "").split(",")
FB_COOKIES = os.getenv("FB_COOKIES", "")  # Cookies для авторизации
KEYWORDS = os.getenv("JOB_KEYWORDS", "вакансия,работа,job,hiring").lower().split(",")

headers = {"X-SECRET": SHARED_SECRET, "Content-Type": "application/json"} if SHARED_SECRET else {"Content-Type": "application/json"}

def contains_keywords(text: str) -> bool:
    """Проверяет наличие ключевых слов"""
    if not text or not KEYWORDS:
        return True
    text_lower = text.lower()
    return any(keyword.strip() in text_lower for keyword in KEYWORDS)

def send_to_api(group_name: str, text: str, link: str = None):
    """Отправляет вакансию в API"""
    payload = {
        "chat_title": f"[FACEBOOK] {group_name}",
        "text": text,
        "link": link,
        "source_type": "facebook"
    }
    
    try:
        r = requests.post(BOT_API, json=payload, headers=headers, timeout=10)
        if r.status_code == 200:
            log.info(f"✅ Отправлено: {group_name}")
            return True
        else:
            log.warning(f"API ошибка {r.status_code}: {r.text}")
            return False
    except Exception as e:
        log.error(f"Ошибка отправки в API: {e}")
        return False

def parse_facebook_group_with_cookies(group_id: str):
    """Парсинг FB группы с авторизацией через cookies"""
    try:
        from facebook_scraper import get_posts
        
        log.info(f"Парсинг приватной FB группы: {group_id}")
        
        # Парсим cookies из переменной окружения
        cookies = {}
        if FB_COOKIES:
            # Формат: name1=value1; name2=value2
            for cookie in FB_COOKIES.split(';'):
                if '=' in cookie:
                    name, value = cookie.strip().split('=', 1)
                    cookies[name] = value
        
        if not cookies:
            log.warning("⚠️ FB_COOKIES не заданы, попытка парсинга без авторизации")
        
        # Получаем посты с cookies
        posts = get_posts(
            group=group_id,
            pages=1,
            cookies=cookies,
            options={
                "comments": False,
                "reactors": False,
                "allow_extra_requests": False
            }
        )
        
        count = 0
        for post in posts:
            try:
                text = post.get('text', '')
                post_id = post.get('post_id', '')
                time_posted = post.get('time')
                
                if not text:
                    continue
                
                # Проверяем свежесть (не старше 24 часов)
                if time_posted and isinstance(time_posted, datetime):
                    if datetime.now() - time_posted > timedelta(hours=24):
                        log.debug(f"Старый пост пропущен: {time_posted}")
                        continue
                
                # Проверяем ключевые слова
                if not contains_keywords(text):
                    log.debug(f"Нет ключевых слов: {text[:50]}")
                    continue
                
                # Формируем ссылку
                link = f"https://facebook.com/{post_id}" if post_id else None
                
                # Отправляем
                if send_to_api(group_id, text, link):
                    count += 1
                    
            except Exception as e:
                log.error(f"Ошибка обработки поста: {e}")
                continue
        
        log.info(f"✅ Обработано {count} постов из группы {group_id}")
        return count
        
    except Exception as e:
        log.error(f"Ошибка парсинга FB группы {group_id}: {e}")
        return 0

def main():
    """Главная функция"""
    log.info("🚀 Запуск Facebook парсера с авторизацией")
    log.info(f"API: {BOT_API}")
    log.info(f"Ключевые слова: {KEYWORDS}")
    log.info(f"Cookies: {'✅ Установлены' if FB_COOKIES else '❌ Не заданы'}")
    
    if not FB_GROUPS or not FB_GROUPS[0]:
        log.error("❌ FB_GROUPS не задан!")
        log.info("Добавь в .env: FB_GROUPS=group_id_1,group_id_2")
        return
    
    total = 0
    for group in FB_GROUPS:
        group = group.strip()
        if group:
            count = parse_facebook_group_with_cookies(group)
            total += count
    
    log.info(f"✅ Всего обработано {total} постов")

if __name__ == "__main__":
    main()
