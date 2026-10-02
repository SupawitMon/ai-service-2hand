"""
eval_chatbot.py — วัดผลแชทบอทตามเกณฑ์รับงานของ SE (AI Integration Meeting 30 Sep 2026)

  python eval_chatbot.py                       # รันในเครื่อง (ไม่ต้องเปิด server)
  python eval_chatbot.py --url http://<IP>:8012  # วัดกับ server จริง (รวมเวลา network)

ผลลัพธ์: reports/eval_report.md (สรุป) + reports/eval_results.csv (รายข้อ)
"""
import os, re, json, csv, time, argparse, uuid, statistics
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
INTENT_TARGET = 0.80


class LocalClient:
    def __init__(self):
        import importlib.util
        os.environ.setdefault("CHAT_LOG_DIR", os.path.join(HERE, "reports", "eval_logs"))
        spec = importlib.util.spec_from_file_location("cs", os.path.join(HERE, "chatbot_server.py"))
        self.cs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cs)
        self.c = self.cs.app.test_client()

    def post(self, path, body):
        rid = "eval-" + uuid.uuid4().hex[:12]
        t = time.perf_counter()
        r = self.c.post(path, json=body, headers={"X-Request-ID": rid})
        return r.get_json(), r.headers.get("X-Request-ID"), rid, (time.perf_counter() - t) * 1000


class HttpClient:
    def __init__(self, url):
        import requests
        self.s, self.url, self.cs = requests.Session(), url.rstrip("/"), None

    def post(self, path, body):
        rid = "eval-" + uuid.uuid4().hex[:12]
        t = time.perf_counter()
        r = self.s.post(self.url + path, json=body, headers={"X-Request-ID": rid}, timeout=30)
        return r.json(), r.headers.get("X-Request-ID"), rid, (time.perf_counter() - t) * 1000


PRICE_TABLE = json.load(open(os.path.join(HERE, "kb", "price_table.json"), encoding="utf-8"))["base_price_good"]


def numbers_in(text):
    return {int(x.replace(",", "")) for x in re.findall(r"\d[\d,]{2,}", text)}


def allowed_numbers(source, catalog, sellers):
    ok = set()
    by_id = {c["listing_id"]: c for c in catalog}
    for sid in source.get("ids", []):
        if sid in by_id:
            ok |= {by_id[sid]["price"], by_id[sid]["market_price"]}
        elif sid.startswith("price_table:"):
            ok.add(PRICE_TABLE.get(sid.split(":", 1)[1]))
        elif sid.startswith("seller:"):
            s = sellers[sid.split(":")[1]]
            ok |= {s["total_sales"], s["rating"], s["response_rate"], s["negotiation_rate"]}
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None)
    ap.add_argument("--cases", default="tests/test_cases.json")
    ap.add_argument("--out", default="eval")
    args = ap.parse_args()
    client = HttpClient(args.url) if args.url else LocalClient()
    T = json.load(open(os.path.join(HERE, args.cases), encoding="utf-8"))
    catalog = json.load(open(os.path.join(HERE, "kb", "product_catalog.json"), encoding="utf-8"))
    sellers = json.load(open(os.path.join(HERE, "kb", "sellers.json"), encoding="utf-8"))
    rows, lat, trace_ok, trace_total, grounding = [], [], 0, 0, []

    def call(path, body):
        nonlocal trace_ok, trace_total
        r, hdr_rid, sent_rid, ms = client.post(path, body)
        lat.append(ms)
        trace_total += 1
        trace_ok += int(hdr_rid == sent_rid == r.get("request_id"))
        return r

    def check_grounding(case_id, r):
        if r.get("is_fallback") or r.get("source", {}).get("type") != "kb":
            return
        if r["intent"] not in {"price", "price_compare", "search", "recommend", "similar", "seller_reputation", "seller_negotiation"}:
            return
        text = r["response"]
        for name in sorted({c["name"] for c in catalog}, key=len, reverse=True):
            text = text.replace(name, " ")          # ตัวเลขในชื่อรุ่น (เช่น 256GB) ไม่ใช่ข้อมูลราคา
        nums = {n for n in numbers_in(text) if n >= 100}
        allowed = allowed_numbers(r["source"], catalog, sellers)
        bad = sorted(n for n in nums if n not in allowed)
        grounding.append({"id": case_id, "intent": r["intent"], "numbers": len(nums), "ungrounded": bad})

    # ---------- 1) Intent accuracy ----------
    per = {}
    for c in T["intent_cases"]:
        r = call("/api/chat", {"message": c["message"], "session_id": "eval-" + c["id"]})
        pred = r["intent"]
        if c["expected"] == "off_topic":   # คำถามนอกเรื่อง: พฤติกรรมที่ถูกคือ "ไม่ตอบ แล้วบอกข้อจำกัด" (เกณฑ์เดียวกับ fallback_cases)
            ok = r["is_fallback"] and r.get("fallback_reason") in ("off_topic", "low_confidence")
        else:
            ok = pred == c["expected"] and (not r["is_fallback"] or r.get("fallback_reason") in ("need_seller", "need_product"))
        per.setdefault(c["expected"], [0, 0]); per[c["expected"]][0] += ok; per[c["expected"]][1] += 1
        rows.append(["intent", c["id"], c["message"], c["expected"], pred, f"{r['confidence']:.2f}", r["is_fallback"],
                     "PASS" if ok else "FAIL", r["request_id"], r["response"][:160]])
        check_grounding(c["id"], r)
    n_ok = sum(v[0] for v in per.values()); n_all = sum(v[1] for v in per.values())
    wrong_answer = sum(1 for r in rows if r[0] == "intent" and r[7] == "FAIL" and str(r[6]) == "False")
    safe_fb = sum(1 for r in rows if r[0] == "intent" and r[7] == "FAIL" and str(r[6]) == "True")

    # ---------- 2) Context ----------
    ctx_pass = ctx_total = 0
    transcript = []
    for c in T["context_cases"]:
        sid = "eval-" + c["id"]
        transcript.append(f"**{c['id']}** — {c['note']} (session `{sid}`)\n")
        for t in c["turns"]:
            r = call("/api/chat", {"message": t["message"], "session_id": sid})
            ok = r["intent"] == t["expect_intent"] and not r["is_fallback"]
            if "expect_product" in t:
                ok &= r["entities"]["product"] == t["expect_product"]
            if "expect_context_product" in t:
                ok &= r["context_used"].get("product") == t["expect_context_product"]
            if "expect_context_seller" in t:
                ok &= r["context_used"].get("seller") == t["expect_context_seller"]
            ctx_pass += ok; ctx_total += 1
            transcript.append(f"- 🧑 {t['message']}\n- 🤖 {r['response']}  \n  `intent={r['intent']} conf={r['confidence']} context_used={r['context_used']} request_id={r['request_id']}` {'✅' if ok else '❌'}\n")
            rows.append(["context", c["id"], t["message"], t["expect_intent"], r["intent"], f"{r['confidence']:.2f}",
                         r["is_fallback"], "PASS" if ok else "FAIL", r["request_id"], r["response"][:160]])
            check_grounding(c["id"], r)
        transcript.append("")

    # ---------- 3) Session isolation ----------
    iso = T["isolation_case"]
    sa, sb = "eval-iso-A", "eval-iso-B"
    call("/api/chat", {"message": iso["a"], "session_id": sa})
    rb = call("/api/chat", {"message": iso["b"], "session_id": sb})
    iso_ok = not rb["context_used"].get("product") and rb.get("fallback_reason") == "need_product"
    rows.append(["isolation", "ISO", iso["b"], "need_product (ไม่ได้บริบทของ A)", rb.get("fallback_reason"), "", rb["is_fallback"],
                 "PASS" if iso_ok else "FAIL", rb["request_id"], rb["response"][:160]])

    # ---------- 4) Fallback ----------
    fb_pass, fb_examples = 0, []
    for c in T["fallback_cases"]:
        r = call("/api/chat", {"message": c["message"], "session_id": "eval-" + c["id"]})
        ok = r["is_fallback"] and r.get("fallback_reason") in c["expect_reason"]
        fb_pass += ok
        fb_examples.append(f"| {c['message']} | {r.get('fallback_reason')} | {r['response'][:110]} | {', '.join(r.get('suggestions', [])[:3])} | {'✅' if ok else '❌'} |")
        rows.append(["fallback", c["id"], c["message"], "/".join(c["expect_reason"]), r.get("fallback_reason"), f"{r['confidence']:.2f}",
                     r["is_fallback"], "PASS" if ok else "FAIL", r["request_id"], r["response"][:160]])

    # ---------- 5) Negotiation intent ----------
    ng_pass = 0
    for c in T["negotiation_cases"]:
        r = call("/api/negotiate/intent", {"message": c["message"], "current_product": c["current"], "session_id": "eval-nego"})
        ok = r["action"] == c["expected"] and ("price" not in c or r["price"] == c["price"])
        ng_pass += ok
        rows.append(["negotiation", c["id"], c["message"], c["expected"] + (f" {c['price']}" if "price" in c else ""),
                     f"{r['action']} {r['price'] or ''}".strip(), f"{r['confidence']:.2f}", "", "PASS" if ok else "FAIL", r["request_id"], ""])

    # ---------- 6) log มีครบทุก request ไหม (เฉพาะโหมด local) ----------
    log_note = "วัดได้เฉพาะโหมด local"
    if client.cs:
        logfile = os.path.join(os.environ["CHAT_LOG_DIR"], "chat_requests.jsonl")
        logged = {json.loads(l)["request_id"] for l in open(logfile, encoding="utf-8")}
        missing = [r[8] for r in rows if r[8] and r[8] not in logged]
        log_note = f"{len(rows) - len(missing)}/{len(rows)} request พบใน log"

    a = np.array(lat)
    p50, p95, p99 = (float(np.percentile(a, q)) for q in (50, 95, 99))
    g_bad = [x for x in grounding if x["ungrounded"]]
    acc = n_ok / n_all

    os.makedirs(os.path.join(HERE, "reports"), exist_ok=True)
    with open(os.path.join(HERE, "reports", f"{args.out}_results.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["test", "id", "message", "expected", "actual", "confidence", "is_fallback", "result", "request_id", "response"])
        w.writerows(rows)

    def mark(b):
        return "✅ ผ่าน" if b else "❌ ไม่ผ่าน"

    per_lines = "\n".join(f"| {k} | {v[0]}/{v[1]} | {v[0]/v[1]:.0%} |" for k, v in sorted(per.items(), key=lambda kv: kv[1][0]/kv[1][1]))
    fails = "\n".join(f"| {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} |" for r in rows if r[0] == "intent" and r[7] == "FAIL") or "| - | ไม่มี | | | |"
    mode = f"HTTP {args.url} (รวม network)" if args.url else "local in-process (ไม่รวม network)"
    report = f"""# ผลวัดแชทบอทตามเกณฑ์รับงาน — 2HandToYou

วันที่: {time.strftime('%Y-%m-%d %H:%M')} · โหมด: {mode} · ชุดทดสอบ: `{args.cases}` (แยกจากข้อมูลเทรน)

## สรุปตามเกณฑ์ของ SE

| ด้าน | วิธีวัด | ผล | เกณฑ์ | สถานะ |
|---|---|---|---|---|
| Intent accuracy | {n_all} คำถาม ใช้คำต่างจากข้อมูลเทรน (ไทย/อังกฤษ/พิมพ์ผิด) | **{acc:.1%}** ({n_ok}/{n_all}) | ≥ 80% | {mark(acc >= INTENT_TARGET)} |
| Grounded answer | ตัวเลขทุกตัวในคำตอบ (ราคา/สถิติผู้ขาย) ต้องมีอยู่ใน KB รายการที่อ้างใน `source.ids` | {len(grounding) - len(g_bad)}/{len(grounding)} คำตอบไม่มีตัวเลขนอกแหล่งอ้างอิง | ไม่สร้างข้อมูลที่ไม่มีในแหล่งอ้างอิง | {mark(not g_bad)} |
| Context handling | {ctx_total} turn ใน {len(T['context_cases'])} บทสนทนาต่อเนื่อง + ทดสอบแยก session | {ctx_pass}/{ctx_total} turn · แยก session: {'ไม่ปน' if iso_ok else 'ปน'} | ใช้บริบทได้ ไม่ปนผู้ใช้อื่น | {mark(ctx_pass == ctx_total and iso_ok)} |
| Safe fallback | {len(T['fallback_cases'])} คำถามกำกวม/ไม่มีข้อมูล/นอกเรื่อง | {fb_pass}/{len(T['fallback_cases'])} | แจ้งข้อจำกัด + ถามกลับ/เสนอทางเลือก | {mark(fb_pass == len(T['fallback_cases']))} |
| Latency | ทุก request ในการทดสอบ ({len(lat)} ครั้ง) | P50 {p50:.1f} ms · **P95 {p95:.1f} ms** · P99 {p99:.1f} ms | ทีม AI เสนอ: P95 ≤ 500 ms | {mark(p95 <= 500)} |
| Traceability | request_id ที่ส่งไป = header ที่ได้กลับ = body | {trace_ok}/{trace_total} · log: {log_note} | ทุกคำขอมี Request ID | {mark(trace_ok == trace_total)} |
| Negotiation intent | {len(T['negotiation_cases'])} ข้อความในแชทเจรจา (รวมจับราคาที่เสนอ) | {ng_pass}/{len(T['negotiation_cases'])} ({ng_pass/len(T['negotiation_cases']):.0%}) | ≥ 80% | {mark(ng_pass/len(T['negotiation_cases']) >= INTENT_TARGET)} |

## Intent accuracy แยกรายหมวด

| intent | ถูก | % |
|---|---|---|
{per_lines}

### ข้อที่ตอบผิด intent

จาก {n_all - n_ok} ข้อที่ผิด: **{safe_fb} ข้อระบบไม่แน่ใจแล้วถามกลับ** (ไม่ได้ให้ข้อมูลผิด) และ **{wrong_answer} ข้อตอบผิดเรื่อง** (ข้อมูลที่ตอบยังมาจาก KB แต่ไม่ตรงคำถาม)

| id | ข้อความ | คาดหวัง | ได้ | ความมั่นใจ |
|---|---|---|---|---|
{fails}

## ตัวอย่าง Fallback

| คำถาม | เหตุผล | คำตอบ | ตัวเลือกที่เสนอ | ผล |
|---|---|---|---|---|
{chr(10).join(fb_examples)}

## Conversation transcript (Context handling)

{chr(10).join(transcript)}
**แยก session:** ผู้ใช้ A ถาม "{iso['a']}" แล้วผู้ใช้ B ถาม "{iso['b']}" → B ได้ `{rb.get('fallback_reason')}` ("{rb['response']}") {'✅ ไม่ได้บริบทของ A' if iso_ok else '❌ ได้บริบทของ A'}

รายละเอียดทุกข้อ: `reports/{args.out}_results.csv`
"""
    with open(os.path.join(HERE, "reports", f"{args.out}_report.md"), "w", encoding="utf-8") as f:
        f.write(report)
    print(report[:report.index("## ตัวอย่าง Fallback")])


if __name__ == "__main__":
    main()
