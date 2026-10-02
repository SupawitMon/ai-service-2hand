# chatbot_server.py  (v2)
# แชทบอท 2HandToYou — ออกแบบตามเกณฑ์ที่ SE กำหนด (AI Integration Meeting 30 Sep 2026)
#
#  Intent       : ตัวจำแนก intent (TF-IDF char+word + Logistic Regression) เทรนจาก dataset 500 ข้อ
#                 + ตัวอย่างเพิ่มใน kb/intent_train_extra.json โดย "ซ่อนชื่อสินค้า/ผู้ขาย/ตัวเลข"
#                 ก่อนเทรน ให้โมเดลเรียนรู้จากเจตนาของประโยค ไม่ใช่จาก keyword หรือชื่อสินค้า
#  Context      : จำบริบทแยกตาม session_id (สินค้า/ผู้ขาย/หมวดล่าสุด + 5 turn) หมดอายุ 30 นาที
#  Grounding    : คำตอบเรื่องสินค้า/ราคา/ผู้ขาย สร้างจาก KB (kb/*.json) เท่านั้น และแนบ source ทุกครั้ง
#  Fallback     : ความมั่นใจต่ำกว่า threshold หรือไม่รู้จักสินค้า -> บอกตรงๆ + เสนอตัวเลือก
#  Traceability : ทุก request มี request_id (รับจาก header X-Request-ID ได้) + log JSONL (ปิดบังข้อมูลส่วนตัว)
#  Latency      : วัดทุก request และดูค่า P50/P95/P99 ได้ที่ GET /api/metrics

import os, re, json, time, uuid, logging, threading, datetime
from logging.handlers import TimedRotatingFileHandler
from collections import deque, Counter, defaultdict

import numpy as np
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from flasgger import Swagger, swag_from
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.metrics.pairwise import cosine_similarity

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KB_DIR = os.path.join(BASE_DIR, "kb")
LOG_DIR = os.environ.get("CHAT_LOG_DIR", os.path.join(BASE_DIR, "logs"))

# ---------------------------------------------------------------- ค่าตั้ง (ปรับผ่าน env ได้)
FALLBACK_THRESHOLD = float(os.environ.get("FALLBACK_THRESHOLD", "0.25"))   # ต่ำกว่านี้ = ไม่แน่ใจ (เลือกจาก 5-fold CV: ตอบ 81% แม่น 95.5%)
HIGH_CONFIDENCE = float(os.environ.get("HIGH_CONFIDENCE", "0.60"))
SESSION_TTL_SEC = int(os.environ.get("SESSION_TTL_SEC", "1800"))           # 30 นาที
SESSION_MAX_TURNS = 5
LOG_RETENTION_DAYS = int(os.environ.get("LOG_RETENTION_DAYS", "30"))
LOG_ACCESS_TOKEN = os.environ.get("LOG_ACCESS_TOKEN", "")                  # ว่าง = ปิด endpoint ดู log

app = Flask(__name__)
CORS(app, expose_headers=["X-Request-ID", "X-Response-Time-ms"])
app.config["SWAGGER"] = {"title": "2HandToYou AI ChatBot API", "uiversion": 3, "specs_route": "/apidocs/"}
Swagger(app, template={"info": {"title": "2HandToYou AI ChatBot API", "version": "2.0.0",
        "description": "แชทบอทถาม-ตอบ + ตัวจำแนก intent สำหรับแชทบอทเจรจา (grounded on KB)"}})


# ================================================================ 1. โหลด KB
def _load(name):
    with open(os.path.join(KB_DIR, name), encoding="utf-8") as f:
        return json.load(f)


with open(os.path.join(BASE_DIR, "chatbot_dataset.json"), encoding="utf-8") as f:
    DATASET = json.load(f)
CATALOG = _load("product_catalog.json")
SELLERS = _load("sellers.json")
TRENDS = _load("category_trends.json")
KB_META = _load("kb_meta.json")
PRICE_TABLE = _load("price_table.json")["base_price_good"]   # ราคามือสองสภาพดีต่อรุ่น
EXTRA = {k: v for k, v in _load("intent_train_extra.json").items() if not k.startswith("_")}

BY_NAME = defaultdict(list)
for it in CATALOG:
    BY_NAME[it["name"]].append(it)
PRODUCT_NAMES = sorted(BY_NAME)
CATEGORIES = sorted({it["category"] for it in CATALOG})
BRANDS = sorted({it["brand"] for it in CATALOG}, key=len, reverse=True)
print(f"KB v{KB_META['kb_version']}: {len(CATALOG)} listings / {len(PRODUCT_NAMES)} products / {len(SELLERS)} sellers")

# ================================================================ 2. intent ทั้งหมด + หมวดของ SE
INTENT_FROM_DATASET = {
    "Product Price": "price", "Price Comparison": "price_compare", "Market Trend": "market_trend",
    "Product Condition": "condition", "Product Specification": "spec", "Product Availability": "availability",
    "Seller Reputation": "seller_reputation", "Seller Negotiation": "seller_negotiation",
    "Brand Search": "search", "Category Search": "search", "Search Assistance": "search",
    "Product Recommendation": "recommend", "Similar Product": "similar",
    "Shipping": "shipping", "Delivery": "shipping", "Warranty": "warranty",
    "Discount": "discount", "Promotion": "discount", "Marketplace Rule": "policy", "Policy Question": "policy",
    "Report Seller": "report_seller", "Report Product": "report_product", "Complaint": "complaint",
    "Sensitive Information": "pii", "Greeting": "greeting", "Farewell": "farewell",
    "Off-topic Question": "off_topic", "Unknown Question": "off_topic",
}
INTENT_CATEGORY = {
    "price": "Pricing", "price_compare": "Pricing", "market_trend": "Pricing",
    "condition": "Product Info", "spec": "Product Info", "availability": "Product Info",
    "seller_reputation": "Seller Info", "seller_negotiation": "Seller Info",
    "search": "Discovery", "recommend": "Discovery", "similar": "Discovery",
    "shipping": "Logistics", "warranty": "Logistics", "discount": "Policy", "policy": "Policy",
    "report_seller": "Support", "report_product": "Support", "complaint": "Support",
    "pii": "Security/PDPA", "greeting": "Conversational", "farewell": "Conversational",
    "off_topic": "Fallback", "offer": "Negotiation",
}
NEEDS_PRODUCT = {"price", "price_compare", "condition", "spec", "availability", "similar", "report_product"}
NEEDS_SELLER = {"seller_reputation", "seller_negotiation", "report_seller"}

# ================================================================ 3. จับ entity: สินค้า / ผู้ขาย / หมวด / งบ / ราคาเสนอ
TH_ALIASES = [("ไอโฟน", "iphone "), ("ไอแพด", "ipad "), ("แมคบุ๊ค", "macbook "), ("แมคบุ๊ก", "macbook "),
              ("ซัมซุง", "samsung "), ("กาแล็กซี่", "galaxy "), ("เพลย์", "playstation "), ("นินเทนโด", "nintendo "),
              ("สวิตช์", "switch "), ("แอร์พอด", "airpods "), ("โซนี่", "sony "), ("แคนนอน", "canon "), ("เลอโนโว", "lenovo ")]
ALIASES = {"ps5": "Sony PlayStation 5", "ps4pro": "Sony PlayStation 4 Pro", "ps4": "Sony PlayStation 4 Pro",
           "steamdeck": "Valve Steam Deck 256GB", "switcholed": "Nintendo Switch OLED", "switchlite": "Nintendo Switch Lite",
           "xboxs": "Microsoft Xbox Series S", "xboxx": "Microsoft Xbox Series X", "airpodspro": "Apple AirPods Pro Gen 2",
           "dualsense": "Sony PS5 DualSense Controller", "a7iii": "Sony Alpha A7 III", "x1carbon": "Lenovo ThinkPad X1 Carbon"}


def norm(s):
    s = s.lower()
    for th, en in TH_ALIASES:
        s = s.replace(th, en)
    return re.sub(r"[^a-z0-9ก-๙]", "", s)


# key ของแต่ละรุ่น: ชื่อเต็ม และชื่อที่ตัดยี่ห้อออก (เช่น "iphone13")
PRODUCT_KEYS = []
for n in PRODUCT_NAMES:
    brand = BY_NAME[n][0]["brand"]
    for k in {norm(n), norm(n[len(brand):]) if n.startswith(brand) else norm(n)}:
        if len(k) >= 4:
            PRODUCT_KEYS.append((k, n))
for a, n in ALIASES.items():
    PRODUCT_KEYS.append((a, n))
PRODUCT_KEYS.sort(key=lambda kn: -len(kn[0]))

SERIES_WORDS = {"iphone", "ipad", "macbook", "galaxy", "playstation", "xbox", "switch", "pixel", "redmi", "poco",
                "airpods", "watch", "thinkpad", "zenbook", "vivobook", "ideapad", "legion", "pavilion", "alpha",
                "eos", "matepad", "reno", "find", "ps", "imac", "rog", "omen", "inspiron", "latitude", "xps"}


def find_product(text):
    t = norm(text)
    for k, n in PRODUCT_KEYS:   # ยาวสุดก่อน -> "iphone13pro" ชนะ "iphone13"
        if k in t:
            return n
    return None


def find_unknown_model(text):
    """คืนชื่อรุ่นที่ผู้ใช้พิมพ์มาแต่ไม่มีใน KB เช่น 'iphone 15' (ใช้เมื่อ find_product ไม่เจอ)"""
    low = text.lower()
    for th, en in TH_ALIASES:
        low = low.replace(th, en)
    # ชื่อซีรีส์ + คำต่อท้ายไม่เกิน 3 คำ โดยต้องมีตัวเลขอยู่ด้วย เช่น "iphone 16 pro max", "galaxy z fold 5", "macbook pro m4"
    m = re.search(r"\b(" + "|".join(sorted(SERIES_WORDS, key=len, reverse=True)) + r")((?:\s*[a-z0-9]+){1,4})", low)
    if not m:
        return None
    words, out = m.group(2).split(), []
    for w in words:
        out.append(w)
        if re.search(r"\d", w):
            while len(out) < len(words) and words[len(out)] in ("pro", "max", "plus", "ultra", "mini", "lite", "fe"):
                out.append(words[len(out)])
            return (m.group(1) + " " + " ".join(out)).strip()
    return None


def similar_names(text, limit=5):
    low = norm(text)
    series = next((w for w in SERIES_WORDS if w in low), None)
    if series:
        return [n for n in PRODUCT_NAMES if series in norm(n)][:limit]
    return []


SELLER_RE = re.compile(r"\b[sS]\d{5}\b")

CATEGORY_SYNONYMS = {
    "Mobile Phone": ["มือถือ", "โทรศัพท์", "สมาร์ทโฟน", "smartphone", "phone", "mobile"],
    "Laptop": ["โน้ตบุ๊ค", "โน๊ตบุ๊ค", "โน้ตบุ๊ก", "แล็ปท็อป", "laptop", "notebook"],
    "Tablet": ["แท็บเล็ต", "แทปเลต", "tablet"], "Camera": ["กล้อง", "camera"],
    "Gaming": ["เกม", "เครื่องเล่นเกม", "console", "gaming"], "Computer": ["คอมพิวเตอร์", "คอม", "pc", "desktop"],
    "Fashion": ["แฟชั่น", "เสื้อ", "รองเท้า", "กางเกง", "fashion", "shoes", "jacket"],
    "Furniture": ["เฟอร์นิเจอร์", "โต๊ะ", "เตียง", "โซฟา", "furniture"], "Books": ["หนังสือ", "book"],
    "Sports": ["กีฬา", "ไม้แบด", "เทนนิส", "จักรยาน", "sport"], "Home Appliances": ["เครื่องใช้ไฟฟ้า", "home appliance"],
    "Musical Instruments": ["เครื่องดนตรี", "กีตาร์", "คีย์บอร์ด", "guitar", "instrument"],
    "Collectibles": ["ของสะสม", "ฟิกเกอร์", "โมเดล", "figure", "collectible"], "Accessories": ["อุปกรณ์เสริม", "หูฟัง", "accessor"],
    "Automotive Parts": ["อะไหล่รถ", "ยางรถ", "แบตรถ", "auto part", "automotive"], "Others": [],
}


def find_category(text):
    low = text.lower()
    for c in CATEGORIES:
        if c.lower() in low:
            return c
    for c, words in CATEGORY_SYNONYMS.items():
        if c not in CATEGORIES:
            continue
        for w in words:
            # คำอังกฤษต้องเป็นคำเต็ม ("phone" ต้องไม่ไปตรงกับ "iphone")
            if (re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low) if w.isascii() else w in low):
                return c
    return None


def find_brand(text):
    low = text.lower()
    for b in BRANDS:
        if re.search(r"(?<![a-z])" + re.escape(b.lower()) + r"(?![a-z])", low):
            return b
    return None


TH_NUM = {"หนึ่ง": 1, "นึง": 1, "สอง": 2, "สาม": 3, "สี่": 4, "ห้า": 5, "หก": 6, "เจ็ด": 7, "แปด": 8, "เก้า": 9}


def extract_amount(text):
    """ดึงจำนวนเงินจากข้อความ: '15000', '15,000', '15k', '1.5หมื่น', 'หมื่นห้า', '9 พัน'"""
    t = text.replace(",", "").lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(k|พัน|หมื่น)", t)
    if m:
        return int(float(m.group(1)) * {"k": 1000, "พัน": 1000, "หมื่น": 10000}[m.group(2)])
    m = re.search(r"หมื่น(หนึ่ง|นึง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า)?", t)
    if m:
        return 10000 + (TH_NUM.get(m.group(1), 0) * 1000 if m.group(1) else 0)
    m = re.search(r"(?<![a-z\d])(\d{3,7})(?!\d)", re.sub(r"\b[s]\d{5}\b", "", t))
    return int(m.group(1)) if m else None


def extract_budget(text):
    if re.search(r"งบ|budget|ไม่เกิน|under|ต่ำกว่า|below|ภายใน", text.lower()):
        return extract_amount(text)
    return None


_KNOWN_TOKENS = set()
for _it in CATALOG:
    for _f in ("name", "brand", "category", "subcategory"):
        _KNOWN_TOKENS |= set(re.findall(r"[a-z]{4,}", _it[_f].lower()))
for _ws in CATEGORY_SYNONYMS.values():
    for _w in _ws:
        _KNOWN_TOKENS |= set(re.findall(r"[a-z]{4,}", _w))
_KNOWN_TOKENS |= set(SERIES_WORDS)
_EN_COMMON = set("""which what when where who whom whose why how have has had does done doing would could should
shall will there their them they this that these those with without from your yours about above below under over
into onto please anything something everything nothing some many much more most less very just like also only
recommend recommendation recommendations suggest suggestion show find looking look need want good best better
cheap cheaper price prices priced pricing budget items item products product sale sell sells selling sold
available availability stock seller sellers shop store buy buying bought purchase order orders get give gift
here there sure okay thanks thank hello hey morning afternoon evening any other others similar alternative
alternatives option options model models brand brands category categories used second hand secondhand condition
cost costs much many under around within less than worth deal deals value money baht thb sneaker sneakers
shoes headphone headphones earbuds console consoles gaming phones laptops cameras tablets watch watches""".split())


def unknown_noun(text):
    """คำนามภาษาอังกฤษที่ไม่ใช่สินค้า/ยี่ห้อ/หมวดใน KB เช่น 'crypto' (ใช้เมื่อหาสินค้า/หมวด/ยี่ห้อไม่เจอ)"""
    for w in re.findall(r"[a-z]{4,}", text.lower()):
        if w not in _KNOWN_TOKENS and w not in _EN_COMMON:
            return w
    return None


def is_english(text):
    return not re.search(r"[\u0E00-\u0E7F]", text)


# ================================================================ 4. ตัวจำแนก intent
def mask(text):
    """ซ่อนชื่อสินค้า/ยี่ห้อ/ผู้ขาย/ตัวเลข ก่อนจำแนก -> โมเดลดูเจตนาของประโยค ไม่ใช่ชื่อสินค้า"""
    t = re.sub(r"\[image:[^\]]*\]", " ", text, flags=re.I)
    t = SELLER_RE.sub(" ", t)
    low = t.lower()
    for n in sorted(PRODUCT_NAMES, key=len, reverse=True):
        low = low.replace(n.lower(), " สินค้าxx ")
    for b in BRANDS:
        low = re.sub(r"(?<![a-z])" + re.escape(b.lower()) + r"(?![a-z])", " สินค้าxx ", low)
    low = re.sub(r"\d[\d,\.]*", " 9 ", low)
    return re.sub(r"\s+", " ", low).strip()


def _tok(text):
    return re.findall(r"[ก-๙]+|[a-z]+|\d+", text)


def _train_classifier():
    X, y = [], []
    for d in DATASET:
        lab = INTENT_FROM_DATASET.get(d["Intent"])
        if lab:
            X.append(mask(d["Question"])); y.append(lab)
    for lab, exs in EXTRA.items():
        for e in exs:
            X.append(mask(e)); y.append(lab)
    feats = FeatureUnion([
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True, min_df=1)),
        ("word", TfidfVectorizer(analyzer=_tok, sublinear_tf=True)),
    ])
    clf = Pipeline([("f", feats), ("lr", LogisticRegression(C=8, max_iter=3000, class_weight="balanced"))])
    clf.fit(X, y)
    return clf, len(X)


CLASSIFIER, N_TRAIN = _train_classifier()
print(f"เทรนตัวจำแนก intent สำเร็จ ({N_TRAIN} ตัวอย่าง, {len(CLASSIFIER.classes_)} intents)")

# ใช้หา "คำถามใน dataset ที่ใกล้ที่สุด" แนบไว้เป็นหลักฐานประกอบ (matched_question)
_Q = [d["Question"] for d in DATASET]
_QVEC = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4)).fit(_Q)
_QMAT = _QVEC.transform(_Q)


# entity ที่อยู่ในข้อความเป็นหลักฐานของเจตนา: มีรหัสผู้ขาย -> น่าจะถามเรื่องผู้ขาย, มีชื่อรุ่น -> ถามเรื่องสินค้า
ENTITY_COMPAT = {
    "seller": {"seller_reputation", "seller_negotiation", "report_seller", "pii", "complaint"},
    "product": {"price", "price_compare", "condition", "spec", "availability", "similar", "discount",
                "shipping", "warranty", "report_product", "offer"},
    "category": {"search", "recommend", "market_trend"},
    "budget": {"search", "recommend"},
}
ENTITY_BOOST = float(os.environ.get("ENTITY_BOOST", "2.0"))


def entity_flags(text):
    return {"seller": bool(SELLER_RE.search(text)), "product": find_product(text) is not None,
            "category": find_category(text) is not None and find_product(text) is None,
            "budget": extract_budget(text) is not None}


def rerank(probs, classes, flags):
    w = np.ones(len(classes))
    for ent, on in flags.items():
        if on:
            w *= np.array([ENTITY_BOOST if c in ENTITY_COMPAT[ent] else 1.0 for c in classes])
    p = probs * w
    return p / p.sum()


def classify(text, allow_offer=True):
    """allow_offer=False สำหรับแชทถาม-ตอบ (เสนอราคาได้เฉพาะในแชทเจรจา)"""
    probs = rerank(CLASSIFIER.predict_proba([mask(text)])[0], CLASSIFIER.classes_, entity_flags(text))
    order = np.argsort(probs)[::-1]
    ranked = [(CLASSIFIER.classes_[i], float(probs[i])) for i in order]
    # "offer" ใช้ได้เมื่อมีจำนวนเงินจริง และไม่ได้พูดถึงงบประมาณ (งบ/ไม่เกิน = การค้นหา ไม่ใช่การเสนอราคา)
    offer_ok = allow_offer and extract_amount(text) is not None and extract_budget(text) is None
    if not offer_ok:
        ranked = [r for r in ranked if r[0] != "offer"]
        total = sum(p for _, p in ranked) or 1.0
        ranked = [(a, p / total) for a, p in ranked]
    top = ranked[:3]
    return top[0][0], top[0][1], top


# Guardrail ด้านความปลอดภัย (BR003): คำขอข้อมูลติดต่อส่วนตัว ต้องถูกปฏิเสธเสมอ ไม่ขึ้นกับความมั่นใจของโมเดล
PII_GUARD = re.compile(
    r"(แอด\s*ไลน์|add\s*line|ไลน์\s*(ไอดี|id)|line\s*id|เบอร์|phone\s*(number|no)|อีเมล|e-?mail|"
    r"เฟส(บุ๊[คก])?|facebook|\big\b|instagram|ช่องทางติดต่อ|contact\s*(info|number|details)|"
    r"(ขอ|give|send|share)[^\n]{0,20}(ที่อยู่|address))", re.I)


def apply_guardrails(text, intent, conf):
    if PII_GUARD.search(text) and intent not in ("shipping", "complaint", "report_seller", "report_product"):
        return "pii", max(conf, 0.9), "pii_guardrail"
    return intent, conf, None


def nearest_question(text):
    sims = cosine_similarity(_QVEC.transform([text]), _QMAT)[0]
    i = int(np.argmax(sims))
    return DATASET[i]["Question"], DATASET[i]["Dataset_ID"], float(sims[i])


# ================================================================ 5. Session (บริบทต่อเนื่อง แยกผู้ใช้)
class SessionStore:
    def __init__(self):
        self._s, self._lock = {}, threading.Lock()

    def get(self, sid):
        now = time.time()
        with self._lock:
            for k in [k for k, v in self._s.items() if now - v["updated"] > SESSION_TTL_SEC]:
                del self._s[k]
            if sid not in self._s:
                self._s[sid] = {"product": None, "seller": None, "category": None, "intent": None,
                                "turns": deque(maxlen=SESSION_MAX_TURNS), "updated": now}
            self._s[sid]["updated"] = now
            return self._s[sid]

    def count(self):
        return len(self._s)


SESSIONS = SessionStore()

# ================================================================ 6. สร้างคำตอบจาก KB (grounded)
def baht(n):
    return f"{int(round(n)):,}"


def T(en, th, msg):
    return en if is_english(msg) else th


def listings_summary(name):
    items = sorted(BY_NAME[name], key=lambda x: x["price"])
    return items, min(i["price"] for i in items), max(i["price"] for i in items)


COND_RANK = {"New": 0, "Like New": 1, "Good": 2, "Fair": 3, "For Parts": 4}


def cond_label(key, msg):
    if key == "For Parts":
        return T("For Parts (broken)", "เครื่องเสีย/ขายเป็นอะไหล่", msg)
    return key


def parts_note(items, msg):
    """ถ้ามีแต่เครื่องเสีย บอกให้ชัดว่าราคาถูกเพราะอะไร พร้อมราคาเครื่องสภาพดี (จาก kb/price_table.json) ไว้เทียบ"""
    if items and all(i["condition_key"] == "For Parts" for i in items) and items[0]["name"] in PRICE_TABLE:
        good = PRICE_TABLE[items[0]["name"]]
        return T(f" ⚠️ All listings are broken units sold for parts, so prices are far below a working unit (about THB {baht(good)} in good condition).",
                 f" ⚠️ ทุกรายการเป็นเครื่องเสีย ขายเป็นอะไหล่ ใช้งานไม่ได้เต็มระบบ ราคาจึงต่ำกว่าเครื่องปกติมาก (เครื่องสภาพดีราคาตลาดประมาณ {baht(good)} บาท)", msg)
    return ""


def _pt_ref(items):
    return [f"price_table:{items[0]['name']}"] if parts_note(items, "x") else []


def ans_price(ctx, msg):
    items, lo, hi = listings_summary(ctx["product"])
    by_cond = defaultdict(list)
    for i in items:
        by_cond[i["condition_key"]].append(i)
    parts = [f"{cond_label(c, msg)} {baht(min(x['price'] for x in v))}" + (f"–{baht(max(x['price'] for x in v))}" if len(v) > 1 else "")
             for c, v in sorted(by_cond.items(), key=lambda kv: COND_RANK.get(kv[0], 9))]
    ids = [i["listing_id"] for i in items]
    return T(f"{ctx['product']}: {len(items)} listings, THB {baht(lo)}–{baht(hi)} ({'; '.join(parts)}).",
             f"{ctx['product']} มีในระบบ {len(items)} รายการ ราคา {baht(lo)}–{baht(hi)} บาท (แยกตามสภาพ: {' / '.join(parts)} บาท)",
             msg) + parts_note(items, msg), ids + _pt_ref(items)


def _pick_listing(ctx):
    items = BY_NAME[ctx["product"]]
    if ctx.get("seller"):
        own = [i for i in items if i["seller_id"] == ctx["seller"]]
        if own:
            return own[0]
    working = [i for i in items if i["condition_key"] != "For Parts"]
    return min(working or items, key=lambda x: x["price"])


def ans_price_compare(ctx, msg):
    it = _pick_listing(ctx)
    diff = (it["price"] - it["market_price"]) / it["market_price"] * 100
    word_th = "ถูกกว่าราคาตลาด" if diff < -1 else "สูงกว่าราคาตลาด" if diff > 1 else "ใกล้เคียงราคาตลาด"
    word_en = "below market" if diff < -1 else "above market" if diff > 1 else "close to market"
    return T(f"{it['name']} ({it['condition_key']}, seller {it['seller_id']}) is THB {baht(it['price'])} vs market THB {baht(it['market_price'])} — {word_en} ({diff:+.0f}%).",
             f"{it['name']} ({it['condition_key']}, ผู้ขาย {it['seller_id']}) ราคา {baht(it['price'])} บาท เทียบราคาตลาดสภาพเดียวกัน {baht(it['market_price'])} บาท — {word_th} ({diff:+.0f}%)",
             msg), [it["listing_id"]]


def ans_market_trend(ctx, msg):
    cat = ctx.get("category") or (BY_NAME[ctx["product"]][0]["category"] if ctx.get("product") else None)
    if not cat:
        return None, []
    tr = TRENDS.get(cat)
    th = {"up": "ปรับขึ้นเล็กน้อย", "down": "ลดลงเล็กน้อย", "stable": "ค่อนข้างคงที่"}
    if not tr:
        return T(f"There is no price-trend data for {cat} in the system yet.",
                 f"ยังไม่มีข้อมูลแนวโน้มราคาของหมวด {cat} ในระบบ", msg), ["category_trends"]
    return T(f"Over the past 3 months, average prices for {cat} have been { {'up':'rising slightly','down':'declining slightly','stable':'fairly stable'}[tr]} (historical data in the system).",
             f"ในช่วง 3 เดือนที่ผ่านมา ราคาเฉลี่ยหมวด {cat} {th[tr]} (จากสถิติราคาย้อนหลังในระบบ)", msg), [f"category_trends:{cat}"]


def ans_condition(ctx, msg):
    items = BY_NAME[ctx["product"]]
    c = Counter(i["condition"] for i in items)
    lines = ", ".join(f"{cond_label(k.split(' / ')[0], msg)} ×{v}" for k, v in c.most_common())
    if ctx.get("seller"):
        it = _pick_listing(ctx)
        return T(f"{it['name']} from seller {it['seller_id']} is in {it['condition']} condition.",
                 f"{it['name']} ของผู้ขาย {it['seller_id']} อยู่ในสภาพ {it['condition']}", msg), [it["listing_id"]]
    return T(f"{ctx['product']} is available in these conditions: {lines}.",
             f"{ctx['product']} ในระบบมีสภาพ: {lines}", msg) + parts_note(items, msg), [i["listing_id"] for i in items] + _pt_ref(items)


def ans_spec(ctx, msg):
    it = _pick_listing(ctx)
    return T(f"{it['name']} — brand {it['brand']}, category {it['category']} / {it['subcategory']}. {it['description']}",
             f"{it['name']} ยี่ห้อ {it['brand']} หมวด {it['category']} / {it['subcategory']} — {it['description']}",
             msg), [it["listing_id"]]


def ans_availability(ctx, msg):
    items = BY_NAME[ctx["product"]]
    return T(f"Yes, {ctx['product']} is still available ({len(items)} listings).",
             f"{ctx['product']} ยังมีสินค้าพร้อมขาย {len(items)} รายการค่ะ", msg) + parts_note(items, msg), [i["listing_id"] for i in items] + _pt_ref(items)


def ans_seller(ctx, msg, kind):
    s = SELLERS.get(ctx["seller"])
    if not s:
        return T(f"Seller {ctx['seller']} was not found in the system.", f"ไม่พบผู้ขาย {ctx['seller']} ในระบบ", msg), []
    if kind == "seller_negotiation":
        return T(f"Seller {s['seller_id']} accepted price negotiation in about {s['negotiation_rate']}% of past orders.",
                 f"ผู้ขาย {s['seller_id']} ยอมต่อรองราคาสำเร็จประมาณ {s['negotiation_rate']}% ของออเดอร์ที่ผ่านมา", msg), [f"seller:{s['seller_id']}"]
    note_th = "เรตติ้งดี น่าเชื่อถือ" if s["rating"] >= 4 else "เรตติ้งปานกลาง ควรตรวจสอบเพิ่ม" if s["rating"] >= 3 else "เรตติ้งค่อนข้างต่ำ ควรระวัง"
    return T(f"Seller {s['seller_id']}: rating {s['rating']}/5, {s['total_sales']} completed sales, {s['response_rate']}% response rate.",
             f"ผู้ขาย {s['seller_id']} คะแนนรีวิว {s['rating']}/5 ขายสำเร็จ {s['total_sales']} รายการ อัตราตอบกลับ {s['response_rate']}% — {note_th}",
             msg), [f"seller:{s['seller_id']}"]


def _top_products(items, n=4):
    best = {}
    for i in sorted(items, key=lambda x: x["price"]):
        best.setdefault(i["name"], i)
    return list(best.values())[:n]


def ans_search(ctx, msg, kind):
    items = CATALOG
    brand, cat, budget = find_brand(msg), ctx.get("category"), ctx.get("budget")
    if kind == "similar" and ctx.get("product"):
        base = BY_NAME[ctx["product"]][0]
        cat = base["category"]
        ref = min(i["price"] for i in BY_NAME[ctx["product"]])
        items = sorted([i for i in CATALOG if i["category"] == cat and i["name"] != ctx["product"]],
                       key=lambda x: abs(x["price"] - ref))
    else:
        if brand:
            items = [i for i in items if i["brand"] == brand]
        if cat:
            items = [i for i in items if i["category"] == cat]
        if kind == "recommend":
            items = [i for i in items if SELLERS.get(i["seller_id"], {}).get("rating", 0) >= 4] or items
    if not re.search(r"อะไหล่|parts|เสีย|broken", msg.lower()):
        items = [i for i in items if i["condition_key"] != "For Parts"]
    if budget:
        items = [i for i in items if i["price"] <= budget]
    if not items:
        return T("No matching items were found in the system.", "ไม่พบสินค้าที่ตรงเงื่อนไขในระบบ" +
                 (f" (งบไม่เกิน {baht(budget)} บาท)" if budget else ""), msg), []
    top = _top_products(items) if kind != "similar" else _top_products(items[:12])
    lst = ", ".join(f"{i['name']} {baht(i['price'])} บาท ({i['condition_key']})" for i in top)
    lst_en = ", ".join(f"{i['name']} THB {baht(i['price'])} ({i['condition_key']})" for i in top)
    head_th = {"similar": f"รุ่นใกล้เคียง {ctx.get('product')} ในหมวด {cat}", "recommend": "แนะนำจากผู้ขายเรตติ้ง 4 ขึ้นไป"}.get(kind, "สินค้าที่พบ")
    head_en = {"similar": f"Items similar to {ctx.get('product')}", "recommend": "Recommended (sellers rated 4+)"}.get(kind, "Found")
    return T(f"{head_en}: {lst_en}", f"{head_th}: {lst}", msg), [i["listing_id"] for i in top]


STATIC = {
    "pii": ("Sorry, I can't share personal information such as phone numbers, emails or addresses (privacy policy BR003). Please contact the seller through in-app chat.",
            "ขออภัยค่ะ ระบบไม่สามารถเปิดเผยข้อมูลส่วนบุคคล เช่น เบอร์โทรศัพท์ อีเมล หรือที่อยู่ ได้ตามนโยบายความเป็นส่วนตัว (BR003) กรุณาติดต่อผู้ขายผ่านแชทในระบบ"),
    "policy": ("Under the marketplace policy, buyers and sellers must follow the platform's trading terms. Payment and delivery arrangements are the responsibility of both parties.",
               "ตามนโยบายตลาดกลาง ผู้ซื้อและผู้ขายต้องปฏิบัติตามข้อกำหนดการซื้อขายของแพลตฟอร์ม การชำระเงินและการนัดรับสินค้าเป็นความรับผิดชอบของทั้งสองฝ่าย"),
    "report_seller": ("Please use the 'Report Seller' button on the seller's profile page and attach evidence. Our team will review within 3 business days.",
                      "กรุณากดปุ่ม 'รายงานผู้ขาย' ที่หน้าโปรไฟล์ผู้ขาย แนบหลักฐาน ทีมงานจะตรวจสอบภายใน 3 วันทำการ"),
    "report_product": ("Please use the 'Report Product' button on the product page and attach your reason and evidence for review.",
                       "กรุณากดปุ่ม 'รายงานสินค้า' ที่หน้ารายละเอียดสินค้า แนบเหตุผลและหลักฐานเพื่อให้ทีมงานตรวจสอบ"),
    "complaint": ("We're sorry for the inconvenience. Please submit your complaint via the Report page. Our team will review it within 3 business days (no personal data of the other party will be disclosed).",
                  "ขออภัยในความไม่สะดวกค่ะ กรุณาส่งเรื่องร้องเรียนผ่านหน้ารายงานปัญหา ทีมงานจะตรวจสอบและติดต่อกลับภายใน 3 วันทำการ (ไม่มีการเปิดเผยข้อมูลส่วนบุคคลของคู่กรณี)"),
    "discount": ("Sorry, there is currently no promotion or discount information available for this item.",
                 "ขออภัย ขณะนี้ยังไม่มีข้อมูลโปรโมชันหรือส่วนลดสำหรับสินค้ารายการนี้ในระบบ"),
    "shipping": ("Sorry, shipping/delivery details are not available in the system yet. Please ask the seller via in-app chat.",
                 "ขออภัย ระบบยังไม่มีข้อมูลการจัดส่ง/ค่าส่ง กรุณาสอบถามผู้ขายผ่านแชทในระบบ"),
    "warranty": ("Sorry, warranty information is not available in the system yet. Please ask the seller via in-app chat.",
                 "ขออภัย ระบบยังไม่มีข้อมูลการรับประกันของสินค้านี้ กรุณาสอบถามผู้ขายผ่านแชทในระบบ"),
    "greeting": ("Hello! Welcome to 2HandToYou. How can I help you today?", "สวัสดีค่ะ ยินดีต้อนรับสู่ 2HandToYou มีอะไรให้ช่วยไหมคะ"),
    "farewell": ("Thank you for using our service. Feel free to come back anytime!", "ขอบคุณที่ใช้บริการค่ะ หากมีคำถามเพิ่มเติมสามารถกลับมาถามได้เสมอนะคะ"),
    "offer": ("To make an offer, please open the product's negotiation chat.", "ถ้าต้องการเสนอราคา กรุณาเปิดหน้าแชทเจรจาของสินค้านั้นค่ะ"),
}

SUGGEST = {
    "price": ("How much is {p}?", "ราคา {p} เท่าไหร่"), "condition": ("What condition is {p} in?", "สภาพ {p} เป็นยังไง"),
    "spec": ("Tell me about {p}", "ขอรายละเอียด {p}"), "availability": ("Is {p} still available?", "{p} ยังมีขายไหม"),
    "price_compare": ("Is {p} cheaper than market?", "{p} ถูกกว่าตลาดไหม"), "similar": ("Anything similar to {p}?", "มีรุ่นใกล้เคียง {p} ไหม"),
    "seller_reputation": ("Is the seller reliable?", "ผู้ขายน่าเชื่อถือไหม"), "search": ("Show me phones under 10000", "หามือถืองบไม่เกิน 10000"),
    "recommend": ("Recommend me a laptop", "แนะนำโน้ตบุ๊คหน่อย"), "policy": ("What are the marketplace rules?", "กฎการซื้อขายมีอะไรบ้าง"),
}


def suggestions_for(intents, product, msg):
    p = product or "iPhone 13"
    out = []
    for it in intents:
        if it in SUGGEST:
            out.append(T(SUGGEST[it][0], SUGGEST[it][1], msg).format(p=p))
    for it in ["price", "search", "policy"]:
        if len(out) >= 3:
            break
        s = T(SUGGEST[it][0], SUGGEST[it][1], msg).format(p=p)
        if s not in out:
            out.append(s)
    return out[:3]


# ================================================================ 7. ตรรกะหลักของ /api/chat
def answer(message, sess):
    intent, conf, top = classify(message, allow_offer=False)
    intent, conf, guard = apply_guardrails(message, intent, conf)
    ent = {"product": find_product(message), "seller": (SELLER_RE.search(message) or [None])[0],
           "category": find_category(message), "budget": extract_budget(message)}
    if ent["seller"]:
        ent["seller"] = ent["seller"].upper()
    ctx, used = dict(ent), {}
    out = {"intent": intent, "confidence": conf, "top_intents": top, "entities": ent, "guardrail": guard}

    def fallback(reason, text, sugg):
        out.update(is_fallback=True, fallback_reason=reason, response=text, suggestions=sugg, source={"type": "none"})
        return out

    # --- 1) ความมั่นใจต่ำ -> ไม่เดา บอกตรงๆ และเสนอตัวเลือก
    if conf < FALLBACK_THRESHOLD or intent == "off_topic":
        unk = find_unknown_model(message) if not ent["product"] else None
        if unk and intent != "off_topic":
            sim = similar_names(message)
            return fallback("unknown_product", T(f'Sorry, "{unk}" is not in our system.' + (f" Similar items: {', '.join(sim)}." if sim else ""),
                                                  f'ขออภัย ไม่มี "{unk}" ในระบบตอนนี้' + (f" รุ่นใกล้เคียงที่มี: {', '.join(sim)}" if sim else ""), message),
                            [T(f"How much is {n}?", f"ราคา {n} เท่าไหร่", message) for n in sim[:3]])
        reason = "off_topic" if intent == "off_topic" else "low_confidence"
        return fallback(reason, T("Sorry, I'm not sure what you mean. You could ask about prices, product condition, sellers, or marketplace policies.",
                                  "ขออภัย ยังไม่แน่ใจว่าหมายถึงเรื่องไหน ลองถามเกี่ยวกับราคา สภาพสินค้า ผู้ขาย หรือนโยบายของตลาดได้ค่ะ", message),
                        suggestions_for([t[0] for t in top[:2]], ent["product"] or sess["product"], message))

    # --- 2) ถามถึงรุ่นที่ไม่มีใน KB (เช่น iPhone 16, Pixel 8) -> บอกตรงๆ ไม่เอาข้อมูลรุ่นอื่นมาตอบแทน
    PRODUCTISH = NEEDS_PRODUCT | {"search", "recommend", "market_trend", "shipping", "warranty", "discount"}
    if intent in PRODUCTISH and not ctx["product"]:
        unk = find_unknown_model(message)
        if unk:
            sim = similar_names(message)
            return fallback("unknown_product", T(f'Sorry, "{unk}" is not in our system.' + (f" Similar items: {', '.join(sim)}." if sim else ""),
                                                  f'ขออภัย ไม่มี "{unk}" ในระบบตอนนี้' + (f" รุ่นใกล้เคียงที่มี: {', '.join(sim)}" if sim else ""), message),
                            [T(f"How much is {n}?", f"ราคา {n} เท่าไหร่", message) for n in sim[:3]])

    # คำค้น/คำแนะนำเรื่องที่ไม่ใช่สินค้าในระบบ (เช่น "Which crypto should I buy") -> ไม่ตอบรายการสินค้าแบบเดาๆ
    if intent in {"search", "recommend"} and not (ctx["product"] or ctx["category"] or find_brand(message)):
        noun = unknown_noun(message)
        if noun:
            return fallback("off_topic", T(f'Sorry, we don\'t have "{noun}" in our marketplace. You can ask about phones, laptops, cameras, gaming and more.',
                                           f'ขออภัย ในระบบไม่มีสินค้า/ข้อมูลเกี่ยวกับ "{noun}" ลองถามเรื่องมือถือ โน้ตบุ๊ค กล้อง เกม หรือสินค้าหมวดอื่นได้ค่ะ', message),
                            suggestions_for(["search", "recommend"], None, message))

    # --- 2.5) เติมบริบทจาก session (เฉพาะ session ของผู้ใช้คนนี้)
    if intent in NEEDS_PRODUCT | {"market_trend"} and not ctx["product"] and not ctx["category"]:
        if sess["product"]:
            ctx["product"] = used["product"] = sess["product"]
            if sess["seller"] and not ctx["seller"]:
                ctx["seller"] = used["seller"] = sess["seller"]
    if intent in NEEDS_SELLER and not ctx["seller"]:
        if sess["seller"]:
            ctx["seller"] = used["seller"] = sess["seller"]
        elif ctx["product"] or sess["product"]:
            p = ctx["product"] or sess["product"]
            sellers = sorted({i["seller_id"] for i in BY_NAME[p]})
            if len(sellers) == 1:
                ctx["seller"] = used["seller"] = sellers[0]
                if not ctx["product"]:
                    used["product"] = p
            elif intent != "report_seller":
                return fallback("need_seller", T(f"{p} is sold by {len(sellers)} sellers. Which one do you mean?",
                                                 f"{p} มีผู้ขาย {len(sellers)} ราย หมายถึงผู้ขายคนไหนคะ", message),
                                [T(f"Is seller {s} reliable?", f"ผู้ขาย {s} น่าเชื่อถือไหม", message) for s in sellers[:3]])
    if intent in {"search", "recommend"} and not (ctx["category"] or find_brand(message)) and sess["category"] and not ctx["budget"]:
        ctx["category"] = used["category"] = sess["category"]

    # --- 3) ต้องรู้สินค้าแต่ยังไม่รู้ -> ถามกลับ
    if intent in NEEDS_PRODUCT and intent != "report_product" and not ctx["product"]:
        popular = [n for n, _ in Counter(i["name"] for i in CATALOG).most_common(3)]
        return fallback("need_product", T("Which product do you mean?", "หมายถึงสินค้ารุ่นไหนคะ", message),
                        [T(SUGGEST[intent][0], SUGGEST[intent][1], message).format(p=n) for n in popular])

    # --- 4) สร้างคำตอบจาก KB
    ids, text = [], None
    if intent == "price":
        text, ids = ans_price(ctx, message)
    elif intent == "price_compare":
        text, ids = ans_price_compare(ctx, message)
    elif intent == "market_trend":
        text, ids = ans_market_trend(ctx, message)
        if text is None:
            return fallback("need_category", T("Which product category do you mean?", "หมายถึงสินค้าหมวดไหนคะ", message),
                            [T(f"Price trend for {c}", f"แนวโน้มราคาหมวด {c}", message) for c in ["Mobile Phone", "Laptop", "Camera"]])
    elif intent == "condition":
        text, ids = ans_condition(ctx, message)
    elif intent == "spec":
        text, ids = ans_spec(ctx, message)
    elif intent == "availability":
        text, ids = ans_availability(ctx, message)
    elif intent in ("seller_reputation", "seller_negotiation"):
        if not ctx["seller"]:
            return fallback("need_seller", T("Which seller do you mean? (e.g. S00005)", "หมายถึงผู้ขายคนไหนคะ (เช่น S00005)", message), [])
        text, ids = ans_seller(ctx, message, intent)
    elif intent in ("search", "recommend", "similar"):
        text, ids = ans_search(ctx, message, intent)
    else:
        en, th = STATIC.get(intent, STATIC["policy"])
        text, ids = T(en, th, message), [f"policy:{intent}"]

    q, qid, qsim = nearest_question(message)
    out.update(is_fallback=False, fallback_reason=None, response=text, suggestions=[], context_used=used,
               source={"type": "kb", "kb_version": KB_META["kb_version"], "ids": ([i for i in ids if ":" in i] + [i for i in ids if ":" not in i])[:20]},
               matched_question=q if qsim >= 0.5 else None, matched_dataset_id=qid if qsim >= 0.5 else None)

    # --- 5) อัปเดต session
    if ctx.get("product"):
        sess["product"] = ctx["product"]
        sess["category"] = BY_NAME[ctx["product"]][0]["category"]
        if ent["product"] and not ent["seller"]:
            sess["seller"] = None          # เปลี่ยนรุ่นแล้ว ล้างผู้ขายเดิม
    if ent["seller"]:
        sess["seller"] = ent["seller"]
    elif used.get("seller"):
        sess["seller"] = used["seller"]
    if ctx.get("category"):
        sess["category"] = ctx["category"]
    return out


# ================================================================ 8. Request ID / log / metrics
os.makedirs(LOG_DIR, exist_ok=True)
_logger = logging.getLogger("chat_requests")
_logger.setLevel(logging.INFO)
_logger.propagate = False
if not _logger.handlers:
    _h = TimedRotatingFileHandler(os.path.join(LOG_DIR, "chat_requests.jsonl"), when="midnight",
                                  backupCount=LOG_RETENTION_DAYS, encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_h)

METRICS = {"latency": defaultdict(lambda: deque(maxlen=5000)), "count": Counter(), "fallback": Counter(),
           "intents": Counter(), "started": datetime.datetime.now().isoformat(timespec="seconds")}


def mask_pii(text):
    t = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[EMAIL]", text or "")
    return re.sub(r"(?<!\d)0\d[\d\- ]{7,11}\d(?!\d)", "[PHONE]", t)


@app.before_request
def _start():
    g.t0 = time.perf_counter()
    rid = request.headers.get("X-Request-ID", "")
    g.request_id = rid if re.fullmatch(r"[\w\-]{8,64}", rid) else uuid.uuid4().hex[:16]
    g.log = {}


@app.after_request
def _finish(resp):
    ms = round((time.perf_counter() - g.t0) * 1000, 2)
    resp.headers["X-Request-ID"] = g.request_id
    resp.headers["X-Response-Time-ms"] = str(ms)
    if request.path.startswith("/api/") and request.path not in ("/api/metrics",) and not request.path.startswith("/api/logs"):
        ep = request.path
        METRICS["latency"][ep].append(ms)
        METRICS["count"][ep] += 1
        if g.log.get("is_fallback"):
            METRICS["fallback"][ep] += 1
        if g.log.get("intent"):
            METRICS["intents"][g.log["intent"]] += 1
        rec = {"ts": datetime.datetime.now().isoformat(timespec="milliseconds"), "request_id": g.request_id,
               "endpoint": ep, "status": resp.status_code, "latency_ms": ms, **g.log}
        _logger.info(json.dumps(rec, ensure_ascii=False))
    return resp


# ================================================================ 9. API
@app.route("/api/chat", methods=["POST"])
@swag_from({"tags": ["Chat"], "summary": "ถามแชทบอท (รองรับ session_id สำหรับคำถามต่อเนื่อง)",
    "parameters": [{"name": "body", "in": "body", "required": True, "schema": {"type": "object", "properties": {
        "message": {"type": "string", "example": "iPhone 13 ราคาเท่าไหร่"},
        "session_id": {"type": "string", "example": "user-123", "description": "ไม่ส่ง = สร้างใหม่ให้ (ส่งค่าที่ได้กลับมาในคำถามถัดไป)"}},
        "required": ["message"]}}],
    "responses": {200: {"description": "คำตอบ + request_id + intent + confidence + source + context_used"},
                  400: {"description": "ไม่มี message"}}})
def chat():
    data = request.get_json(force=True, silent=True) or {}
    message = (data.get("message") or "").strip()[:1000]
    sid = str(data.get("session_id") or request.headers.get("X-Session-ID") or "")[:64] or "s-" + uuid.uuid4().hex[:12]
    if not message:
        return jsonify({"error": "กรุณาระบุข้อความคำถาม (message)", "request_id": g.request_id}), 400
    sess = SESSIONS.get(sid)
    r = answer(message, sess)
    sess["intent"] = r["intent"]
    sess["turns"].append({"q": mask_pii(message), "intent": r["intent"], "request_id": g.request_id})
    body = {
        "request_id": g.request_id, "session_id": sid, "response": r["response"],
        "intent": r["intent"], "intent_category": "Fallback" if r["is_fallback"] else INTENT_CATEGORY.get(r["intent"], "Other"),
        "confidence": round(r["confidence"], 3),
        "confidence_level": "high" if r["confidence"] >= HIGH_CONFIDENCE else "medium" if r["confidence"] >= FALLBACK_THRESHOLD else "low",
        "is_fallback": r["is_fallback"], "fallback_reason": r.get("fallback_reason"),
        "suggestions": r.get("suggestions", []), "entities": r["entities"], "context_used": r.get("context_used", {}),
        "source": r["source"], "matched_question": r.get("matched_question"), "guardrail": r.get("guardrail"),
        "latency_ms": round((time.perf_counter() - g.t0) * 1000, 2),
    }
    g.log = {"session_id": sid, "message": mask_pii(message), "intent": r["intent"], "confidence": body["confidence"],
             "top_intents": [[a, round(b, 3)] for a, b in r["top_intents"]], "is_fallback": r["is_fallback"],
             "fallback_reason": r.get("fallback_reason"), "entities": r["entities"], "context_used": body["context_used"],
             "source": r["source"], "guardrail": r.get("guardrail"), "response": body["response"][:300]}
    return jsonify(body)


NEGOTIATION_ACTION = {"offer": "offer", "price": "market", "price_compare": "market", "market_trend": "market",
                      "condition": "spec", "spec": "spec", "availability": "spec",
                      "seller_reputation": "trust", "seller_negotiation": "trust", "pii": "pii",
                      "greeting": "greeting", "farewell": "farewell"}


@app.route("/api/negotiate/intent", methods=["POST"])
@swag_from({"tags": ["Negotiation"], "summary": "จำแนก intent ของข้อความในแชทเจรจา (ใช้ตัวจำแนกเดียวกับแชทบอท)",
    "parameters": [{"name": "body", "in": "body", "required": True, "schema": {"type": "object", "properties": {
        "message": {"type": "string", "example": "ขอ 15000 ได้ไหม"},
        "current_product": {"type": "string", "example": "Sony PlayStation 5"},
        "session_id": {"type": "string"}}, "required": ["message"]}}],
    "responses": {200: {"description": "action (offer/spec/trust/market/pii/other_product/unknown_product/other) + price + confidence"}}})
def negotiate_intent():
    data = request.get_json(force=True, silent=True) or {}
    message = (data.get("message") or "").strip()[:1000]
    current = data.get("current_product") or ""
    intent, conf, top = classify(message)
    intent, conf, guard = apply_guardrails(message, intent, conf)
    prod = find_product(message)
    action, price, unk, similar = NEGOTIATION_ACTION.get(intent, "other"), None, None, []
    if prod and prod != current:
        action = "other_product"
    elif not prod:
        unk = find_unknown_model(message)
        if unk:
            action, similar = "unknown_product", similar_names(message)
    if action == "offer" or (action in ("market", "other") and extract_amount(message) and re.search(r"ขอ|ลด|เหลือ|ให้|offer|do|รับ|ปิด", message.lower())):
        price = extract_amount(message)
        action = "offer" if price else action
    if conf < FALLBACK_THRESHOLD and action not in ("other_product", "unknown_product", "offer"):
        action = "other"
    g.log = {"session_id": data.get("session_id"), "message": mask_pii(message), "intent": intent, "confidence": round(conf, 3),
             "action": action, "price": price, "product_mention": prod, "is_fallback": action == "other", "guardrail": guard}
    return jsonify({"request_id": g.request_id, "action": action, "intent": intent, "confidence": round(conf, 3),
                    "price": price, "product_mention": prod, "unknown_mention": unk, "similar": similar, "guardrail": guard,
                    "top_intents": [[a, round(b, 3)] for a, b in top]})


@app.route("/api/metrics", methods=["GET"])
@swag_from({"tags": ["Ops"], "summary": "Latency P50/P95/P99, จำนวน request, อัตรา fallback, สัดส่วน intent",
            "responses": {200: {"description": "metrics"}}})
def metrics():
    eps = {}
    for ep, lat in METRICS["latency"].items():
        a = np.array(lat)
        eps[ep] = {"requests": METRICS["count"][ep], "fallback_rate": round(METRICS["fallback"][ep] / max(METRICS["count"][ep], 1), 3),
                   "latency_ms": {"p50": round(float(np.percentile(a, 50)), 2), "p95": round(float(np.percentile(a, 95)), 2),
                                  "p99": round(float(np.percentile(a, 99)), 2), "max": round(float(a.max()), 2)}}
    return jsonify({"since": METRICS["started"], "active_sessions": SESSIONS.count(), "endpoints": eps,
                    "intents": dict(METRICS["intents"].most_common())})


@app.route("/api/logs/<request_id>", methods=["GET"])
@swag_from({"tags": ["Ops"], "summary": "ดู log ของ request_id (ต้องส่ง header X-Admin-Token ให้ตรงกับ env LOG_ACCESS_TOKEN)",
            "parameters": [{"name": "request_id", "in": "path", "type": "string", "required": True},
                           {"name": "X-Admin-Token", "in": "header", "type": "string", "required": True}],
            "responses": {200: {"description": "log record"}, 403: {"description": "ไม่มีสิทธิ์"}, 404: {"description": "ไม่พบ"}}})
def get_log(request_id):
    if not LOG_ACCESS_TOKEN or request.headers.get("X-Admin-Token") != LOG_ACCESS_TOKEN:
        return jsonify({"error": "forbidden"}), 403
    files = sorted([f for f in os.listdir(LOG_DIR) if f.startswith("chat_requests.jsonl")], reverse=True)
    for fn in files:
        with open(os.path.join(LOG_DIR, fn), encoding="utf-8") as f:
            for line in f:
                if f'"request_id": "{request_id}"' in line:
                    return jsonify(json.loads(line))
    return jsonify({"error": "not found"}), 404


@app.route("/api/kb/info", methods=["GET"])
@swag_from({"tags": ["Ops"], "summary": "เวอร์ชันและแหล่งที่มาของ Knowledge Base", "responses": {200: {"description": "kb meta"}}})
def kb_info():
    return jsonify({**KB_META, "intent_classifier": {"training_examples": N_TRAIN, "intents": list(CLASSIFIER.classes_)},
                    "thresholds": {"fallback": FALLBACK_THRESHOLD, "high_confidence": HIGH_CONFIDENCE},
                    "session_ttl_sec": SESSION_TTL_SEC, "log_retention_days": LOG_RETENTION_DAYS})


@app.route("/api/chat/stats", methods=["GET"])
def chat_stats():
    return jsonify({"total_questions": len(DATASET), "listings": len(CATALOG), "products": len(PRODUCT_NAMES),
                    "intent_categories": dict(Counter(d["Intent_Category"] for d in DATASET))})


@app.route("/api/chat/sample-questions", methods=["GET"])
def sample_questions():
    import random
    n = max(1, min(request.args.get("n", default=4, type=int), 20))
    pool = [d for d in DATASET if d["Intent_Category"] != "Fallback"]
    cats = list({d["Intent_Category"] for d in pool})
    random.shuffle(cats)
    picked = [random.choice([d for d in pool if d["Intent_Category"] == c]) for c in cats[:n]]
    return jsonify({"questions": [{"question": d["Question"], "intent_category": d["Intent_Category"]} for d in picked]})


@app.route("/")
def home():
    return "Chatbot Backend Server v2 is running!"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=os.environ.get("FLASK_DEBUG", "1") == "1")
