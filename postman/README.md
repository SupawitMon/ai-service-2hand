# Postman collection — 2HandToYou AI Service

ไฟล์เดียว: `2HandToYou_AI_Service.postman_collection.json` (22 request พร้อม test อัตโนมัติ)

## URL ที่ใช้ (เส้นเดียว)

ทุก request เรียกผ่าน **API Gateway พอร์ต 8012** ผ่านตัวแปร `{{base_url}}` ที่ฝังอยู่ใน collection แล้ว **ไม่ต้อง import environment**

| ค่าของ `base_url` | ใช้เมื่อ |
|---|---|
| `http://localhost:8012` (ค่าเริ่มต้น) | รัน Postman บนเครื่องเดียวกับที่ติดตั้งระบบ |
| `http://<IP เซิร์ฟเวอร์>:8012` | ทดสอบจากเครื่องอื่น |

เปลี่ยนค่า: คลิกชื่อ collection → แท็บ **Variables** → แก้ช่อง **Current value** ของ `base_url` → **Save**

## วิธีใช้

1. Postman → **Import** → เลือกไฟล์ `2HandToYou_AI_Service.postman_collection.json`
2. (ถ้าทดสอบจากเครื่องอื่น) แก้ `base_url` ตามตารางด้านบน
3. คลิกขวาที่ collection → **Run collection** → **Run** ทุก test ต้องผ่าน

## หมายเหตุ

- **ทายเกรดจากรูป:** ต้องเลือกไฟล์รูปเองก่อน (Body → form-data → `image`) ถ้าไม่เลือก test ข้อนั้นจะถูกข้าม ไม่นับว่า fail
- **ดู log ของ request_id:** ใส่ `admin_token` ใน Variables ให้ตรงกับ `LOG_ACCESS_TOKEN` ในไฟล์ `.env` บนเซิร์ฟเวอร์ (ไม่ใส่จะได้ 403 ซึ่งถูกต้อง)
- คำถามแชทบอทข้อ 1–3 ใช้ `session_id` เดียวกัน (สร้างให้อัตโนมัติ) เพื่อทดสอบการจำบริบท
- รันจาก command line: `newman run 2HandToYou_AI_Service.postman_collection.json --env-var base_url=http://<IP>:8012`
