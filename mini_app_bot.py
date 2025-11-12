import os
import logging
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import hashlib
import requests

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

# Инициализация БД
def init_db():
    """Инициализация базы данных"""
    try:
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
        logger.info("✅ База данных инициализирована")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

def send_telegram_message(chat_id: str, message: str):
    """Отправка сообщения через Telegram Bot API"""
    if not BOT_TOKEN:
        return False
    
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"❌ Ошибка отправки в Telegram: {e}")
        return False

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok", "service": "telegram-job-parser"}), 200

@app.route('/post', methods=['POST'])
def post_job():
    """Endpoint для получения вакансий от парсера"""
    # Проверка секретного ключа
    secret = request.headers.get('X-SECRET')
    if secret != SHARED_SECRET:
        logger.warning(f"❌ Неверный секрет: {secret}")
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        data = request.json
        chat_title = data.get('chat_title', 'Неизвестный канал')
        text = data.get('text', '')
        link = data.get('link', '')
        source_type = data.get('source_type', 'telegram')
        
        logger.info(f"📥 Получено от парсера: {chat_title} - {text[:50]}...")
        
        # Создаем хеш для дедупликации
        content = f"{chat_title}:{text[:200]}"
        content_hash = hashlib.md5(content.encode()).hexdigest()
        
        # Сохранение в БД
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'INSERT INTO jobs (chat_title, text, link, content_hash, source_type) VALUES (?, ?, ?, ?, ?)',
                (chat_title, text, link, content_hash, source_type)
            )
            conn.commit()
            logger.info(f"✅ Сохранено в БД")
        except sqlite3.IntegrityError:
            conn.close()
            logger.info(f"⚠️ Дубликат пропущен")
            return jsonify({"status": "duplicate"}), 200
        
        conn.close()
        
        # Отправка уведомления менеджеру
        if MANAGER_CHAT_ID and BOT_TOKEN:
            source_emoji = {"telegram": "📱", "facebook": "📘", "google": "📊"}.get(source_type, "📋")
            message = f"{source_emoji} <b>Новая вакансия</b>\n\n"
            message += f"📢 {chat_title}\n"
            message += f"📝 {text[:200]}{'...' if len(text) > 200 else ''}\n"
            if link:
                message += f"🔗 {link}\n"
            
            if send_telegram_message(MANAGER_CHAT_ID, message):
                logger.info(f"✉️ Уведомление отправлено")
            else:
                logger.warning(f"⚠️ Не удалось отправить уведомление")
        
        return jsonify({"status": "success"}), 200
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/jobs', methods=['GET'])
def get_jobs():
    """Получение списка вакансий"""
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
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/channels', methods=['GET'])
def get_channels():
    """Получение списка каналов"""
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
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/channels', methods=['POST'])
def add_channel():
    """Добавление канала"""
    try:
        data = request.json
        url = data.get('url', '').strip()
        source_type = data.get('source_type', 'telegram').lower()
        
        if not url:
            return jsonify({"error": "URL required"}), 400
        
        # Нормализация URL
        if source_type == 'telegram':
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
            return jsonify({"error": "Already exists"}), 409
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
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
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/')
def root():
    """Главная страница"""
    return send_from_directory('static', 'index.html')

@app.route('/<path:path>')
def static_files(path):
    """Статические файлы"""
    return send_from_directory('static', path)

if __name__ == '__main__':
    logger.info(f"🚀 Запуск на порту {PORT}")
    logger.info(f"🌐 URL: {WEB_APP_URL}")
    logger.info(f"📊 БД: {DB_PATH}")
    logger.info(f"🔐 Секрет: {'✅' if SHARED_SECRET != 'default-secret-key' else '❌'}")
    
    # Инициализация БД
    init_db()
    
    # Запуск Flask
    app.run(host='0.0.0.0', port=PORT, debug=False)
