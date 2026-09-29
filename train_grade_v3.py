"""
train_grade_v3.py
เทรนโมเดลทายเกรด A/B/C ใหม่ ด้วย dataset v3 ที่ QA หามา (1,005 รูป)
แทนที่ best.pt ตัวเดิม (ที่เทรนจากแค่ 122 รูป)

ขั้นตอน: แปลง dataset ตำหนิ -> เกรด A/B/C ก่อน แล้วค่อยเทรน classification
"""

import os
import shutil
import argparse
from pathlib import Path
from collections import Counter

import torch
from ultralytics import YOLO
from sklearn.model_selection import train_test_split

# ============================================================
# 1. แก้ path ตรงนี้ให้ตรงกับเครื่องคุณ
# ============================================================
DEFECT_DATA_DIR = r"C:\Users\PREDATOR ACER\Downloads\Used Electronics Defects.v3-object_damage_detect-v0.2.yolo26"
GRADE_DATA_DIR = r"C:\Users\PREDATOR ACER\Downloads\backend 2hand\grade_dataset_v3"  # จะถูกสร้างอัตโนมัติ
BASE_MODEL = r"C:\Users\PREDATOR ACER\Downloads\backend 2hand\yolov8n-cls.pt"        # ถ้าไม่มีไฟล์นี้ ใส่ "yolov8n-cls.pt" เฉยๆ

EPOCHS = 100
IMG_SIZE = 224
BATCH = 16

DEFECT_NAMES = ["broken", "crack", "dent", "discoloration", "scratch"]
STRUCTURAL = {"broken", "crack"}                    # ตำหนิรุนแรง -> เกรด C
COSMETIC = {"dent", "discoloration", "scratch"}      # ตำหนิผิวเผิน -> เกรด B


def classify_image(label_path: Path) -> str:
    """ดูไฟล์ label แล้วตัดสินเกรดตามกฎ: ไม่มีตำหนิ=A, ผิวเผิน=B, โครงสร้าง=C"""
    if not label_path.exists():
        return "A"
    lines = [l for l in label_path.read_text().splitlines() if l.strip()]
    if not lines:
        return "A"
    classes = {DEFECT_NAMES[int(l.split()[0])] for l in lines}
    if classes & STRUCTURAL:
        return "C"
    return "B"


def step1_convert_to_grades():
    """ขั้นตอนที่ 1: แปลง dataset ตำหนิ (ตำแหน่ง) ให้เป็นโฟลเดอร์เกรด A/B/C"""
    defect_data = Path(DEFECT_DATA_DIR)
    out_dir = Path(GRADE_DATA_DIR)

    if out_dir.exists():
        print(f"พบโฟลเดอร์ {out_dir} อยู่แล้ว — ข้ามขั้นตอนแปลงข้อมูล (ลบโฟลเดอร์นี้ทิ้งก่อนถ้าต้องการแปลงใหม่)")
        return

    items = []
    for split in ["train", "valid"]:
        img_dir = defect_data / split / "images"
        lbl_dir = defect_data / split / "labels"
        if not img_dir.exists():
            raise FileNotFoundError(f"ไม่พบ {img_dir} — เช็ค DEFECT_DATA_DIR ให้ถูกต้อง")
        for img_path in img_dir.iterdir():
            if img_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".avif"}:
                continue
            lbl_path = lbl_dir / (img_path.stem + ".txt")
            grade = classify_image(lbl_path)
            items.append((img_path, grade))

    print(f"พบรูปทั้งหมด: {len(items)} รูป")
    grade_counts = Counter(g for _, g in items)
    print("จำนวนต่อเกรด:", dict(grade_counts))

    grades = [g for _, g in items]
    train_items, temp_items = train_test_split(items, test_size=0.25, stratify=grades, random_state=42)
    temp_grades = [g for _, g in temp_items]
    val_items, test_items = train_test_split(temp_items, test_size=0.4, stratify=temp_grades, random_state=42)

    splits = {"train": train_items, "val": val_items, "test": test_items}
    for split_name, split_items in splits.items():
        for grade in ["A", "B", "C"]:
            (out_dir / split_name / grade).mkdir(parents=True, exist_ok=True)
        for img_path, grade in split_items:
            dst = out_dir / split_name / grade / img_path.name
            shutil.copyfile(img_path, dst)
        print(f"{split_name}: {len(split_items)} รูป -> {out_dir / split_name}")

    print(f"\nแปลงข้อมูลเสร็จแล้ว! อยู่ที่: {out_dir.resolve()}")
    print("แนะนำ: เปิดดูรูปในแต่ละโฟลเดอร์เกรดสักครู่ ถ้าเห็นรูปไหนเกรดผิดปกติ ลากย้ายโฟลเดอร์ได้เลยก่อนเทรน\n")


def step2_train():
    """ขั้นตอนที่ 2: เทรนโมเดล classification"""
    if torch.cuda.is_available():
        device = 0
        print(f"พบ GPU: {torch.cuda.get_device_name(0)} — ใช้ GPU เทรน")
    else:
        device = "cpu"
        print("ไม่พบ GPU — จะเทรนด้วย CPU (ช้ากว่ามาก)")

    model_path = BASE_MODEL if os.path.exists(BASE_MODEL) else "yolov8n-cls.pt"
    print(f"ใช้โมเดลตั้งต้น: {model_path}")

    model = YOLO(model_path)
    results = model.train(
        data=GRADE_DATA_DIR,
        epochs=EPOCHS,
        imgsz=IMG_SIZE,
        batch=BATCH,
        device=device,
        name="grade_v3",
        patience=25,
        # augmentation แรงหน่อย ช่วยลด overfit เพราะเกรด A มีตัวอย่างน้อยกว่าเกรดอื่นมาก
        hsv_h=0.015, hsv_s=0.4, hsv_v=0.4,
        degrees=15, translate=0.1, scale=0.3,
        fliplr=0.5, flipud=0.0,
        erasing=0.2,
        auto_augment="randaugment",
    )
    return results


def step3_evaluate(results):
    """ขั้นตอนที่ 3: ตรวจผลลัพธ์สุดท้ายบน validation set"""
    best_model_path = str(results.save_dir / "weights" / "best.pt")
    print(f"\nใช้โมเดลจาก: {best_model_path}")

    model = YOLO(best_model_path)
    metrics = model.val(data=GRADE_DATA_DIR)

    print("\n=== สรุปผลลัพธ์ ===")
    print(f"Top-1 accuracy: {metrics.top1:.4f}")
    print(f"Top-5 accuracy: {metrics.top5:.4f}")
    print(f"\nเทียบกับของเดิม (จาก 122 รูป): Top-1 accuracy 66.7%")
    print(f"\nโมเดลตัวใหม่อยู่ที่: {best_model_path}")
    print("เอาไฟล์นี้ไป copy แทนที่ best.pt เดิมในโฟลเดอร์ backend เพื่อใช้งานจริง")


def main():
    print("=== ขั้นตอนที่ 1: แปลงข้อมูลตำหนิเป็นเกรด A/B/C ===")
    step1_convert_to_grades()

    print("=== ขั้นตอนที่ 2: เทรนโมเดล ===")
    results = step2_train()

    print("=== ขั้นตอนที่ 3: ตรวจผลลัพธ์ ===")
    step3_evaluate(results)


if __name__ == "__main__":
    main()