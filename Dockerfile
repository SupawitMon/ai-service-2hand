FROM python:3.11-slim

# ไลบรารีระบบที่ opencv (ใช้โดย ultralytics/YOLO) ต้องการ
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ติดตั้ง PyTorch แบบ CPU ก่อน (เล็กกว่าเวอร์ชัน GPU หลายเท่า)
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

COPY requirements_backend.txt .
RUN pip install --no-cache-dir -r requirements_backend.txt

# โค้ด + โมเดลที่ backend ใช้จริง
COPY backend_server.py product_lookup.json price_model.json price_model_categories.pkl best.pt ./

EXPOSE 5000
ENV FLASK_DEBUG=0 PYTHONUNBUFFERED=1

# 1 worker (โหลดโมเดลครั้งเดียว) + หลาย thread รองรับหลาย request พร้อมกัน
CMD ["gunicorn", "-w", "1", "--threads", "4", "--timeout", "120", "-b", "0.0.0.0:5000", "backend_server:app"]
