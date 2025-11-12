"""
Session loader для Railway
Этот файл содержит Base64 закодированную сессию.
При запуске декодирует и создает parser.session файл.
"""

import base64
import os

# ВСТАВЬ СЮДА СВОЮ BASE64 СТРОКУ (разбей на части по 1000 символов)
SESSION_B64_PART1 = ""
SESSION_B64_PART2 = ""
SESSION_B64_PART3 = ""
SESSION_B64_PART4 = ""
SESSION_B64_PART5 = ""
# Добавь больше частей если нужно

def load_session():
    """Загружает session из Base64 частей"""
    # Объединяем части
    session_b64 = (
        SESSION_B64_PART1 + 
        SESSION_B64_PART2 + 
        SESSION_B64_PART3 + 
        SESSION_B64_PART4 + 
        SESSION_B64_PART5
    )
    
    if not session_b64:
        print("⚠️ Session данные не найдены в session_loader.py")
        return False
    
    try:
        # Декодируем Base64
        session_data = base64.b64decode(session_b64)
        
        # Определяем путь
        session_path = os.getenv("TELETHON_SESSION", "parser.session")
        
        # Создаем директорию если нужно
        session_dir = os.path.dirname(session_path)
        if session_dir:
            os.makedirs(session_dir, exist_ok=True)
        
        # Сохраняем файл
        with open(session_path, 'wb') as f:
            f.write(session_data)
        
        print(f"✅ Session успешно загружен: {session_path}")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка загрузки session: {e}")
        return False

if __name__ == "__main__":
    load_session()
