# chatbot_server.py
# Backend สำหรับ "AI ChatBot" (Module 1) — แชทบอทตอบคำถามทั่วไป
# (ราคา, สภาพสินค้า, นโยบาย, ค้นหาสินค้า ฯลฯ)
#
# หลักการทำงาน: Retrieval-based — ค้นหาคำถามใน dataset ที่ใกล้เคียงกับคำถาม
# ของผู้ใช้มากที่สุด แล้วตอบด้วยคำตอบที่เตรียมไว้ ("Expected_AI_Response")
# ซึ่งถูกออกแบบให้ตรงตาม Business Rules อยู่แล้ว (BR001-BR008)
#
# วิธีค้นหา: ผสม 2 แบบ + กฎช่วยดันตามคำสำคัญ (intent keyword boost)
#   1. Word-level TF-IDF (ตัดคำแบบง่าย: กลุ่มอักษรไทย/อังกฤษ/ตัวเลขต่อเนื่อง)
#   2. Char n-gram TF-IDF (จับความคล้ายแม้สะกด/เว้นวรรคไม่ตรงเป๊ะ)
#   3. เพิ่มคะแนนให้คำถามที่อยู่ใน intent category เดียวกับคำสำคัญที่เจอ
#      (เช่น เจอคำว่า "ราคา" -> ดันคำถามหมวด Pricing ให้คะแนนสูงขึ้น)
#      แก้ปัญหาที่ TF-IDF เพียงอย่างเดียวมักไปแมตช์ตาม "ชื่อสินค้า" ที่ซ้ำกัน
#      มากกว่าคำที่บ่งบอกเจตนาจริงของคำถาม (ราคา vs ตำหนิ vs สเปค ฯลฯ)
#
# คนละไฟล์กับ backend_server.py (ระบบประเมินราคา) เพราะเป็นคนละโมดูล/ฟีเจอร์
# ตามที่ QA แบ่งไว้ใน dataset (Module 1 = ChatBot)

import os
import json
import re

import pandas as pd
import numpy as np
from flask import Flask, request, jsonify
from flask_cors import CORS
from flasgger import Swagger, swag_from
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
CORS(app)

app.config["SWAGGER"] = {
    "title": "AI ChatBot — API",
    "uiversion": 3,
    "specs_route": "/apidocs/",
}
Swagger(app, template={
    "info": {
        "title": "AI ChatBot — API",
        "description": "แชทบอทตอบคำถามลูกค้าทั่วไป (ราคา/สภาพสินค้า/นโยบาย) แบบ retrieval-based",
        "version": "1.0.0",
    },
})

# ----------------------------------------------------------------------------
# 1. โหลด dataset คำถาม-คำตอบ
# ----------------------------------------------------------------------------
print("กำลังโหลด dataset แชทบอท...")
DATASET_PATH = os.path.join(BASE_DIR, "chatbot_dataset.json")
with open(DATASET_PATH, "r", encoding="utf-8") as f:
    RAW_RECORDS = json.load(f)

DF = pd.DataFrame(RAW_RECORDS)
print(f"โหลด chatbot_dataset.json สำเร็จ ({len(DF)} คำถาม-คำตอบ)")

# ----------------------------------------------------------------------------
# 2. เตรียมระบบค้นหา: word TF-IDF + char n-gram TF-IDF (ผสมกัน)
#    ตัดคำแบบง่าย (ไม่ต้องใช้ library ตัดคำภาษาไทยเพิ่ม): จับกลุ่มอักษรไทย
#    ต่อเนื่อง, อังกฤษต่อเนื่อง, ตัวเลข แยกเป็นคำ — ใช้ได้ดีเพราะคำถามใน
#    dataset ส่วนใหญ่มีช่องว่างคั่นระหว่างคำไทยกับคำอังกฤษ/ชื่อสินค้าอยู่แล้ว
# ----------------------------------------------------------------------------
QUESTIONS = DF["Question"].astype(str).tolist()


def _tokenize(text):
    return re.findall(r"[ก-๙]+|[A-Za-z]+|\d+", text)


WORD_VECTORIZER = TfidfVectorizer(analyzer=_tokenize, min_df=1, sublinear_tf=True)
WORD_MATRIX = WORD_VECTORIZER.fit_transform(QUESTIONS)

CHAR_VECTORIZER = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
CHAR_MATRIX = CHAR_VECTORIZER.fit_transform(QUESTIONS)

WORD_WEIGHT = 0.6   # น้ำหนักของ word-level TF-IDF ในคะแนนรวม (char-level ได้ 1-WORD_WEIGHT)
INTENT_BOOST = 0.28  # คะแนนเพิ่มให้คำถามที่อยู่ใน intent category ตรงกับคำสำคัญที่เจอ

print("เตรียมระบบค้นหา (word + char TF-IDF) สำเร็จ")

# คำสำคัญที่บ่งบอกเจตนา (intent) ของคำถาม — ใช้ดันคะแนนคำถามที่อยู่ใน
# หมวดเดียวกัน ป้องกันไม่ให้ TF-IDF เลือกตาม "ชื่อสินค้า" ที่ซ้ำกันเพียงอย่างเดียว
INTENT_KEYWORDS = {
    "Pricing": ["ราคา", "price", "เท่าไหร่", "ส่วนลด", "discount", "แพง", "ถูก", "expensive", "cheap"],
    "Product Info": ["ตำหนิ", "defect", "สภาพ", "condition", "สเปค", "spec", "รายละเอียด", "detail"],
    "Security/PDPA": ["เบอร์โทร", "phone", "email", "อีเมล", "ที่อยู่", "address", "ส่วนตัว", "personal"],
    "Discovery": ["แนะนำ", "recommend", "หมวด", "category", "ใกล้เคียง", "similar"],
    "Seller Info": ["ผู้ขาย", "seller", "เรตติ้ง", "rating"],
    "Logistics": ["จัดส่ง", "ส่งของ", "delivery", "shipping", "ขนส่ง"],
    "Policy": ["นโยบาย", "policy", "คืนสินค้า", "return", "รับประกัน", "warranty"],
}


def _inferred_intents(message: str):
    hits = set()
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(kw in message for kw in keywords):
            hits.add(intent)
    return hits


# ----------------------------------------------------------------------------
# 2.5 กันไม่ให้ "ทายมั่ว" เมื่อถามถึงสินค้าที่ไม่มีในฐานข้อมูลเลย (กัน BR001)
#    ปัญหาที่เจอจริง: ถ้าคำถามมีคำทั่วไปอย่าง "ราคา" ปนกับชื่อสินค้าที่ไม่มี
#    ในฐานข้อมูล (เช่น "Logitech G Pro X Superlight") ระบบ TF-IDF อาจไป
#    แมตช์กับคำถามสั้นๆ ทั่วไป (เช่น "ราคา?") ที่คะแนนสูงจากคำว่า "ราคา"
#    เพียงคำเดียว แล้วตอบราคาของสินค้าอื่นที่ไม่เกี่ยวข้องเลย (หลอนข้อมูล)
#    วิธีแก้: เก็บชื่อสินค้า/ยี่ห้อทั้งหมดที่มีจริงในฐานข้อมูลไว้ก่อน
#    ถ้าคำถามมีคำที่ดูเหมือนชื่อสินค้า (คำอังกฤษยาวๆ) แต่ไม่ตรงกับที่มีอยู่
#    เลยสักคำ ให้ตอบ fallback ทันที ไม่เดา
# ----------------------------------------------------------------------------
def _collect_known_product_tokens():
    tokens = set()
    for col in ["Brand", "Product_Name", "Model", "Category", "Subcategory"]:
        for val in DF[col].dropna().astype(str):
            for tok in _tokenize(val):
                if len(tok) >= 3 and tok.isascii():
                    tokens.add(tok.lower())
    return tokens


KNOWN_PRODUCT_TOKENS = _collect_known_product_tokens()

# คำทั่วไปที่ติดอยู่ในชื่อสินค้าหลายรุ่นมาก (pro/plus/max ฯลฯ) ไม่ควรใช้เป็น
# "หลักฐานว่ารู้จักสินค้านี้" เพราะไม่ได้บ่งชี้ตัวสินค้าจริง — ถ้าปล่อยไว้จะทำให้
# _has_unknown_product_mention พลาด (เจอ "pro" แล้วคิดว่ารู้จักสินค้า ทั้งที่คำ
# ที่บ่งชี้ตัวสินค้าจริงอย่าง "superlight" ไม่มีอยู่ในฐานข้อมูลเลย)
_GENERIC_PRODUCT_MODIFIERS = {"pro", "plus", "max", "mini", "lite", "air", "ultra", "se", "new", "gen"}

# คำศัพท์ทั่วไป (ไม่ใช่ชื่อสินค้า) ที่ไม่ควรเอามาเช็คว่า "รู้จักไหม" แม้จะเป็นคำอังกฤษ
_GENERIC_ENGLISH_WORDS = set()
for kws in INTENT_KEYWORDS.values():
    for kw in kws:
        if kw.isascii():
            _GENERIC_ENGLISH_WORDS.add(kw.lower())
_GENERIC_ENGLISH_WORDS |= {"the", "and", "for", "you", "your", "this", "that", "have", "has",
                            "does", "what", "how", "much", "many", "can", "could", "would"}
_GENERIC_ENGLISH_WORDS |= _GENERIC_PRODUCT_MODIFIERS


def _has_unknown_product_mention(message: str) -> bool:
    """True ถ้าข้อความมีคำที่ดูเหมือนชื่อสินค้า/ยี่ห้อ (อังกฤษ, ยาว >=3 ตัว,
    ไม่ใช่คำทั่วไปอย่าง pro/plus/max) แต่ไม่ตรงกับสินค้า/ยี่ห้อ/หมวดหมู่ใดๆ
    ที่มีอยู่จริงในฐานข้อมูลเลยสักคำ"""
    candidate_tokens = [
        tok.lower() for tok in _tokenize(message)
        if len(tok) >= 3 and tok.isascii() and tok.lower() not in _GENERIC_ENGLISH_WORDS
    ]
    if not candidate_tokens:
        return False  # ไม่มีคำที่ดูเหมือนชื่อสินค้าเลย ไม่ต้องเช็ค
    return not any(tok in KNOWN_PRODUCT_TOKENS for tok in candidate_tokens)


# ----------------------------------------------------------------------------
# 3. Business Rules — ข้อความ fallback มาตรฐาน (BR002)
# ----------------------------------------------------------------------------
FALLBACK_TH = "ขออภัย ขณะนี้ยังไม่มีข้อมูลสำหรับคำถามนี้"
FALLBACK_EN = "Sorry, there is currently no information available for this question."

SIMILARITY_THRESHOLD = 0.20  # คะแนนขั้นต่ำที่ยอมตอบ — ต่ำกว่านี้ถือว่า "ไม่เจอคำถามที่ตรงพอ"


def _is_english(text: str) -> bool:
    return len(re.findall(r"[\u0E00-\u0E7F]", text)) == 0


def find_best_match(user_message: str):
    """ค้นคำถามใน dataset ที่ใกล้เคียงกับ user_message มากที่สุด (ผสม word+char TF-IDF + intent boost)"""
    word_sim = cosine_similarity(WORD_VECTORIZER.transform([user_message]), WORD_MATRIX)[0]
    char_sim = cosine_similarity(CHAR_VECTORIZER.transform([user_message]), CHAR_MATRIX)[0]
    combined = WORD_WEIGHT * word_sim + (1 - WORD_WEIGHT) * char_sim

    hits = _inferred_intents(user_message)
    if hits:
        combined = combined + DF["Intent_Category"].isin(hits).values * INTENT_BOOST

    best_idx = int(np.argmax(combined))
    # combined อาจเกิน 1.0 ได้ เพราะ INTENT_BOOST บวกเพิ่มจากคะแนนความคล้ายที่
    # ใกล้ 1.0 อยู่แล้ว (ใช้แค่จัดอันดับเลือกคำถามที่ดีที่สุด ไม่ใช่ความน่าจะเป็นจริง)
    # ตอนแสดงผลเป็น "% ความมั่นใจ" ต้อง clamp ไว้ที่ 1.0 ไม่งั้นจะโชว์เกิน 100%
    best_score = min(float(combined[best_idx]), 1.0)
    return best_idx, best_score


# ----------------------------------------------------------------------------
# 4. API: ส่งข้อความคุยกับแชทบอท
# ----------------------------------------------------------------------------
def _confidence_level(score: float) -> str:
    """แบ่งระดับความมั่นใจเป็น 3 ระดับ ไว้ให้ฝั่งหน้าเว็บโชว์สี/label ได้ง่ายขึ้น"""
    if score >= 0.60:
        return "high"
    if score >= 0.35:
        return "medium"
    return "low"


# ----------------------------------------------------------------------------
# ปรับราคาในคำตอบให้ใกล้เคียงราคาตลาดจริงขึ้น — ไม่แตะไฟล์ dataset เลย
# (ทำตอน serve คำตอบเท่านั้น เพราะไม่มีเวลาให้ QA แก้ dataset ทัน deadline)
#
# ที่มา: เช็คราคาจริงในตลาด (เว็บค้นหา) เทียบกับราคาใน dataset พบว่า
# ราคาใน dataset ต่ำกว่าราคาตลาดจริงอย่างเป็นระบบ ประมาณ 4-5 เท่า
# (เช่น PS5 dataset=4,676 บาท vs ตลาดจริง ~18,790-30,990 บาท,
#      iPhone 13 dataset=3,313 บาท vs ตลาดจริง ~13,000-18,000 บาท)
#
# วิธีแก้: คูณตัวเลขราคาที่ฝังอยู่ในข้อความคำตอบ (Current_Price/Average_Market_Price)
# ด้วยตัวคูณคงที่ก่อนส่งออกไป — เป็นการ "ประมาณแก้ไข" ไม่ใช่ราคาที่แม่นยำ 100%
# ควรให้ QA ปรับราคาจริงใน dataset แทนในระยะยาว เมื่อมีเวลา
# ----------------------------------------------------------------------------
PRICE_CORRECTION_MULTIPLIER = 4.5


def _apply_price_correction(response_text: str, row) -> str:
    text = response_text
    for col in ["Current_Price", "Average_Market_Price"]:
        val = row.get(col)
        if val is None or pd.isna(val):
            continue
        original_str = f"{int(val):,}"
        if original_str not in text:
            continue  # ตัวเลขนี้ไม่ได้ปรากฏในข้อความ (เช่น คำถามไม่เกี่ยวกับราคา) ข้ามไป
        corrected_val = round(float(val) * PRICE_CORRECTION_MULTIPLIER)
        corrected_str = f"{corrected_val:,}"
        text = text.replace(original_str, corrected_str)
    return text


@app.route("/api/chat", methods=["POST"])
@swag_from({
    "tags": ["Chat"],
    "summary": "ส่งข้อความถามแชทบอท ได้คำตอบกลับตาม dataset (retrieval-based)",
    "consumes": ["application/json"],
    "parameters": [{
        "name": "body", "in": "body", "required": True,
        "schema": {
            "type": "object",
            "properties": {"message": {"type": "string", "example": "ราคา Sony PlayStation 5 เท่าไหร่คะ"}},
            "required": ["message"]
        }
    }],
    "responses": {
        200: {
            "description": "คำตอบจากแชทบอท",
            "examples": {"application/json": {
                "response": "ราคาปัจจุบันของ Sony PlayStation 5 อยู่ที่ 4,676 บาท (ราคาตลาดเฉลี่ย 5,942 บาท)",
                "confidence": 0.83,
                "intent_category": "Pricing",
                "matched_question": "ราคา Sony PlayStation 5 เท่าไหร่",
                "is_fallback": False
            }}
        },
        400: {"description": "ไม่พบข้อความคำถาม (message)"}
    }
})
def chat():
    data = request.get_json(force=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "กรุณาระบุข้อความคำถาม (message)"}), 400

    best_idx, best_score = find_best_match(message)

    # กัน "ทายมั่ว" — เช็คแค่ตอนคะแนนจับคู่ไม่สูงมากเท่านั้น (เช่น < 0.9)
    # ถ้าคะแนนสูงมากอยู่แล้ว (ใกล้ 1.0 คือคำถามตรงกับใน dataset แทบเป๊ะ) ให้เชื่อ
    # ผลนั้นเลย ไม่ต้องเช็คซ้ำ — ก่อนแก้จุดนี้เคยมีบั๊กที่เช็คทับคำตอบถูกไปด้วย
    # (แม้คะแนนจะเต็ม 1.000 ก็ยังโดนบล็อกเป็น fallback ผิดๆ ประมาณ 35% ของคำถามจริง)
    HIGH_CONFIDENCE_CUTOFF = 0.90
    if best_score < HIGH_CONFIDENCE_CUTOFF and _has_unknown_product_mention(message):
        fallback = FALLBACK_EN if _is_english(message) else FALLBACK_TH
        return jsonify({
            "response": fallback,
            "confidence": round(best_score, 3),
            "confidence_level": _confidence_level(best_score),
            "intent_category": "Fallback",
            "matched_question": None,
            "is_fallback": True,
        })

    if best_score < SIMILARITY_THRESHOLD:
        fallback = FALLBACK_EN if _is_english(message) else FALLBACK_TH
        return jsonify({
            "response": fallback,
            "confidence": round(best_score, 3),
            "confidence_level": _confidence_level(best_score),
            "intent_category": "Fallback",
            "matched_question": None,
            "is_fallback": True,
        })

    row = DF.iloc[best_idx]
    corrected_response = _apply_price_correction(row["Expected_AI_Response"], row)
    return jsonify({
        "response": corrected_response,
        "confidence": round(best_score, 3),
        "confidence_level": _confidence_level(best_score),
        "intent_category": row["Intent_Category"],
        "matched_question": row["Question"],
        "is_fallback": False,
    })


# ----------------------------------------------------------------------------
# 5. API: ข้อมูลสรุป dataset (ไว้เดโม/ดีบัก)
# ----------------------------------------------------------------------------
@app.route("/api/chat/stats", methods=["GET"])
@swag_from({
    "tags": ["Chat"],
    "summary": "ข้อมูลสรุป dataset ที่แชทบอทใช้ตอบ",
    "responses": {200: {"description": "จำนวนคำถามทั้งหมด และแยกตามหมวด intent"}}
})
def chat_stats():
    return jsonify({
        "total_questions": len(DF),
        "intent_categories": DF["Intent_Category"].value_counts().to_dict(),
    })


# ----------------------------------------------------------------------------
# 6. API: สุ่มตัวอย่างคำถาม (ไว้ทำปุ่มคำถามลัดในหน้าเว็บ ไม่ให้ซ้ำเดิมทุกครั้ง)
# ----------------------------------------------------------------------------
@app.route("/api/chat/sample-questions", methods=["GET"])
@swag_from({
    "tags": ["Chat"],
    "summary": "สุ่มคำถามตัวอย่างจาก dataset (คนละชุดทุกครั้งที่เรียก) สำหรับทำปุ่มคำถามลัด",
    "parameters": [{"name": "n", "in": "query", "type": "integer", "default": 4, "description": "จำนวนคำถามที่ต้องการ"}],
    "responses": {200: {"description": "รายการคำถามสุ่ม พร้อม intent category"}}
})
def sample_questions():
    n = request.args.get("n", default=4, type=int)
    n = max(1, min(n, 20))
    # สุ่มแบบกระจายหมวด intent ให้หลากหลาย ไม่ใช่สุ่มดิบๆ ที่อาจได้ Pricing รัว 4 ข้อ
    pool = DF[DF["Intent_Category"] != "Fallback"]
    categories = list(pool["Intent_Category"].unique())
    import random
    random.shuffle(categories)
    picked_rows = []
    for cat in categories[:n]:
        cat_rows = pool[pool["Intent_Category"] == cat]
        picked_rows.append(cat_rows.sample(1).iloc[0])
    return jsonify({
        "questions": [
            {"question": row["Question"], "intent_category": row["Intent_Category"]}
            for row in picked_rows
        ]
    })


@app.route("/")
def home():
    return "Chatbot Backend Server is running!"


if __name__ == "__main__":
    # ใน Docker ปิด debug (ตั้ง FLASK_DEBUG=0 ใน docker-compose.yml)
    app.run(host="0.0.0.0", port=5001, debug=os.environ.get("FLASK_DEBUG", "1") == "1")
