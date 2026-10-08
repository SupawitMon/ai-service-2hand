# API Specification — 2HandToYou AI Service (OpenAPI 3.0)

| ไฟล์ | ใช้ทำอะไร |
|---|---|
| `swagger.html` | เปิดด้วยเบราว์เซอร์ได้ทันที (ไม่ต้องต่ออินเทอร์เน็ต) แสดง API ทุกตัวแบบ Swagger และกด "Try it out" ยิง API จริงได้ |
| `openapi.yaml` | ไฟล์สเปกมาตรฐาน OpenAPI 3.0 — นำเข้า Swagger Editor (editor.swagger.io), Postman, หรือเครื่องมือสร้างโค้ดได้ |
| `openapi.json` | เนื้อหาเดียวกับ `openapi.yaml` ในรูปแบบ JSON |

ครอบคลุม 10 endpoint ของ 2 บริการ (AI Price Service, AI ChatBot Service) เรียกผ่านพอร์ต 8012
ตรวจความถูกต้องแล้ว: สเปกผ่าน OpenAPI validator และ response จริงจากเซิร์ฟเวอร์ตรงกับ schema ทุกตัว
