# 2HandToYou AI ChatBot — สเปกและผลรับงาน

ตอบประเด็นจากสไลด์ AI Integration Meeting (30 Sep 2026) หน้า 04 และ 12 · KB version `2026.10.02`

## 1. ตอบคำถามต่อทีม AI (สไลด์หน้า 04)

| ประเด็น | ปัญหาเดิม | สิ่งที่ทำ | ตอบคำถามของ SE |
|---|---|---|---|
| **Intent** | อิง keyword มากเกินไป | ตัวจำแนก intent แบบ machine learning (TF-IDF ตัวอักษร+คำ → Logistic Regression) 23 intent เทรนจาก dataset QA 500 ข้อ + ตัวอย่างเพิ่ม 475 ข้อ **ก่อนเทรนจะซ่อนชื่อสินค้า/ผู้ขาย/ตัวเลข** ให้โมเดลเรียนรู้จากเจตนาของประโยค ไม่ใช่จากชื่อสินค้า | **Intent classifier** (ไม่ใช่ prompt หรือ LLM) เลือกเพราะตอบไว (P95 ~4 ms) ควบคุมได้ และอธิบายผลได้ (ส่ง top-3 intent + ความมั่นใจใน log) แชทบอทเจรจาใช้ตัวจำแนกเดียวกันผ่าน `POST /api/negotiate/intent` |
| **Context** | คำถามต่อเนื่องหลุดบริบท | จำบริบทแยกตาม `session_id`: สินค้า ผู้ขาย หมวดล่าสุด และ 5 turn ล่าสุด หมดอายุ 30 นาที ถ้าคำถามไม่ระบุสินค้าแต่ต้องใช้ จะดึงจาก session และบอกใน `context_used` | **เก็บต่อ turn:** สินค้า/ผู้ขาย/หมวดที่คุยล่าสุด + ข้อความ (ปิดบังข้อมูลส่วนตัว) **ส่ง session:** ฝั่ง SE ส่ง `session_id` (หรือ header `X-Session-ID`) มาทุกคำถาม ถ้าไม่ส่ง ระบบสร้างให้และคืนค่าใน response แต่ละ session แยกกันเด็ดขาด |
| **Grounding** | ไม่รู้แหล่งข้อมูลที่ใช้ตอบ | คำตอบเรื่องสินค้า/ราคา/ผู้ขาย **สร้างจาก KB เท่านั้น** ไม่ใช้ข้อความสำเร็จรูปจาก dataset ที่อาจเป็นของสินค้าคนละรุ่น ทุกคำตอบแนบ `source.ids` (รหัส listing/ผู้ขาย) + `kb_version` | **KB มาจาก:** `chatbot_dataset.json` (QA) → listing 430 รายการ / 107 รุ่น / ผู้ขาย 40 ราย + `kb/price_table.json` (ราคามือสองต่อรุ่น) **อัปเดตโดย:** แก้ไฟล์ต้นทาง → `python build_kb.py` → `python sync_negotiation_catalog.py` → `docker compose up -d --build` (ขั้นตอนเต็มในข้อ 5) |
| **Fallback** | ตอบผิดเมื่อไม่มั่นใจ | ไม่ตอบเมื่อ: ความมั่นใจต่ำ / ถามนอกเรื่อง / ถามรุ่นที่ไม่มีใน KB / ต้องรู้สินค้าหรือผู้ขายแต่ไม่รู้ → ตอบว่าไม่แน่ใจ พร้อมบอกเหตุผล (`fallback_reason`) และตัวเลือก (`suggestions`) | **Confidence threshold = 0.25** เลือกจาก 5-fold cross-validation บนข้อมูลเทรน (ไม่ใช่ชุดทดสอบ): ที่ค่านี้ระบบตอบ 81% ของคำถาม แม่นยำ 95.5% ปรับได้ผ่าน env `FALLBACK_THRESHOLD` **Guardrail:** คำขอข้อมูลติดต่อส่วนตัวถูกปฏิเสธเสมอ ไม่ขึ้นกับความมั่นใจ (BR003) |
| **Traceability** | ตามสาเหตุยาก | ทุก request มี `request_id` (รับจาก header `X-Request-ID` ได้ ส่งคืนทั้ง header และ body) บันทึก log JSONL: ข้อความ (ปิดบังเบอร์/อีเมล), intent, top-3, ความมั่นใจ, entity, บริบทที่ใช้, แหล่งข้อมูล, คำตอบ, เวลา | **เข้าถึง log:** ผู้ดูแลระบบที่มี `LOG_ACCESS_TOKEN` เรียก `GET /api/logs/<request_id>` (header `X-Admin-Token`) หรือเปิดไฟล์ `logs/chat_requests.jsonl` บนเซิร์ฟเวอร์ **เก็บนาน:** 30 วัน หมุนไฟล์ทุกเที่ยงคืน (env `LOG_RETENTION_DAYS`) |

## 2. ผลวัดตามเกณฑ์รับงาน (สไลด์หน้า 12)

| ด้าน | ชุด dev (85 ข้อ, ใช้ระหว่างพัฒนา) | ชุด blind (58 ข้อ, เขียนหลังพัฒนาเสร็จ) |
|---|---|---|
| Intent accuracy | **87.1%** (74/85) | **89.7%** (52/58) |
| Grounded answer | 40/40 คำตอบไม่มีตัวเลขนอกแหล่งอ้างอิง | 21/21 คำตอบไม่มีตัวเลขนอกแหล่งอ้างอิง |
| Context handling | 13/13 turn · แยก session: ไม่ปน | 6/6 turn · แยก session: ไม่ปน |
| Safe fallback | 8/8 | 4/4 |
| Latency | P50 3.6 ms · **P95 4.2 ms** · P99 4.9 ms | P50 3.8 ms · **P95 4.3 ms** · P99 5.4 ms |
| Traceability | 124/124 · log: 123/123 request พบใน log | 78/78 · log: 77/77 request พบใน log |
| Negotiation intent | 16/16 (100%) | 7/8 (88%) |

**วิธีวัดที่ควรรู้**
- ชุดทดสอบทั้ง 2 ชุดไม่มีประโยคซ้ำกับข้อมูลเทรน (ตรวจด้วยสคริปต์แล้ว) ใช้คำต่างกันแต่เจตนาเดียวกัน มีทั้งไทย อังกฤษ และพิมพ์ผิด
- ชุด blind รันครั้งแรกได้ intent **84.5%** และเจอบั๊ก 1 จุด (ชื่อรุ่นที่มีช่องว่าง เช่น "Galaxy Z Fold 5" ไม่ถูกจับว่าเป็นรุ่นที่ไม่มีในระบบ) แก้บั๊กแล้วรันใหม่ได้ผลตามตาราง ผลรอบแรกเก็บไว้ที่ `reports/blind_report_first_run.md`
- คำถามที่ระบบตอบไม่ตรง ส่วนใหญ่เป็นแบบ "ไม่แน่ใจแล้วถามกลับ" ไม่ใช่ให้ข้อมูลผิด (ชุด blind: ตอบผิดเรื่อง 0 ข้อ)
- Latency วัดในเครื่อง ยังไม่รวม network ให้วัดซ้ำกับเซิร์ฟเวอร์จริงด้วย `python eval_chatbot.py --url http://<IP>:8012`
- **ค่าเป้าหมายที่ทีม AI เสนอ:** intent ≥ 80%, P95 latency ≤ 500 ms (รวม network), fallback rate ในใช้งานจริงไม่เกิน 25% (ดูได้ที่ `/api/metrics`)

หลักฐานรายข้อ: `reports/eval_results.csv`, `reports/blind_results.csv` · transcript บทสนทนาต่อเนื่องและตัวอย่าง fallback: `reports/eval_report.md`

## 3. API

ทุก endpoint เรียกผ่าน `http://<IP>:8012` ได้ (nginx ส่งต่อให้) หรือตรงที่ `:8013` · Swagger: `http://<IP>:8013/apidocs`

### POST /api/chat
```json
// request (ส่ง session_id เดิมทุกครั้งในบทสนทนาเดียวกัน)
{"message": "แล้วสภาพเป็นไงบ้าง", "session_id": "user-123"}

// response (หลังถาม "Nintendo Switch OLED ราคาเท่าไหร่" ใน session เดียวกัน)
{
  "request_id": "2d56d18dc6c544d3", "session_id": "user-123",
  "response": "Nintendo Switch OLED ในระบบมีสภาพ: New ×2",
  "intent": "condition", "intent_category": "Product Info",
  "confidence": 0.56, "confidence_level": "medium",
  "is_fallback": false, "fallback_reason": null, "suggestions": [],
  "context_used": {"product": "Nintendo Switch OLED"},
  "source": {"type": "kb", "kb_version": "2026.10.02", "ids": ["L0260", "L0373"]},
  "guardrail": null, "latency_ms": 3.92
}
```
ฟิลด์เดิม (`response`, `confidence`, `confidence_level`, `intent_category`, `matched_question`, `is_fallback`) ยังอยู่ครบ ระบบเดิมของ SE ไม่ต้องแก้

ตัวอย่าง fallback:
```json
{"response": "ขออภัย ไม่มี \"iphone 16 pro max\" ในระบบตอนนี้ รุ่นใกล้เคียงที่มี: Apple iPhone 11, Apple iPhone 13, ...",
 "is_fallback": true, "fallback_reason": "unknown_product",
 "suggestions": ["ราคา Apple iPhone 11 เท่าไหร่", "ราคา Apple iPhone 13 เท่าไหร่", "ราคา Apple iPhone 13 Pro เท่าไหร่"]}
```
`fallback_reason`: `low_confidence` · `off_topic` · `unknown_product` · `need_product` · `need_seller` · `need_category`

### POST /api/negotiate/intent
```json
{"message": "ขอเหลือหมื่นห้าได้ไหม", "current_product": "Sony PlayStation 5", "session_id": "nego-1"}
→ {"action": "offer", "price": 15000, "intent": "offer", "confidence": 0.244, "request_id": "d5a9064720c545f1", ...}
```
`action`: `offer` · `spec` · `trust` · `market` · `pii` · `other_product` · `unknown_product` · `greeting` · `farewell` · `other`

### Ops
| Endpoint | ใช้ทำอะไร |
|---|---|
| `GET /api/metrics` | จำนวน request, P50/P95/P99 latency, อัตรา fallback, สัดส่วน intent (ตั้งแต่ start) |
| `GET /api/logs/<request_id>` | ดู log ของคำขอ (header `X-Admin-Token`) |
| `GET /api/kb/info` | เวอร์ชัน KB, แหล่งข้อมูล, จำนวนข้อมูลเทรน, threshold ที่ใช้ |

ทุก response มี header `X-Request-ID` และ `X-Response-Time-ms`

## 4. Log

ไฟล์ `logs/chat_requests.jsonl` บรรทัดละ 1 request:
```json
{"ts": "2026-10-02T15:17:21.512", "request_id": "2d56d18dc6c544d3", "endpoint": "/api/chat", "status": 200,
 "latency_ms": 3.92, "session_id": "user-123", "message": "แล้วสภาพเป็นไงบ้าง", "intent": "condition",
 "confidence": 0.56, "top_intents": [["condition", 0.56], ["price", 0.12], ["spec", 0.08]], "is_fallback": false,
 "context_used": {"product": "Nintendo Switch OLED"}, "source": {...}, "response": "..."}
```
- เบอร์โทรและอีเมลในข้อความถูกแทนด้วย `[PHONE]` / `[EMAIL]` ก่อนบันทึก
- โฟลเดอร์ `logs/` ไม่ขึ้น GitHub (อยู่ใน `.gitignore`)

## 5. อัปเดต Knowledge Base

1. แก้ข้อมูลต้นทาง: `chatbot_dataset.json` (สินค้า/ผู้ขาย จาก QA) หรือ `kb/price_table.json` (ราคามือสองต่อรุ่น)
2. `python build_kb.py` สร้าง `kb/product_catalog.json`, `kb/sellers.json`, `kb/category_trends.json`, `kb/kb_meta.json`
3. `python sync_negotiation_catalog.py` อัปเดตข้อมูลในหน้าแชทบอทเจรจาให้ตรงกัน
4. `python eval_chatbot.py` ตรวจว่ายังผ่านเกณฑ์
5. `docker compose up -d --build chatbot frontend`

เพิ่มประโยคเทรน intent ได้ที่ `kb/intent_train_extra.json` (ห้ามคัดลอกจากไฟล์ใน `tests/`)

## 6. ข้อจำกัดที่ทราบ

- **ราคาใน `kb/price_table.json` เป็นค่าประมาณ** ของตลาดมือสองไทย ยังไม่ได้เทียบประกาศจริงรายรุ่น ควรให้ QA ตรวจทาน (dataset เดิมของ QA มีราคาแบบสุ่ม เช่น PS5 ของใหม่ 4,676 บาท จึงใช้ตรงๆ ไม่ได้)
- บางรุ่นใน dataset ของ QA มีแต่สภาพ For Parts (เช่น iPhone 14) ระบบจะติดป้าย "เครื่องเสีย/ขายเป็นอะไหล่" และบอกราคาเครื่องสภาพดีจาก `kb/price_table.json` ไว้เทียบ (อ้างใน `source.ids` เป็น `price_table:<รุ่น>`)
- ข้อมูลการจัดส่ง/ประกัน/โปรโมชันไม่มีใน dataset ระบบจึงตอบว่า "ยังไม่มีข้อมูล" ทุกครั้ง (ไม่แต่งข้อมูลขึ้นเอง)
- Session และ metrics เก็บใน memory: restart แล้วหาย และรองรับ 1 worker ถ้าต้องขยายหลายเครื่องต้องย้ายไป Redis
- ตัวจำแนก intent เป็นแบบ lexical: ประโยคที่ใช้คำแปลกมาก (ไม่เคยเห็นคำใกล้เคียงในข้อมูลเทรน) จะถูกส่งไป fallback แทน
