"""
build_kb.py — สร้าง Knowledge Base (KB) ของแชทบอทจากแหล่งข้อมูลต้นทาง

แหล่งข้อมูล (source of truth):
  1. chatbot_dataset.json      : dataset 500 ข้อจาก QA (ข้อมูลผู้ขาย, แนวโน้มราคาหมวดสินค้า, ข้อความนโยบาย)
  2. kb/price_table.json       : ราคามือสองสภาพดีต่อรุ่น (บาท) + ตัวคูณตามสภาพ  <- แก้ราคาที่ไฟล์นี้
  3. listings จาก dataset      : สินค้าแต่ละรายการ (รุ่น / ผู้ขาย / สภาพ)

ผลลัพธ์ (แชทบอททั้ง 2 ตัวอ่านจากไฟล์เหล่านี้เท่านั้น):
  kb/product_catalog.json  รายการสินค้าทั้งหมด + ราคา
  kb/sellers.json          ข้อมูลผู้ขาย
  kb/category_trends.json  แนวโน้มราคาแยกหมวด
  kb/kb_meta.json          เวอร์ชัน + วันที่สร้าง

วิธีอัปเดต KB:
  1) แก้ chatbot_dataset.json หรือ kb/price_table.json
  2) python build_kb.py
  3) python sync_negotiation_catalog.py   (อัปเดตข้อมูลในหน้าแชทบอทเจรจาให้ตรงกัน)
  4) docker compose up -d --build chatbot frontend
"""
import json, hashlib, re, datetime, os
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
KB = os.path.join(HERE, "kb")


def load(p):
    with open(os.path.join(HERE, p), encoding="utf-8") as f:
        return json.load(f)


def save(p, obj):
    with open(os.path.join(HERE, p), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def cond_key(cond):
    return cond.split(" / ")[0].strip()


def rnd(x):
    step = 10 if x < 2000 else 50 if x < 20000 else 100
    return int(round(x / step) * step)


def main():
    data = load("chatbot_dataset.json")
    pt = load("kb/price_table.json")
    base, mult = pt["base_price_good"], pt["condition_multiplier"]

    # ---------- listings: 1 รายการ = รุ่น + ผู้ขาย + สภาพ (ไม่ซ้ำ) ----------
    seen, catalog = OrderedDict(), []
    for d in data:
        name = d.get("Product_Name")
        if not name or not d.get("Seller_ID") or name not in base:
            continue
        key = (name, d["Seller_ID"], d["Condition"])
        if key in seen:
            continue
        market = base[name] * mult[cond_key(d["Condition"])]
        # ผู้ขายแต่ละคนตั้งราคาต่างกัน -3% ถึง +15% (คงที่ต่อผู้ขาย+รุ่น)
        f = 1.0 + (int(hashlib.md5((d["Seller_ID"] + name).encode()).hexdigest(), 16) % 19) / 100 - 0.03
        item = {
            "listing_id": f"L{len(catalog) + 1:04d}",
            "name": name, "brand": d["Brand"], "model": d["Model"],
            "category": d["Category"], "subcategory": d["Subcategory"],
            "condition": d["Condition"], "condition_key": cond_key(d["Condition"]),
            "seller_id": d["Seller_ID"], "price": rnd(market * f), "market_price": rnd(market),
            "description": d["Description"], "dataset_product_id": d["Product_ID"],
        }
        seen[key] = item
        catalog.append(item)

    # ---------- sellers ----------
    sellers = {}
    for d in data:
        s = d.get("Seller_ID")
        if s and s not in sellers:
            sellers[s] = {"seller_id": s, "rating": d["Seller_Rating"], "total_sales": int(d["Seller_Total_Sales"]),
                          "response_rate": int(d["Seller_Response_Rate"]), "negotiation_rate": int(d["Seller_Negotiation_Rate"])}

    # ---------- แนวโน้มราคาแยกหมวด (จากคำตอบหมวด Market Trend ของ QA) ----------
    trends = {}
    pat = [("ลดลง", "down"), ("declined", "down"), ("fallen", "down"), ("dropped", "down"),
           ("เพิ่มขึ้น", "up"), ("risen", "up"), ("increased", "up"), ("คงที่", "stable"), ("stable", "stable")]
    for d in data:
        if d["Intent"] != "Market Trend":
            continue
        txt = d["Expected_AI_Response"]
        for w, t in pat:
            if w in txt:
                trends.setdefault(d["Category"], t)
                break

    meta = {
        "kb_version": datetime.date.today().strftime("%Y.%m.%d"),
        "built_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "sources": ["chatbot_dataset.json (QA, 500 rows)", "kb/price_table.json"],
        "counts": {"listings": len(catalog), "products": len({c['name'] for c in catalog}), "sellers": len(sellers)},
        "price_note": pt.get("note", ""),
    }
    save("kb/product_catalog.json", catalog)
    save("kb/sellers.json", sellers)
    save("kb/category_trends.json", trends)
    save("kb/kb_meta.json", meta)
    print(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
