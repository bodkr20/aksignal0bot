FROM python:3.11-slim

# إعداد دليل العمل داخل الحاوية
WORKDIR /app

# نسخ ملف المتطلبات وتثبيت المكتبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات المشروع (بما فيها كود البوت)
COPY . .

# الأمر البرمجي لتشغيل البوت فوراً
CMD ["python", "bot.py"]
