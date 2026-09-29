# -*- coding: utf-8 -*-
"""
============================================================================
 Backend Server — เชื่อมโมเดลจริงที่เทรนไว้แล้วเข้ากับหน้า mockup

 ใช้ไฟล์: price_model.json (XGBoost), price_model_categories.pkl,
          best.pt (YOLO), product_lookup.json (ฐานข้อมูลราคาตลาดอ้างอิง)

 โมเดล price_model.json ต้องการข้อมูล 37 อย่างถึงจะทายราคาได้ แต่ฟอร์มหน้าบ้าน
 ให้กรอกแค่ ยี่ห้อ/รุ่น/ปี/เกรด/อุปกรณ์ครบไหม — ไฟล์นี้เติมข้อมูลที่เหลือให้เอง:
   - ข้อมูลตลาด (ราคาเฉลี่ย/สูงสุด/ต่ำสุด, คะแนนผู้ขาย ฯลฯ) -> ดึงจาก product_lookup.json
     (คำนวณไว้ล่วงหน้าจาก dataset เดิม โดยเฉลี่ยตามยี่ห้อ+รุ่น)
   - ข้อมูลความเสียหาย (Damage_Level, Scratch_Level ฯลฯ) -> map มาจากเกรด A/B/C
   - จำนวนอุปกรณ์ครบ/ขาด -> map มาจาก dropdown "อุปกรณ์ครบครัน"

 รัน: python backend_server.py   (จะเปิดที่ http://localhost:5000)
============================================================================
"""

import os
import json
import numpy as np
import pandas as pd
import xgboost as xgb
import joblib
from flask import Flask, request, jsonify
from flask_cors import CORS
from flasgger import Swagger, swag_from

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CURRENT_YEAR = 2026

app = Flask(__name__)
CORS(app)

# ---- Swagger UI: เข้าดู/ทดสอบ API แบบ interactive ได้ที่ /apidocs ----
app.config["SWAGGER"] = {
    "title": "AI ประเมินราคาสินค้ามือสอง — API",
    "uiversion": 3,
    "specs_route": "/apidocs/",
}
swagger = Swagger(app, template={
    "info": {
        "title": "AI ประเมินราคาสินค้ามือสอง — API",
        "description": "API สำหรับดึงรายชื่อสินค้า, ทายเกรดสภาพจากรูปภาพ (YOLO), และประเมินราคา (XGBoost)",
        "version": "1.0.0",
    },
})

# ----------------------------------------------------------------------------
# 1. โหลดโมเดลและไฟล์ประกอบทั้งหมด (โหลดครั้งเดียวตอนเปิดเซิร์ฟเวอร์)
# ----------------------------------------------------------------------------
print("กำลังโหลดโมเดล...")

booster = xgb.Booster()
booster.load_model(os.path.join(BASE_DIR, "price_model.json"))
FEATURE_NAMES = booster.feature_names
FEATURE_TYPES = booster.feature_types
print(f"โหลด price_model.json สำเร็จ ({len(FEATURE_NAMES)} features)")

categories = joblib.load(os.path.join(BASE_DIR, "price_model_categories.pkl"))
print("โหลด price_model_categories.pkl สำเร็จ")

# --- PATCH: price_model_categories.pkl ไม่ตรงกับ categories จริงที่ฝังอยู่ใน
# price_model.json (โมเดลจะ error ทันทีถ้า category domain ไม่ตรงเป๊ะ แม้ค่าที่
# ใช้จริงในแถวนั้นจะถูกต้องก็ตาม) --> ดึง categories จริงจากตัวโมเดลเองมาทับ
# หมายเหตุ: นี่เป็นการแก้ให้ "ไม่ error" เท่านั้น ไม่ได้แก้ปัญหาข้อมูลต้นตอ
# (ดูคำเตือนท้ายไฟล์นี้/README)
def _decode_model_categories(model_path, feature_names):
    with open(model_path, encoding="utf-8") as f:
        raw = json.load(f)
    enc = raw["learner"]["gradient_booster"]["model"]["cats"]["enc"]
    out = {}
    for i, name in enumerate(feature_names):
        entry = enc[i]
        offsets, values = entry["offsets"], entry["values"]
        if not offsets:
            continue
        vals = bytes([v & 0xFF for v in values])
        cats_list = []
        for j in range(len(offsets) - 1):
            chunk = vals[offsets[j]:offsets[j + 1]]
            try:
                # ต้อง decode แบบ strict: ถ้า category ไหนใน price_model.json
                # เป็น invalid UTF-8 (ไฟล์เพี้ยนตั้งแต่ตอนเทรน/เซฟโมเดล) xgboost
                # เองก็ไม่มีทางรับค่านั้นกลับเข้าไปได้อยู่ดี (encode คืนไม่ผ่าน)
                # จึงตัดออกจาก domain ไปเลย ดีกว่าให้ทุก request ที่ไม่แตะคอลัมน์
                # นี้พังไปด้วย
                cats_list.append(chunk.decode("utf-8"))
            except UnicodeDecodeError:
                print(f"!! ข้าม category เพี้ยน (invalid UTF-8) ในคอลัมน์ {name}, "
                      f"index {j} — ไฟล์ price_model.json มีปัญหาการเข้ารหัสตั้งแต่ต้นทาง")
        out[name] = cats_list
    return out

_real_categories = _decode_model_categories(os.path.join(BASE_DIR, "price_model.json"), FEATURE_NAMES)
_mismatched_cols = [c for c in _real_categories if _real_categories[c] != categories.get(c)]
if _mismatched_cols:
    print(f"!! คำเตือน: {len(_mismatched_cols)} คอลัมน์ categorical ใน .pkl ไม่ตรงกับที่โมเดลเทรนจริง: {_mismatched_cols}")
    print("   ใช้ categories จริงจาก price_model.json แทนเพื่อกัน error — แต่ค่าที่ map ผิดภาษา/สะกดจะยังทายผิดเงียบๆ")
categories = {**categories, **_real_categories}  # ทับด้วยของจริงจากโมเดล

with open(os.path.join(BASE_DIR, "product_lookup.json"), "r", encoding="utf-8") as f:
    lookup_data = json.load(f)
PRODUCT_LOOKUP = lookup_data["products"]
FALLBACK = lookup_data["overall_fallback"]
print(f"โหลด product_lookup.json สำเร็จ ({len(PRODUCT_LOOKUP)} รุ่นสินค้า)")

# ---- Index สำหรับค้นหาแบบไม่สนตัวพิมพ์เล็ก/ใหญ่และช่องว่าง ----
# เช่น "s22" / "S 22" / "Galaxy S22" ต้องหาเจอเป็นสินค้าเดียวกัน
def _normalize_for_match(s):
    return "".join(s.lower().split())  # ตัดช่องว่างทั้งหมด + เป็นตัวพิมพ์เล็ก

NORMALIZED_LOOKUP = {}
for _key in PRODUCT_LOOKUP.keys():
    _brand, _model = _key.split("|||")
    _norm_key = _normalize_for_match(_brand) + "|||" + _normalize_for_match(_model)
    NORMALIZED_LOOKUP[_norm_key] = (_brand, _model)  # เก็บชื่อจริง (ตัวสะกดถูกต้อง) ไว้คืนกลับ

def resolve_product(brand, model_name):
    """หาแบรนด์/รุ่นที่ตรงในฐานข้อมูล ไม่สนตัวพิมพ์เล็กใหญ่/ช่องว่าง
    คืนค่า (brand จริง, model จริง) ถ้าเจอ หรือ (None, None) ถ้าไม่เจอ"""
    norm_key = _normalize_for_match(brand) + "|||" + _normalize_for_match(model_name)
    return NORMALIZED_LOOKUP.get(norm_key, (None, None))

YOLO_MODEL = None
try:
    from ultralytics import YOLO
    YOLO_MODEL = YOLO(os.path.join(BASE_DIR, "best.pt"))
    print("โหลด best.pt (YOLO เกรด A/B/C) สำเร็จ")
except Exception as e:
    print("!! โหลด YOLO เกรดไม่สำเร็จ (ยังใช้ /api/predict-price ได้ปกติ):", e)


# ----------------------------------------------------------------------------
# 2. ตารางแปลง เกรด A/B/C -> ค่าฟีเจอร์ความเสียหาย/สภาพ
# ----------------------------------------------------------------------------
GRADE_DEFAULTS = {
    "A": {
        "Seller_Condition_Percentage": 95, "AI_Detected_Condition": 95,
        "Damage_Level": "NONE", "Water_Damage": "No", "Scratch_Level": "NONE",
        "Dent_Level": "NONE", "Screen_Crack": "No", "Broken_Parts": "No",
        "num_visible_damage": 0,
    },
    "B": {
        "Seller_Condition_Percentage": 80, "AI_Detected_Condition": 80,
        "Damage_Level": "MINOR", "Water_Damage": "No", "Scratch_Level": "LIGHT",
        "Dent_Level": "LIGHT", "Screen_Crack": "No", "Broken_Parts": "No",
        "num_visible_damage": 1,
    },
    "C": {
        "Seller_Condition_Percentage": 55, "AI_Detected_Condition": 55,
        "Damage_Level": "MODERATE", "Water_Damage": "No", "Scratch_Level": "HEAVY",
        "Dent_Level": "HEAVY", "Screen_Crack": "No", "Broken_Parts": "No",
        "num_visible_damage": 3,
    },
}

ACCESSORY_DEFAULTS = {
    "full":    {"num_accessories": 6, "num_missing_accessories": 0},
    "partial": {"num_accessories": 3, "num_missing_accessories": 3},
    "none":    {"num_accessories": 0, "num_missing_accessories": 6},
}

# ข้อความอธิบายตำหนิ/สภาพสินค้าตามเกรด — ใช้เป็นเหตุผลประกอบการประเมินราคา
GRADE_CONDITION_NOTE = {
    "A": "สภาพสมบูรณ์ ไม่พบตำหนิจากการตรวจสอบ ช่วยให้ประเมินราคาได้สูงกว่าสภาพทั่วไป",
    "B": "พบตำหนิเล็กน้อย เช่น รอยขีดข่วนหรือรอยบุบเบาๆ ทำให้ราคาลดลงจากสภาพสมบูรณ์เล็กน้อย",
    "C": "พบตำหนิค่อนข้างชัดเจน เช่น รอยขีดข่วนหรือรอยบุบหลายจุด ทำให้ราคาลดลงจากสภาพสมบูรณ์พอสมควร",
}


# ----------------------------------------------------------------------------
# 3. สร้าง feature vector ให้ตรงกับที่โมเดลต้องการทุกคอลัมน์ (37 อย่าง)
# ----------------------------------------------------------------------------
def build_feature_row(brand, model_name, year, grade, accessories_level):
    key = f"{brand}|||{model_name}"
    market = PRODUCT_LOOKUP.get(key, FALLBACK)

    grade_vals = GRADE_DEFAULTS.get(grade, GRADE_DEFAULTS["B"])
    acc_vals = ACCESSORY_DEFAULTS.get(accessories_level, ACCESSORY_DEFAULTS["partial"])

    market_avg = market["Market_Average_Price"] or FALLBACK["Market_Average_Price"]
    market_high = market["Market_Highest_Price"] or FALLBACK["Market_Highest_Price"]
    market_low = market["Market_Lowest_Price"] or FALLBACK["Market_Lowest_Price"]
    hist_sold = market["Historical_Sold_Price"] or FALLBACK["Historical_Sold_Price"]

    row = {
        "Production_Year": int(year),
        "Weight": float(market["Weight"] or FALLBACK["Weight"]),
        "Seller_Condition_Percentage": grade_vals["Seller_Condition_Percentage"],
        "AI_Detected_Condition": grade_vals["AI_Detected_Condition"],
        "Market_Average_Price": float(market_avg),
        "Market_Highest_Price": float(market_high),
        "Market_Lowest_Price": float(market_low),
        "Historical_Sold_Price": float(hist_sold),
        "Seller_Rating": float(market["Seller_Rating"] or FALLBACK["Seller_Rating"]),
        "Seller_Total_Sales": float(market["Seller_Total_Sales"] or FALLBACK["Seller_Total_Sales"]),
        "product_age_years": max(0, CURRENT_YEAR - int(year)),
        "num_accessories": acc_vals["num_accessories"],
        "num_missing_accessories": acc_vals["num_missing_accessories"],
        "num_visible_damage": grade_vals["num_visible_damage"],
        "battery_health_pct": grade_vals["Seller_Condition_Percentage"],
        "market_price_range": float(market_high - market_low),
        "market_range_pct": float((market_high - market_low) / market_avg) if market_avg else 0.0,
        "hist_vs_avg_ratio": float(hist_sold / market_avg) if market_avg else 1.0,
        "condition_gap": grade_vals["Seller_Condition_Percentage"] - grade_vals["AI_Detected_Condition"],
        "has_battery_info": 1,
        "Category": market["Category"] or "Unknown",
        "Subcategory": market["Subcategory"] or "Unknown",
        "Brand": brand,
        "Model": model_name,
        "Color": market["Color"] or "Unknown",
        "Material": market["Material"] or "Unknown",
        "Storage": market["Storage"] or "Unknown",
        "RAM": market["RAM"] or "Unknown",
        "Size": market["Size"] or "Unknown",
        "Damage_Level": grade_vals["Damage_Level"],
        "Water_Damage": grade_vals["Water_Damage"],
        "Scratch_Level": grade_vals["Scratch_Level"],
        "Dent_Level": grade_vals["Dent_Level"],
        "Screen_Crack": grade_vals["Screen_Crack"],
        "Broken_Parts": grade_vals["Broken_Parts"],
        "Price_Trend": market["Price_Trend"] or "Stable",
        "Demand_Level": market["Demand_Level"] or "Medium",
    }

    df = pd.DataFrame([row])[FEATURE_NAMES]  # เรียงคอลัมน์ให้ตรงกับตอนเทรนเป๊ะ

    for col, ftype in zip(FEATURE_NAMES, FEATURE_TYPES):
        if ftype == "c":
            valid_cats = categories.get(col, [])
            val = df.at[0, col]
            if val not in valid_cats:
                val = "Unknown" if "Unknown" in valid_cats else valid_cats[0]
                df.at[0, col] = val
            df[col] = pd.Categorical(df[col], categories=valid_cats)
        elif ftype == "int":
            df[col] = df[col].astype(int)
        else:
            df[col] = df[col].astype(float)

    return df, market


# ----------------------------------------------------------------------------
# 3.5 คำนวณ "ปัจจัยที่มีผลต่อราคา" จากโมเดลจริง (ไม่ใช่ตัวเลขตายตัว)
#     ใช้ pred_contribs ของ XGBoost: บอกว่าแต่ละฟีเจอร์ดันราคาขึ้น/ลงกี่บาท
#     แล้วรวมเป็น 4 กลุ่มที่ผู้ใช้เข้าใจง่าย
# ----------------------------------------------------------------------------
FACTOR_GROUPS = {
    "ราคาตลาดของรุ่นนี้": [
        "Market_Average_Price", "Market_Highest_Price", "Market_Lowest_Price",
        "Historical_Sold_Price", "market_price_range", "market_range_pct", "hist_vs_avg_ratio",
        "Price_Trend", "Demand_Level", "Brand", "Model", "Category", "Subcategory",
        "Color", "Material", "Storage", "RAM", "Size", "Weight",
        "Seller_Rating", "Seller_Total_Sales",
    ],
    "สภาพสินค้า (เกรด)": [
        "Seller_Condition_Percentage", "AI_Detected_Condition", "Damage_Level", "Water_Damage",
        "Scratch_Level", "Dent_Level", "Screen_Crack", "Broken_Parts", "num_visible_damage",
        "battery_health_pct", "condition_gap", "has_battery_info",
    ],
    "อุปกรณ์ที่ให้มา": ["num_accessories", "num_missing_accessories"],
    "อายุเครื่อง": ["Production_Year", "product_age_years"],
}


def compute_factors(dmatrix):
    """คืนค่า list ของปัจจัย: label, pct (สัดส่วนผลกระทบ 0-100), impact (บาท +/-)"""
    contribs = booster.predict(dmatrix, pred_contribs=True)[0]
    by_name = dict(zip(FEATURE_NAMES, contribs[:-1]))  # ตัวสุดท้ายคือ bias
    groups = []
    for label, cols in FACTOR_GROUPS.items():
        impact = float(sum(by_name.get(c, 0.0) for c in cols))
        groups.append({"label": label, "impact": impact})
    total = sum(abs(g["impact"]) for g in groups) or 1.0
    out = []
    for g in groups:
        pct = round(abs(g["impact"]) / total * 100)
        if pct < 1:
            continue  # ผลน้อยมาก ไม่ต้องโชว์ (เช่น อายุเครื่อง ที่โมเดลแทบไม่ใช้)
        out.append({"label": g["label"], "pct": pct, "impact": int(round(g["impact"] / 10) * 10)})
    out.sort(key=lambda f: -f["pct"])
    return out


def suggest_models(brand, model_name, limit=5):
    """หารุ่นที่ชื่อใกล้เคียง ไว้บอกผู้ใช้ตอนหาไม่เจอ"""
    import difflib
    nb, nm = _normalize_for_match(brand), _normalize_for_match(model_name)
    candidates = []
    for norm_key, (b, m) in NORMALIZED_LOOKUP.items():
        kb, km = norm_key.split("|||")
        if nb and kb != nb:
            continue
        score = difflib.SequenceMatcher(None, nm, km).ratio()
        if nm and nm in km:
            score += 0.5  # พิมพ์ไม่ครบ เช่น "iphone" -> iPhone 12, iPhone 13 ...
        candidates.append((score, f"{b} {m}"))
    candidates.sort(key=lambda t: -t[0])
    return [name for score, name in candidates[:limit] if score > 0.4]


# ----------------------------------------------------------------------------
# 4. API: รายชื่อยี่ห้อ/รุ่น สำหรับ dropdown หน้าบ้าน
# ----------------------------------------------------------------------------
@app.route("/api/options", methods=["GET"])
@swag_from({
    "tags": ["Product"],
    "summary": "ดึงรายชื่อยี่ห้อ/รุ่นทั้งหมด สำหรับทำ dropdown",
    "responses": {
        200: {
            "description": "รายชื่อยี่ห้อและรุ่นสินค้า",
            "examples": {
                "application/json": {
                    "brands": ["Apple", "Samsung"],
                    "brand_models": {"Apple": ["iPhone 13", "iPhone 14"], "Samsung": ["Galaxy S22"]}
                }
            }
        }
    }
})
def get_options():
    brand_models = {}
    for key in PRODUCT_LOOKUP.keys():
        brand, model_name = key.split("|||")
        brand_models.setdefault(brand, []).append(model_name)
    for b in brand_models:
        brand_models[b].sort()
    return jsonify({"brand_models": brand_models, "brands": sorted(brand_models.keys())})


# ----------------------------------------------------------------------------
# 5. API: ทายเกรดจากรูป (YOLO)
# ----------------------------------------------------------------------------
@app.route("/api/predict-grade", methods=["POST"])
@swag_from({
    "tags": ["Grade"],
    "summary": "ทายเกรดสภาพสินค้าจากรูปภาพ (YOLO classification)",
    "consumes": ["multipart/form-data"],
    "parameters": [
        {
            "name": "image", "in": "formData", "type": "file", "required": True,
            "description": "ไฟล์รูปภาพสินค้า (jpg/png)"
        }
    ],
    "responses": {
        200: {
            "description": "เกรดที่ทายได้ พร้อมค่าความมั่นใจ",
            "examples": {"application/json": {"grade": "B", "confidence": 0.51}}
        },
        400: {"description": "ไม่พบไฟล์รูปภาพ"},
        500: {"description": "YOLO model ยังไม่ได้โหลด"}
    }
})
def predict_grade():
    if YOLO_MODEL is None:
        return jsonify({"error": "YOLO model ยังไม่ได้โหลด (เช็ค ultralytics ติดตั้งหรือยัง)"}), 500
    if "image" not in request.files:
        return jsonify({"error": "ไม่พบไฟล์รูปภาพ"}), 400

    file = request.files["image"]
    # ใช้ชื่อไฟล์ชั่วคราวไม่ซ้ำกัน กันรูปของคนละ request ทับกันตอนมีหลายคนใช้พร้อมกัน
    import tempfile
    fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    file.save(tmp_path)

    try:
        results = YOLO_MODEL(tmp_path, verbose=False)
        r = results[0]
        top1_idx = int(r.probs.top1)
        confidence = float(r.probs.top1conf)
        class_name = r.names[top1_idx]
        grade = class_name.upper() if class_name.upper() in ("A", "B", "C") else "B"
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return jsonify({"grade": grade, "confidence": round(confidence, 3)})


# ----------------------------------------------------------------------------
# 6. API: ทายราคา (XGBoost)
# ----------------------------------------------------------------------------
@app.route("/api/predict-price", methods=["POST"])
@swag_from({
    "tags": ["Price"],
    "summary": "ทายราคาจากข้อมูลสินค้า (XGBoost)",
    "consumes": ["application/json"],
    "parameters": [{
        "name": "body", "in": "body", "required": True,
        "schema": {
            "type": "object",
            "properties": {
                "brand": {"type": "string", "example": "Apple"},
                "model": {"type": "string", "example": "iPhone 13"},
                "year": {"type": "integer", "example": 2021},
                "grade": {"type": "string", "example": "B", "enum": ["A", "B", "C"]},
                "accessories": {"type": "string", "example": "partial", "enum": ["full", "partial", "none"]},
            },
            "required": ["brand", "model"]
        }
    }],
    "responses": {
        200: {
            "description": "ผลการประเมินราคา",
            "examples": {"application/json": {
                "expected_price": 16800, "recommended_min": 15600, "recommended_max": 18000,
                "price_confidence": 0.86, "condition_note": "พบตำหนิเล็กน้อย...",
                "product": {"brand": "Apple", "model": "iPhone 13"},
                "factors": [{"label": "ราคาตลาดของรุ่นนี้", "pct": 70, "impact": -3500},
                            {"label": "สภาพสินค้า (เกรด)", "pct": 24, "impact": 1200},
                            {"label": "อุปกรณ์ที่ให้มา", "pct": 6, "impact": -250}],
                "reference": {"market_average_price": 21589, "historical_sold_price": 20456,
                               "category": "Mobile Phones", "subcategory": "Smartphone"}
            }}
        },
        400: {"description": "ข้อมูลไม่ครบ (ไม่ระบุยี่ห้อ/รุ่น)"},
        404: {"description": "ไม่พบรุ่นสินค้าในฐานข้อมูล (มี suggestions รุ่นที่ใกล้เคียงให้)"}
    }
})
def predict_price():
    data = request.get_json(force=True)

    brand = data.get("brand", "").strip()
    model_name = data.get("model", "").strip()
    year = data.get("year")
    grade = data.get("grade", "B").upper()
    accessories_level = data.get("accessories", "partial")

    if not brand or not model_name:
        return jsonify({"error": "กรุณาระบุยี่ห้อและรุ่นสินค้า"}), 400
    if not year:
        year = CURRENT_YEAR  # ไม่บังคับแล้ว — ทดสอบแล้วปีแทบไม่มีผลต่อราคาที่โมเดลทาย

    # ค้นหาแบบไม่สนตัวพิมพ์เล็ก/ใหญ่และช่องว่าง เช่น "s22" หรือ "iPhone14" ต้องเจอ
    resolved_brand, resolved_model = resolve_product(brand, model_name)
    if resolved_brand is None:
        suggestions = suggest_models(brand, model_name)
        msg = f"ไม่พบรุ่น {brand} {model_name} ในฐานข้อมูล"
        if suggestions:
            msg += " — หมายถึง: " + ", ".join(suggestions) + " ใช่ไหม?"
        else:
            msg += " กรุณาเลือกจากรายการ"
        return jsonify({"error": msg, "suggestions": suggestions}), 404
    brand, model_name = resolved_brand, resolved_model  # ใช้ชื่อจริงที่สะกดถูกต้องต่อจากนี้

    X, market = build_feature_row(brand, model_name, year, grade, accessories_level)
    dmatrix = xgb.DMatrix(X, enable_categorical=True)
    pred_log_or_raw = booster.predict(dmatrix)[0]
    factors = compute_factors(dmatrix)

    # ถ้าตอนเทรนใช้ log1p(price) ผลลัพธ์จะติดลบ/เล็กผิดปกติเทียบกับราคาตลาด
    # เช็คแบบง่าย: ถ้าค่าที่ได้ต่ำกว่า 50 ให้ถือว่าเป็นสเกล log แล้วแปลงกลับ
    if pred_log_or_raw < 50:
        price = float(np.expm1(pred_log_or_raw))
    else:
        price = float(pred_log_or_raw)

    price = max(price, 0)
    lo = round(price * 0.93 / 100) * 100
    hi = round(price * 1.07 / 100) * 100
    mid = round(price / 100) * 100

    # ---- คำนวณ "ความมั่นใจของราคาที่ประเมิน" (price_confidence) ----
    # แยกจาก confidence ของการตรวจเกรดจากรูป (คนละค่ากัน)
    # หลักการ: เทียบราคาที่โมเดลทายกับราคาตลาดอ้างอิงว่าใกล้เคียงกันแค่ไหน
    # (ยิ่งใกล้ราคาตลาด ยิ่งมั่นใจ) + ลดความมั่นใจถ้าข้อมูลราคาตลาดของสินค้านี้ไม่ครบ
    market_avg_raw = market["Market_Average_Price"] or 0
    hist_sold_raw = market["Historical_Sold_Price"] or 0

    if market_avg_raw > 0:
        price_diff_ratio = abs(mid - market_avg_raw) / market_avg_raw
    else:
        price_diff_ratio = 1.0  # ไม่มีราคาตลาดอ้างอิงเลย ถือว่าความมั่นใจต่ำสุด
    price_alignment = max(0.0, 1.0 - min(price_diff_ratio, 1.0))

    data_completeness = 1.0
    if market_avg_raw <= 0:
        data_completeness -= 0.25
    if hist_sold_raw <= 0:
        data_completeness -= 0.15

    price_confidence = round(0.5 + 0.45 * price_alignment * data_completeness, 2)
    price_confidence = min(max(price_confidence, 0.50), 0.97)

    return jsonify({
        "expected_price": mid,
        "recommended_min": lo,
        "recommended_max": hi,
        "price_confidence": price_confidence,
        "condition_note": GRADE_CONDITION_NOTE.get(grade, GRADE_CONDITION_NOTE["B"]),
        "product": {"brand": brand, "model": model_name},
        "factors": factors,
        "reference": {
            "market_average_price": round(market["Market_Average_Price"] or 0),
            "historical_sold_price": round(market["Historical_Sold_Price"] or 0),
            "category": market["Category"],
            "subcategory": market["Subcategory"],
        },
    })

@app.route("/")
def home():
    return "Backend Server is running!"

if __name__ == "__main__":
    # ใน Docker ปิด debug (ตั้ง FLASK_DEBUG=0 ใน docker-compose.yml) — debug=True อันตรายถ้าเปิดให้คนอื่นเข้า
    app.run(host="0.0.0.0", port=5000, debug=os.environ.get("FLASK_DEBUG", "1") == "1")