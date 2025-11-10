import os
import logging
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import asyncio
from threading import Thread
import sqlite3
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv('BOT_TOKEN')
MANAGER_CHAT_ID = os.getenv('MANAGER_CHAT_ID')
SHARED_SECRET = os.getenv('SHARED_SECRET', 'default-secret-key')
PORT = int(os.getenv('PORT', 8000))
WEB_APP_URL = os.getenv('WEB_APP_URL', 'http://localhost:8000')
DB_PATH = os.getenv('DB_PATH', 'jobs.db')

app = Flask(__name__, static_folder='static')
CORS(app)

# Глобальная переменная для бота
bot_app = None

# Инициализация БД
def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_title TEXT,
            text TEXT,
            link TEXT,
            content_hash TEXT UNIQUE,
            source_type TEXT DEFAULT 'telegram',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            source_type TEXT DEFAULT 'telegram',
            enabled INTEGER DEFAULT 1,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_content_hash ON jobs(content_hash)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON jobs(created_at DESC)')
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start с кнопкой для открытия мини-апа"""
    keyboard = {
        "inline_keyboard": [[
            {
                "text": "🔍 Открыть поиск вакансий",
                "web_app": {"url": f"{WEB_APP_URL}/index.html"}
            }
        ]]
    }
    
    await update.message.reply_text(
        "👋 Привет! Нажми на кнопку ниже, чтобы открыть поиск вакансий:",
        reply_markup=keyboard
    )

async def send_telegram_message(chat_id: str, message: str):
    """Отправка сообщения через Telegram бота"""
    if bot_app and bot_app.bot:
        try:
            await bot_app.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode='HTML'
            )
            return True
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения: {e}")
            return False
    return False

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok", "service": "telegram-job-parser"})

@app.route('/post', methods=['POST'])
def post_job():
    """Endpoint для получения вакансий от парсера"""
    # Проверка секретного ключа
    secret = request.headers.get('X-SECRET')
    if secret != SHARED_SECRET:
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        import hashlib
        
        data = request.json
        chat_title = data.get('chat_title', 'Неизвестный канал')
        text = data.get('text', '')
        link = data.get('link', '')
        source_type = data.get('source_type', 'telegram')
        
        # Создаем хеш для дедупликации
        content = f"{chat_title}:{text[:200]}"
        content_hash = hashlib.md5(content.encode()).hexdigest()
        
        # Сохранение в БД с проверкой дубликатов
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'INSERT INTO jobs (chat_title, text, link, content_hash, source_type) VALUES (?, ?, ?, ?, ?)',
                (chat_title, text, link, content_hash, source_type)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            logger.info(f"Дубликат пропущен: {chat_title[:30]}...")
            return jsonify({"status": "duplicate", "message": "Job already exists"}), 200
        
        conn.close()
        
        # Формирование сообщения для менеджера
        source_emoji = {"telegram": "📱", "facebook": "📘", "google": "📊"}.get(source_type, "📋")
        message = f"{source_emoji} <b>Новая вакансия</b>\n\n"
        message += f"📢 Источник: {chat_title}\n"
        message += f"📝 Текст: {text[:200]}{'...' if len(text) > 200 else ''}\n"
        if link:
            message += f"🔗 Ссылка: {link}\n"
        
        # Отправка сообщения
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            send_telegram_message(MANAGER_CHAT_ID, message)
        )
        loop.close()
        
        if result:
            return jsonify({"status": "success"}), 200
        else:
            return jsonify({"error": "Failed to send message"}), 500
            
    except Exception as e:
        logger.error(f"Ошибка обработки запроса: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/jobs', methods=['GET'])
def get_jobs():
    """Получение списка вакансий для мини-апа"""
    try:
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id, chat_title, text, link, created_at FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?',
            (limit, offset)
        )
        jobs = cursor.fetchall()
        
        cursor.execute('SELECT COUNT(*) FROM jobs')
        total = cursor.fetchone()[0]
        
        conn.close()
        
        return jsonify({
            "jobs": [
                {
                    "id": job[0],
                    "chat_title": job[1],
                    "text": job[2],
                    "link": job[3],
                    "created_at": job[4]
                }
                for job in jobs
            ],
            "total": total
        })
    except Exception as e:
        logger.error(f"Ошибка получения вакансий: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/channels', methods=['GET'])
def get_channels():
    """Получение списка отслеживаемых каналов"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT id, url, source_type, enabled, added_at FROM channels ORDER BY added_at DESC')
        channels = cursor.fetchall()
        conn.close()
        
        return jsonify({
            "channels": [
                {
                    "id": ch[0],
                    "url": ch[1],
                    "source_type": ch[2],
                    "enabled": bool(ch[3]),
                    "added_at": ch[4]
                }
                for ch in channels
            ]
        })
    except Exception as e:
        logger.error(f"Ошибка получения каналов: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/channels', methods=['POST'])
def add_channel():
    """Добавление канала для отслеживания"""
    try:
        data = request.json
        url = data.get('url', '').strip()
        source_type = data.get('source_type', 'telegram').lower()
        
        if not url:
            return jsonify({"error": "URL is required"}), 400
        
        # Нормализация URL
        if source_type == 'telegram':
            # Извлекаем username из ссылки
            import re
            match = re.search(r't\.me/([a-zA-Z0-9_]+)', url)
            if match:
                url = match.group(1)
            url = url.lstrip('@')
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO channels (url, source_type) VALUES (?, ?)',
                (url, source_type)
            )
            conn.commit()
            channel_id = cursor.lastrowid
            conn.close()
            
            return jsonify({
                "status": "success",
                "channel": {
                    "id": channel_id,
                    "url": url,
                    "source_type": source_type
                }
            })
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({"error": "Channel already exists"}), 409
            
    except Exception as e:
        logger.error(f"Ошибка добавления канала: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/channels/<int:channel_id>', methods=['DELETE'])
def delete_channel(channel_id):
    """Удаление канала"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM channels WHERE id = ?', (channel_id,))
        conn.commit()
        conn.close()
        
        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"Ошибка удаления канала: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/')
def root():
    """Главная страница"""
    return send_from_directory('static', 'index.html')

@app.route('/<path:path>')
def static_files(path):
    """Статические файлы"""
    return send_from_directory('static', path)

def run_flask():
    """Запуск Flask сервера"""
    app.run(host='0.0.0.0', port=PORT, debug=False)

async def run_bot():
    """Запуск Telegram бота"""
    global bot_app
    
    bot_app = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрация обработчиков
    bot_app.add_handler(CommandHandler("start", start_command))
    
    # Запуск бота
    await bot_app.initialize()
    await bot_app.start()
    logger.info("Бот запущен")
    
    # Держим бота активным
    await bot_app.updater.start_polling()
    await asyncio.Event().wait()

def main():
    """Главная функция запуска"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен!")
        return
    
    if not MANAGER_CHAT_ID:
        logger.error("MANAGER_CHAT_ID не установлен!")
        return
    
    # Инициализация БД
    init_db()
    
    logger.info(f"Запуск сервера на порту {PORT}")
    logger.info(f"Web App URL: {WEB_APP_URL}")
    
    # Запуск Flask в отдельном потоке
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Запуск бота
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Остановка сервера...")

if __name__ == '__main__':
    main()
