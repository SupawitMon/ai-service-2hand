"""
train_grade_v4.py
เทรนโมเดลทายเกรด A/B/C ใหม่ ด้วย dataset v4 (2,087 รูป — มากกว่า v3 ราว 2 เท่า)
ได้ไฟล์ best.pt ตัวใหม่ เอาไปแทน best.pt เดิมใน backend

วิธีใช้:
  1) แตก zip dataset v4 ไว้ในโฟลเดอร์เดียวกับไฟล์นี้ ให้ได้โฟลเดอร์
     Used_Electronics_Defects_v4  (ข้างในมี train/ valid/ data.yaml)
  2) python train_grade_v4.py
  3) จบแล้วสคริปต์จะก็อป best.pt ตัวใหม่มาไว้ที่ best_v4.pt ให้ ตรวจผลแล้วค่อยเปลี่ยนชื่อทับ best.pt

ขั้นตอนข้างใน: แปลง dataset ตำหนิ (กรอบตำแหน่ง) -> โฟลเดอร์เกรด A/B/C แล้วเทรน classification
กฎเกรด: ไม่มีตำหนิ = A, มีแค่ dent/discoloration/scratch = B, มี broken/crack = C
"""

import os
import shutil
import argparse
from pathlib import Path
from collections import Counter

HERE = Path(__file__).resolve().parent

DEFECT_NAMES = ["broken", "crack", "dent", "discoloration", "scratch"]
STRUCTURAL = {"broken", "crack"}          # ตำหนิรุนแรง -> C
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# dataset v4 มีเกรด A น้อยมาก (164 จาก 2,087 รูป ≈ 8%) โมเดลจะชอบทายแค่ B/C
# จึงทำสำเนารูปเกรด A ในชุด train เพิ่ม (เฉพาะ train — val/test ใช้ของจริงไม่ปลอม)
OVERSAMPLE_A = 4


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--data", default=str(HERE / "Used_Electronics_Defects_v4"),
                   help="โฟลเดอร์ dataset v4 ที่แตก zip แล้ว")
    p.add_argument("--out", default=str(HERE / "grade_dataset_v4"),
                   help="โฟลเดอร์เกรด A/B/C ที่จะสร้าง")
    p.add_argument("--base", default=str(HERE / "yolov8n-cls.pt"), help="โมเดลตั้งต้น")
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--imgsz", type=int, default=224)
    p.add_argument("--batch", type=int, default=32)
    p.add_argument("--convert-only", action="store_true", help="แปลงข้อมูลอย่างเดียว ไม่เทรน")
    return p.parse_args()


def classify_image(label_path: Path) -> str:
    if not label_path.exists():
        return "A"
    lines = [l for l in label_path.read_text().splitlines() if l.strip()]
    if not lines:
        return "A"
    classes = {DEFECT_NAMES[int(l.split()[0])] for l in lines}
    return "C" if classes & STRUCTURAL else "B"


def step1_convert(data_dir: Path, out_dir: Path):
    from sklearn.model_selection import train_test_split

    if out_dir.exists():
        print(f"พบ {out_dir} อยู่แล้ว — ข้ามการแปลง (ลบโฟลเดอร์นี้ถ้าต้องการแปลงใหม่)")
        return

    items = []
    for split in ["train", "valid", "test"]:          # v4 ไม่มี test แต่รองรับไว้เผื่อเวอร์ชันหน้า
        img_dir, lbl_dir = data_dir / split / "images", data_dir / split / "labels"
        if not img_dir.exists():
            continue
        for img in img_dir.iterdir():
            if img.suffix.lower() in IMG_EXT:
                items.append((img, classify_image(lbl_dir / (img.stem + ".txt"))))
    if not items:
        raise FileNotFoundError(f"ไม่พบรูปใน {data_dir} — เช็คว่าแตก zip ถูกที่ (ต้องมี train/images)")

    print(f"พบรูปทั้งหมด {len(items)} รูป | ต่อเกรด: {dict(Counter(g for _, g in items))}")

    grades = [g for _, g in items]
    train_items, temp = train_test_split(items, test_size=0.25, stratify=grades, random_state=42)
    val_items, test_items = train_test_split(temp, test_size=0.4, stratify=[g for _, g in temp], random_state=42)

    for name, split_items in {"train": train_items, "val": val_items, "test": test_items}.items():
        for g in "ABC":
            (out_dir / name / g).mkdir(parents=True, exist_ok=True)
        for img, g in split_items:
            shutil.copyfile(img, out_dir / name / g / img.name)
            if name == "train" and g == "A":
                for k in range(1, OVERSAMPLE_A):
                    shutil.copyfile(img, out_dir / name / g / f"{img.stem}_dup{k}{img.suffix}")
        counts = {g: len(list((out_dir / name / g).iterdir())) for g in "ABC"}
        print(f"  {name}: {counts}")
    print(f"แปลงเสร็จ: {out_dir}\n")


def step2_train(args):
    import torch
    from ultralytics import YOLO

    device = 0 if torch.cuda.is_available() else "cpu"
    print("ใช้ GPU:" if device == 0 else "ไม่พบ GPU — ใช้ CPU (ช้ามาก)",
          torch.cuda.get_device_name(0) if device == 0 else "")

    base = args.base if os.path.exists(args.base) else "yolov8n-cls.pt"
    model = YOLO(base)
    return model.train(
        data=args.out, epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
        device=device, name="grade_v4", patience=25, exist_ok=True,
        hsv_h=0.015, hsv_s=0.4, hsv_v=0.4, degrees=15, translate=0.1, scale=0.3,
        fliplr=0.5, erasing=0.2, auto_augment="randaugment",
    )


def step3_evaluate(results, args):
    from ultralytics import YOLO

    best = Path(results.save_dir) / "weights" / "best.pt"
    model = YOLO(str(best))

    # วัดบนชุด test ที่โมเดลไม่เคยเห็นเลย + ดูความแม่นแยกรายเกรด (สำคัญกว่าค่ารวม เพราะเกรดไม่สมดุล)
    test_dir = Path(args.out) / "test"
    names = model.names
    correct, total = Counter(), Counter()
    for g in "ABC":
        for img in (test_dir / g).iterdir():
            pred = names[model.predict(str(img), verbose=False)[0].probs.top1]
            total[g] += 1
            correct[g] += int(pred == g)

    print("\n=== ผลบนชุด test ===")
    for g in "ABC":
        acc = correct[g] / total[g] if total[g] else 0
        print(f"  เกรด {g}: ถูก {correct[g]}/{total[g]} ({acc:.0%})")
    overall = sum(correct.values()) / max(sum(total.values()), 1)
    print(f"  รวม: {overall:.1%}   (best.pt ตัวเดิมจาก 122 รูป ≈ 66.7%)")

    out = HERE / "best_v4.pt"
    shutil.copyfile(best, out)
    print(f"\nก็อปโมเดลใหม่ไว้ที่: {out}")
    print("ถ้าผลดีกว่าเดิม: เปลี่ยนชื่อ best.pt เดิมเป็น best_old.pt แล้วเปลี่ยน best_v4.pt เป็น best.pt")


def main():
    args = parse_args()
    print("=== 1) แปลง dataset ตำหนิ -> เกรด A/B/C ===")
    step1_convert(Path(args.data), Path(args.out))
    if args.convert_only:
        return
    print("=== 2) เทรน ===")
    results = step2_train(args)
    print("=== 3) ประเมินผล ===")
    step3_evaluate(results, args)


if __name__ == "__main__":
    main()
