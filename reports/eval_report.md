# ผลวัดแชทบอทตามเกณฑ์รับงาน — 2HandToYou

วันที่: 2026-10-02 15:26 · โหมด: local in-process (ไม่รวม network) · ชุดทดสอบ: `tests/test_cases.json` (แยกจากข้อมูลเทรน)

## สรุปตามเกณฑ์ของ SE

| ด้าน | วิธีวัด | ผล | เกณฑ์ | สถานะ |
|---|---|---|---|---|
| Intent accuracy | 85 คำถาม ใช้คำต่างจากข้อมูลเทรน (ไทย/อังกฤษ/พิมพ์ผิด) | **87.1%** (74/85) | ≥ 80% | ✅ ผ่าน |
| Grounded answer | ตัวเลขทุกตัวในคำตอบ (ราคา/สถิติผู้ขาย) ต้องมีอยู่ใน KB รายการที่อ้างใน `source.ids` | 40/40 คำตอบไม่มีตัวเลขนอกแหล่งอ้างอิง | ไม่สร้างข้อมูลที่ไม่มีในแหล่งอ้างอิง | ✅ ผ่าน |
| Context handling | 13 turn ใน 6 บทสนทนาต่อเนื่อง + ทดสอบแยก session | 13/13 turn · แยก session: ไม่ปน | ใช้บริบทได้ ไม่ปนผู้ใช้อื่น | ✅ ผ่าน |
| Safe fallback | 8 คำถามกำกวม/ไม่มีข้อมูล/นอกเรื่อง | 8/8 | แจ้งข้อจำกัด + ถามกลับ/เสนอทางเลือก | ✅ ผ่าน |
| Latency | ทุก request ในการทดสอบ (124 ครั้ง) | P50 3.6 ms · **P95 4.2 ms** · P99 4.9 ms | ทีม AI เสนอ: P95 ≤ 500 ms | ✅ ผ่าน |
| Traceability | request_id ที่ส่งไป = header ที่ได้กลับ = body | 124/124 · log: 123/123 request พบใน log | ทุกคำขอมี Request ID | ✅ ผ่าน |
| Negotiation intent | 16 ข้อความในแชทเจรจา (รวมจับราคาที่เสนอ) | 16/16 (100%) | ≥ 80% | ✅ ผ่าน |

## Intent accuracy แยกรายหมวด

| intent | ถูก | % |
|---|---|---|
| recommend | 2/4 | 50% |
| condition | 3/5 | 60% |
| similar | 2/3 | 67% |
| warranty | 2/3 | 67% |
| discount | 2/3 | 67% |
| complaint | 2/3 | 67% |
| shipping | 3/4 | 75% |
| off_topic | 3/4 | 75% |
| price | 7/8 | 88% |
| price_compare | 4/4 | 100% |
| market_trend | 4/4 | 100% |
| spec | 5/5 | 100% |
| availability | 4/4 | 100% |
| seller_reputation | 4/4 | 100% |
| seller_negotiation | 3/3 | 100% |
| search | 5/5 | 100% |
| policy | 3/3 | 100% |
| report_seller | 3/3 | 100% |
| report_product | 3/3 | 100% |
| pii | 4/4 | 100% |
| greeting | 3/3 | 100% |
| farewell | 3/3 | 100% |

### ข้อที่ตอบผิด intent

จาก 11 ข้อที่ผิด: **5 ข้อระบบไม่แน่ใจแล้วถามกลับ** (ไม่ได้ให้ข้อมูลผิด) และ **6 ข้อตอบผิดเรื่อง** (ข้อมูลที่ตอบยังมาจาก KB แต่ไม่ตรงคำถาม)

| id | ข้อความ | คาดหวัง | ได้ | ความมั่นใจ |
|---|---|---|---|---|
| I004 | what does the Fujifilm X100V go for | price | shipping | 0.19 |
| I017 | is the Nintendo Switch Lite in good shape | condition | price_compare | 0.27 |
| I039 | ช่วยเลือกมือถือดีๆ ให้หน่อย | recommend | search | 0.38 |
| I041 | any recommendations for a gaming console | recommend | search | 0.37 |
| I043 | มีอะไรคล้ายๆ Dell Latitude 5420 ไหม | similar | search | 0.39 |
| I047 | ส่งของแบบไหนบ้าง EMS หรือ Kerry | shipping | shipping | 0.14 |
| I050 | Apple Mac Mini M2 ยังอยู่ในประกันไหม | warranty | availability | 0.33 |
| I055 | any coupon codes I can use | discount | condition | 0.18 |
| I066 | รอมาอาทิตย์นึงแล้วของยังไม่มา | complaint | complaint | 0.19 |
| I079 | what's the weather in Bangkok | off_topic | spec | 0.27 |
| I085 | iPhone 11 สภาพกี่% | condition | price | 0.37 |

## ตัวอย่าง Fallback

| คำถาม | เหตุผล | คำตอบ | ตัวเลือกที่เสนอ | ผล |
|---|---|---|---|---|
| iPhone 16 Pro Max ราคาเท่าไหร่ | unknown_product | ขออภัย ไม่มี "iphone 16 pro max" ในระบบตอนนี้ รุ่นใกล้เคียงที่มี: Apple iPhone 11, Apple iPhone 13, Apple iPho | ราคา Apple iPhone 11 เท่าไหร่, ราคา Apple iPhone 13 เท่าไหร่, ราคา Apple iPhone 13 Pro เท่าไหร่ | ✅ |
| Galaxy S24 สภาพดีไหม | unknown_product | ขออภัย ไม่มี "galaxy s24" ในระบบตอนนี้ รุ่นใกล้เคียงที่มี: Samsung Galaxy A54, Samsung Galaxy Note 20 Ultra, S | ราคา Samsung Galaxy A54 เท่าไหร่, ราคา Samsung Galaxy Note 20 Ultra เท่าไหร่, ราคา Samsung Galaxy S21 FE เท่าไหร่ | ✅ |
| ราคาเท่าไหร่ | need_product | หมายถึงสินค้ารุ่นไหนคะ | ราคา Specialized Rockhopper Mountain Bike เท่าไหร่, ราคา Samsung Galaxy S21 FE เท่าไหร่, ราคา Casio G-Shock GA-2100 เท่าไหร่ | ✅ |
| บอลคืนนี้ใครชนะ | off_topic | ขออภัย ยังไม่แน่ใจว่าหมายถึงเรื่องไหน ลองถามเกี่ยวกับราคา สภาพสินค้า ผู้ขาย หรือนโยบายของตลาดได้ค่ะ | ราคา iPhone 13 เท่าไหร่, หามือถืองบไม่เกิน 10000, กฎการซื้อขายมีอะไรบ้าง | ✅ |
| asdkjh qwe zzz | off_topic | Sorry, I'm not sure what you mean. You could ask about prices, product condition, sellers, or marketplace poli | How much is iPhone 13?, Show me phones under 10000, What are the marketplace rules? | ✅ |
| Which crypto should I buy | off_topic | Sorry, we don't have "crypto" in our marketplace. You can ask about phones, laptops, cameras, gaming and more. | Show me phones under 10000, Recommend me a laptop, How much is iPhone 13? | ✅ |
| ผู้ขายน่าเชื่อถือไหม | need_seller | หมายถึงผู้ขายคนไหนคะ (เช่น S00005) |  | ✅ |
| Pixel 8 ยังมีไหม | unknown_product | ขออภัย ไม่มี "pixel 8" ในระบบตอนนี้ |  | ✅ |

## Conversation transcript (Context handling)

**C001** — ถามราคา แล้วถามสภาพต่อโดยไม่บอกชื่อรุ่น (session `eval-C001`)

- 🧑 Nintendo Switch OLED ราคาเท่าไหร่
- 🤖 Nintendo Switch OLED มีในระบบ 2 รายการ ราคา 11,250–11,600 บาท (แยกตามสภาพ: New 11,250–11,600 บาท)  
  `intent=price conf=0.975 context_used={} request_id=eval-2e829540b396` ✅

- 🧑 แล้วสภาพเป็นไงบ้าง
- 🤖 Nintendo Switch OLED ในระบบมีสภาพ: New ×2  
  `intent=condition conf=0.56 context_used={'product': 'Nintendo Switch OLED'} request_id=eval-5fb97b941d17` ✅


**C002** — ถามสเปค แล้วถามว่ายังมีไหม (session `eval-C002`)

- 🧑 ขอรายละเอียด Sony Alpha A7 III
- 🤖 Sony Alpha A7 III ยี่ห้อ Sony หมวด Camera / Digital Camera — Sony Alpha A7 III ประเภท Digital Camera สภาพ Like New อยู่ในหมวดหมู่ Camera  
  `intent=spec conf=0.756 context_used={} request_id=eval-ae28cbc570db` ✅

- 🧑 ยังมีขายอยู่ไหม
- 🤖 Sony Alpha A7 III ยังมีสินค้าพร้อมขาย 2 รายการค่ะ  
  `intent=availability conf=0.746 context_used={'product': 'Sony Alpha A7 III'} request_id=eval-0b115f343755` ✅


**C003** — English follow-up (session `eval-C003`)

- 🧑 How much is the Apple MacBook Air M1?
- 🤖 Apple MacBook Air M1: 2 listings, THB 5,200–5,850 (For Parts (broken) 5,200–5,850). ⚠️ All listings are broken units sold for parts, so prices are far below a working unit (about THB 15,000 in good condition).  
  `intent=price conf=0.884 context_used={} request_id=eval-b52ffeacc2ca` ✅

- 🧑 is it cheaper than the market price?
- 🤖 Apple MacBook Air M1 (For Parts, seller S00027) is THB 5,200 vs market THB 5,250 — close to market (-1%).  
  `intent=price_compare conf=0.882 context_used={'product': 'Apple MacBook Air M1'} request_id=eval-7763f66d5e36` ✅


**C004** — ถามผู้ขาย แล้วถามว่าต่อรองได้ไหม (session `eval-C004`)

- 🧑 ผู้ขาย S00007 น่าเชื่อถือไหม
- 🤖 ผู้ขาย S00007 คะแนนรีวิว 4.8/5 ขายสำเร็จ 390 รายการ อัตราตอบกลับ 80% — เรตติ้งดี น่าเชื่อถือ  
  `intent=seller_reputation conf=0.561 context_used={} request_id=eval-25de631ca045` ✅

- 🧑 แล้วร้านนี้ยอมต่อราคาไหม
- 🤖 ผู้ขาย S00007 ยอมต่อรองราคาสำเร็จประมาณ 29% ของออเดอร์ที่ผ่านมา  
  `intent=seller_negotiation conf=0.615 context_used={'seller': 'S00007'} request_id=eval-8a717be77791` ✅


**C005** — เปลี่ยนรุ่นกลางทาง บริบทต้องเปลี่ยนตาม (session `eval-C005`)

- 🧑 ราคา iPhone 13 เท่าไหร่
- 🤖 Apple iPhone 13 มีในระบบ 7 รายการ ราคา 16,750–19,100 บาท (แยกตามสภาพ: New 16,750–19,100 บาท)  
  `intent=price conf=0.948 context_used={} request_id=eval-59b58d6094bd` ✅

- 🧑 แล้ว Samsung Galaxy S22 ล่ะ ราคาเท่าไหร่
- 🤖 Samsung Galaxy S22 มีในระบบ 7 รายการ ราคา 8,250–9,100 บาท (แยกตามสภาพ: Fair 8,250–9,100 บาท)  
  `intent=price conf=0.944 context_used={} request_id=eval-759f5d3836f7` ✅

- 🧑 สภาพเป็นยังไง
- 🤖 Samsung Galaxy S22 ในระบบมีสภาพ: Fair ×7  
  `intent=condition conf=0.537 context_used={'product': 'Samsung Galaxy S22'} request_id=eval-e40f8ecbee6b` ✅


**C006** — ถามหาสินค้าในหมวด แล้วถามรุ่นใกล้เคียง (session `eval-C006`)

- 🧑 Canon EOS R10 ราคาเท่าไหร่
- 🤖 Canon EOS R10 มีในระบบ 3 รายการ ราคา 7,450–8,850 บาท (แยกตามสภาพ: เครื่องเสีย/ขายเป็นอะไหล่ 7,450–8,850 บาท) ⚠️ ทุกรายการเป็นเครื่องเสีย ขายเป็นอะไหล่ ใช้งานไม่ได้เต็มระบบ ราคาจึงต่ำกว่าเครื่องปกติมาก (เครื่องสภาพดีราคาตลาดประมาณ 22,000 บาท)  
  `intent=price conf=0.975 context_used={} request_id=eval-aeea2c9f4240` ✅

- 🧑 มีรุ่นอื่นที่คล้ายกันไหม
- 🤖 รุ่นใกล้เคียง Canon EOS R10 ในหมวด Camera: Sony ZV-E10 12,350 บาท (Fair), Canon EOS M50 Mark II 14,150 บาท (Good), Nikon D7500 22,700 บาท (New), Fujifilm X-T30 II 26,400 บาท (Good)  
  `intent=similar conf=0.779 context_used={'product': 'Canon EOS R10'} request_id=eval-5fea67588287` ✅


**แยก session:** ผู้ใช้ A ถาม "Sony PlayStation 5 ราคาเท่าไหร่" แล้วผู้ใช้ B ถาม "แล้วสภาพเป็นยังไง" → B ได้ `need_product` ("หมายถึงสินค้ารุ่นไหนคะ") ✅ ไม่ได้บริบทของ A

รายละเอียดทุกข้อ: `reports/eval_results.csv`
