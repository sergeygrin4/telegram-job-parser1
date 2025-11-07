FROM python:3.11-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование файлов приложения
COPY . .

# Создание директории для данных
RUN mkdir -p /data

# Порт будет установлен через переменную окружения PORT
EXPOSE 8000

# Запуск приложения
CMD ["python", "mini_app_bot.py"]
