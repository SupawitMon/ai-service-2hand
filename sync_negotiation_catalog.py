"""sync_negotiation_catalog.py — คัดลอกข้อมูลสินค้าจาก KB (kb/product_catalog.json + kb/sellers.json)
ไปใส่ในหน้า negotiation_chatbot.html ให้แชทบอททั้ง 2 ตัวใช้ข้อมูลชุดเดียวกัน (รันหลัง build_kb.py)"""
import json, os, re
HERE = os.path.dirname(os.path.abspath(__file__))
cat = json.load(open(os.path.join(HERE, "kb", "product_catalog.json"), encoding="utf-8"))
sel = json.load(open(os.path.join(HERE, "kb", "sellers.json"), encoding="utf-8"))
products = [{"name": c["name"], "price": c["price"], "market": c["market_price"], "seller": c["seller_id"],
             "rating": sel[c["seller_id"]]["rating"], "negRate": sel[c["seller_id"]]["negotiation_rate"],
             "brand": c["brand"], "cond": c["condition"], "cat": c["category"], "desc": c["description"],
             "listing_id": c["listing_id"]} for c in cat]
p = os.path.join(HERE, "negotiation_chatbot.html")
h = open(p, encoding="utf-8").read()
a = h.index("[", h.index("const PRODUCTS")); b = h.index("];", a)
h = h[:a] + json.dumps(products, ensure_ascii=False) + h[b + 1:]
open(p, "w", encoding="utf-8").write(h)
print(f"อัปเดต {len(products)} รายการใน negotiation_chatbot.html")
