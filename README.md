# AI Service ตลาดสินค้ามือสอง

- ประเมินราคา: ทายเกรดสภาพจากรูป (YOLO) + ประเมินราคา (XGBoost)
- แชทบอทถาม-ตอบ: ค้นคำตอบจาก dataset 500 ข้อ (TF-IDF)
- แชทบอทเจรจาต่อรอง: หน้าเว็บ `negotiation_chatbot.html` (คำนวณใน JavaScript ไม่ต้องใช้ server)

## รันด้วย Docker (แนะนำ)

ต้องมี Docker Desktop ก่อน จากนั้น:

```bash
git clone https://github.com/<ชื่อ-user>/<ชื่อ-repo>.git
cd <ชื่อ-repo>
docker compose up -d --build
```

ครั้งแรกใช้เวลาประมาณ 5–10 นาที (ติดตั้ง PyTorch) ครั้งต่อไปจะเร็ว

จะได้ 3 container: `ai-price-backend`, `ai-chatbot`, `ai-frontend`

| ใช้ทำอะไร | ที่อยู่ |
|---|---|
| หน้าเว็บประเมินราคา | http://localhost:8080 |
| หน้าเว็บแชทบอทเจรจา | http://localhost:8080/negotiation_chatbot.html |
| API ประเมินราคา/เกรด | http://localhost:5000 |
| API แชทบอทถาม-ตอบ | http://localhost:5001 |
| Swagger ราคา / แชทบอท | http://localhost:5000/apidocs , http://localhost:5001/apidocs |

คำสั่งที่ใช้บ่อย:

```bash
docker compose logs -f backend   # ดู log (เปลี่ยนเป็น chatbot ได้)
docker compose down              # ปิด
docker compose up -d --build     # อัปเดตหลังแก้โค้ดหรือเปลี่ยนโมเดล
```

## API

| Method | Path | ใช้ทำอะไร |
|---|---|---|
| GET | `/api/options` | รายชื่อยี่ห้อ/รุ่นทั้งหมด |
| POST | `/api/predict-grade` | ส่งรูป (form-data ชื่อ `image`) ได้เกรด A/B/C |
| POST | `/api/predict-price` | ส่ง JSON `brand`, `model`, `grade`, `accessories` ได้ช่วงราคา + ปัจจัยที่มีผล |
| POST | `/api/chat` (พอร์ต 5001) | ส่ง JSON `message` ได้คำตอบแชทบอท |
| GET | `/api/chat/stats` (พอร์ต 5001) | สถิติของ dataset แชทบอท |
| GET | `/api/chat/sample-questions` (พอร์ต 5001) | ตัวอย่างคำถาม |

## รันแบบไม่ใช้ Docker

```bash
pip install -r requirements_backend.txt -r requirements_chatbot.txt
python backend_server.py    # หน้าต่างที่ 1
python chatbot_server.py    # หน้าต่างที่ 2
```

แล้วดับเบิลคลิกเปิด `mockup_ai_price.html` หรือ `negotiation_chatbot.html`

## เปลี่ยนโมเดลเกรดเป็นตัวใหม่

เทรนด้วย `train_grade_v3.py` แล้วก็อป `runs/classify/grade_v3/weights/best.pt`
มาทับ `best.pt` จากนั้น `docker compose up -d --build`
