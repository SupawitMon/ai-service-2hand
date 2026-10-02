# AI Service ตลาดสินค้ามือสอง

- ประเมินราคา: ทายเกรดสภาพจากรูป (YOLO) + ประเมินราคา (XGBoost)
- แชทบอทถาม-ตอบ: ตัวจำแนก intent + ตอบจาก Knowledge Base (`kb/`) พร้อม session, request ID, log, metrics
- แชทบอทเจรจาต่อรอง: หน้าเว็บ `negotiation_chatbot.html` ใช้ตัวจำแนก intent เดียวกันผ่าน `/api/negotiate/intent`

**สเปกแชทบอทและผลรับงานตามเกณฑ์ SE:** [`docs/AI_CHATBOT_SPEC.md`](docs/AI_CHATBOT_SPEC.md)

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
| หน้าเว็บประเมินราคา | http://localhost:8012 |
| หน้าเว็บแชทบอทเจรจา | http://localhost:8012/negotiation_chatbot.html |
| API ประเมินราคา/เกรด | http://localhost:8012/api/... |
| API แชทบอทถาม-ตอบ | http://localhost:8012/api/chat |
| Swagger ราคา | http://localhost:8012/apidocs |
| Swagger แชทบอท | http://localhost:8013/apidocs |

บนเซิร์ฟเวอร์ เปลี่ยน `localhost` เป็น IP ของเครื่อง ใช้แค่ 2 พอร์ต: **8012** และ **8013**

คำสั่งที่ใช้บ่อย:

```bash
docker compose logs -f backend   # ดู log (เปลี่ยนเป็น chatbot ได้)
docker compose down              # ปิด
docker compose up -d --build     # อัปเดตหลังแก้โค้ดหรือเปลี่ยนโมเดล
```

## API

ทุก path เรียกผ่านพอร์ต 8012 ได้หมด

| Method | Path | ใช้ทำอะไร |
|---|---|---|
| GET | `/api/options` | รายชื่อยี่ห้อ/รุ่นทั้งหมด |
| POST | `/api/predict-grade` | ส่งรูป (form-data ชื่อ `image`) ได้เกรด A/B/C |
| POST | `/api/predict-price` | ส่ง JSON `brand`, `model`, `grade`, `accessories` ได้ช่วงราคา + ปัจจัยที่มีผล |
| POST | `/api/chat` | ส่ง JSON `message` ได้คำตอบแชทบอท |
| GET | `/api/chat/stats` | สถิติของ dataset แชทบอท |
| GET | `/api/chat/sample-questions` | ตัวอย่างคำถาม |
| POST | `/api/negotiate/intent` | ส่ง JSON `message`, `current_product` ได้ action ของแชทเจรจา |
| GET | `/api/metrics` | latency P50/P95/P99, อัตรา fallback |
| GET | `/api/kb/info` | เวอร์ชัน KB และ threshold |
| GET | `/api/logs/<request_id>` | ดู log (ต้องมี header `X-Admin-Token`) |

## รันแบบไม่ใช้ Docker

```bash
pip install -r requirements_backend.txt -r requirements_chatbot.txt
python backend_server.py    # หน้าต่างที่ 1
python chatbot_server.py    # หน้าต่างที่ 2
```

แล้วดับเบิลคลิกเปิด `mockup_ai_price.html` หรือ `negotiation_chatbot.html`

## วัดผลแชทบอท

```bash
python eval_chatbot.py                                   # ชุด dev
python eval_chatbot.py --cases tests/test_cases_blind.json --out blind
python eval_chatbot.py --url http://<IP>:8012            # วัดกับเซิร์ฟเวอร์จริง (ต้อง pip install requests)
```
ผลอยู่ที่ `reports/`

## อัปเดตข้อมูลสินค้า/ราคาของแชทบอท

แก้ `kb/price_table.json` หรือ `chatbot_dataset.json` แล้วรัน `python build_kb.py` และ `python sync_negotiation_catalog.py`

## ดู log ย้อนหลัง

คัดลอก `.env.example` เป็น `.env` แล้วตั้ง `LOG_ACCESS_TOKEN` จากนั้น `docker compose up -d` แล้วเรียก
`curl -H "X-Admin-Token: <รหัส>" http://<IP>:8012/api/logs/<request_id>` (log เก็บ 30 วันที่โฟลเดอร์ `logs/`)

## เปลี่ยนโมเดลเกรดเป็นตัวใหม่

เทรนด้วย `train_grade_v3.py` แล้วก็อป `runs/classify/grade_v3/weights/best.pt`
มาทับ `best.pt` จากนั้น `docker compose up -d --build`
