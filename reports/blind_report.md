# ผลวัดแชทบอทตามเกณฑ์รับงาน — 2HandToYou

วันที่: 2026-10-02 15:26 · โหมด: local in-process (ไม่รวม network) · ชุดทดสอบ: `tests/test_cases_blind.json` (แยกจากข้อมูลเทรน)

## สรุปตามเกณฑ์ของ SE

| ด้าน | วิธีวัด | ผล | เกณฑ์ | สถานะ |
|---|---|---|---|---|
| Intent accuracy | 58 คำถาม ใช้คำต่างจากข้อมูลเทรน (ไทย/อังกฤษ/พิมพ์ผิด) | **89.7%** (52/58) | ≥ 80% | ✅ ผ่าน |
| Grounded answer | ตัวเลขทุกตัวในคำตอบ (ราคา/สถิติผู้ขาย) ต้องมีอยู่ใน KB รายการที่อ้างใน `source.ids` | 21/21 คำตอบไม่มีตัวเลขนอกแหล่งอ้างอิง | ไม่สร้างข้อมูลที่ไม่มีในแหล่งอ้างอิง | ✅ ผ่าน |
| Context handling | 6 turn ใน 2 บทสนทนาต่อเนื่อง + ทดสอบแยก session | 6/6 turn · แยก session: ไม่ปน | ใช้บริบทได้ ไม่ปนผู้ใช้อื่น | ✅ ผ่าน |
| Safe fallback | 4 คำถามกำกวม/ไม่มีข้อมูล/นอกเรื่อง | 4/4 | แจ้งข้อจำกัด + ถามกลับ/เสนอทางเลือก | ✅ ผ่าน |
| Latency | ทุก request ในการทดสอบ (78 ครั้ง) | P50 3.8 ms · **P95 4.3 ms** · P99 5.4 ms | ทีม AI เสนอ: P95 ≤ 500 ms | ✅ ผ่าน |
| Traceability | request_id ที่ส่งไป = header ที่ได้กลับ = body | 78/78 · log: 77/77 request พบใน log | ทุกคำขอมี Request ID | ✅ ผ่าน |
| Negotiation intent | 8 ข้อความในแชทเจรจา (รวมจับราคาที่เสนอ) | 7/8 (88%) | ≥ 80% | ✅ ผ่าน |

## Intent accuracy แยกรายหมวด

| intent | ถูก | % |
|---|---|---|
| policy | 1/2 | 50% |
| complaint | 1/2 | 50% |
| seller_reputation | 2/3 | 67% |
| price | 3/4 | 75% |
| search | 3/4 | 75% |
| off_topic | 3/4 | 75% |
| price_compare | 3/3 | 100% |
| market_trend | 2/2 | 100% |
| condition | 3/3 | 100% |
| spec | 3/3 | 100% |
| availability | 3/3 | 100% |
| seller_negotiation | 2/2 | 100% |
| recommend | 3/3 | 100% |
| similar | 2/2 | 100% |
| shipping | 3/3 | 100% |
| warranty | 2/2 | 100% |
| discount | 2/2 | 100% |
| report_seller | 2/2 | 100% |
| report_product | 2/2 | 100% |
| pii | 3/3 | 100% |
| greeting | 2/2 | 100% |
| farewell | 2/2 | 100% |

### ข้อที่ตอบผิด intent

จาก 6 ข้อที่ผิด: **6 ข้อระบบไม่แน่ใจแล้วถามกลับ** (ไม่ได้ให้ข้อมูลผิด) และ **0 ข้อตอบผิดเรื่อง** (ข้อมูลที่ตอบยังมาจาก KB แต่ไม่ตรงคำถาม)

| id | ข้อความ | คาดหวัง | ได้ | ความมั่นใจ |
|---|---|---|---|---|
| B002 | Apple Watch Series 7 41mm ขายอยู่ราคาไหน | price | price | 0.17 |
| B021 | ร้าน S00024 ขายมากี่ออเดอร์แล้ว | seller_reputation | seller_reputation | 0.25 |
| B024 | มีของ Samsung อะไรบ้าง | search | search | 0.21 |
| B041 | what happens if a buyer doesn't pay | policy | policy | 0.15 |
| B047 | I paid but the seller disappeared | complaint | pii | 0.24 |
| B057 | ราคาทองวันนี้เท่าไหร่ | off_topic | price | 0.61 |

## ตัวอย่าง Fallback

| คำถาม | เหตุผล | คำตอบ | ตัวเลือกที่เสนอ | ผล |
|---|---|---|---|---|
| Galaxy Z Fold 5 ราคาเท่าไหร่ | unknown_product | ขออภัย ไม่มี "galaxy z fold 5" ในระบบตอนนี้ รุ่นใกล้เคียงที่มี: Samsung Galaxy A54, Samsung Galaxy Note 20 Ult | ราคา Samsung Galaxy A54 เท่าไหร่, ราคา Samsung Galaxy Note 20 Ultra เท่าไหร่, ราคา Samsung Galaxy S21 FE เท่าไหร่ | ✅ |
| สภาพเป็นยังไง | need_product | หมายถึงสินค้ารุ่นไหนคะ | สภาพ Specialized Rockhopper Mountain Bike เป็นยังไง, สภาพ Samsung Galaxy S21 FE เป็นยังไง, สภาพ Casio G-Shock GA-2100 เป็นยังไง | ✅ |
| ช่วยทำการบ้านคณิตศาสตร์ให้หน่อย | off_topic | ขออภัย ยังไม่แน่ใจว่าหมายถึงเรื่องไหน ลองถามเกี่ยวกับราคา สภาพสินค้า ผู้ขาย หรือนโยบายของตลาดได้ค่ะ | หามือถืองบไม่เกิน 10000, ราคา iPhone 13 เท่าไหร่, กฎการซื้อขายมีอะไรบ้าง | ✅ |
| MacBook Pro M4 ยังมีไหม | unknown_product | ขออภัย ไม่มี "macbook pro m4" ในระบบตอนนี้ รุ่นใกล้เคียงที่มี: Apple MacBook Air M1, Apple MacBook Air M2, App | ราคา Apple MacBook Air M1 เท่าไหร่, ราคา Apple MacBook Air M2 เท่าไหร่, ราคา Apple MacBook Pro 13" 2020 เท่าไหร่ | ✅ |

## Conversation transcript (Context handling)

**BC01** — ราคา -> ถามว่ายังมีไหม -> ถามสเปค (session `eval-BC01`)

- 🧑 Canon EOS 90D ราคาเท่าไหร่
- 🤖 Canon EOS 90D มีในระบบ 6 รายการ ราคา 27,700–32,900 บาท (แยกตามสภาพ: New 27,700–32,900 บาท)  
  `intent=price conf=0.975 context_used={} request_id=eval-46fab963211b` ✅

- 🧑 ยังมีขายอยู่ไหม
- 🤖 Canon EOS 90D ยังมีสินค้าพร้อมขาย 6 รายการค่ะ  
  `intent=availability conf=0.746 context_used={'product': 'Canon EOS 90D'} request_id=eval-ca99b7ed99f0` ✅

- 🧑 ขอรายละเอียดหน่อย
- 🤖 Canon EOS 90D ยี่ห้อ Canon หมวด Camera / Digital Camera — Canon EOS 90D ประเภท Digital Camera สภาพ New อยู่ในหมวดหมู่ Camera  
  `intent=spec conf=0.753 context_used={'product': 'Canon EOS 90D'} request_id=eval-d6dc04a3c2b3` ✅


**BC02** — English, change product mid-way (session `eval-BC02`)

- 🧑 how much is the Nintendo Switch Lite
- 🤖 Nintendo Switch Lite: 5 listings, THB 4,900–5,650 (Like New 4,900–5,650).  
  `intent=price conf=0.882 context_used={} request_id=eval-1e315daaf848` ✅

- 🧑 what about the Valve Steam Deck 256GB, how much
- 🤖 Valve Steam Deck 256GB: 3 listings, THB 8,800–9,850 (Fair 8,800–9,850).  
  `intent=price conf=0.654 context_used={} request_id=eval-35aa119d92bc` ✅

- 🧑 is it still available?
- 🤖 Yes, Valve Steam Deck 256GB is still available (3 listings).  
  `intent=availability conf=0.955 context_used={'product': 'Valve Steam Deck 256GB'} request_id=eval-fa010d2e4a9b` ✅


**แยก session:** ผู้ใช้ A ถาม "Canon EOS R10 ราคาเท่าไหร่" แล้วผู้ใช้ B ถาม "ยังมีขายไหม" → B ได้ `need_product` ("หมายถึงสินค้ารุ่นไหนคะ") ✅ ไม่ได้บริบทของ A

รายละเอียดทุกข้อ: `reports/blind_results.csv`
