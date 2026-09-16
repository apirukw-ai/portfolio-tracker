import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any
import pythainav as nav
from supabase import Client, create_client

# ==========================================
# 1. ตั้งค่าการเชื่อมต่อ Supabase
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Error: กรุณาตั้งค่า SUPABASE_URL และ SUPABASE_KEY ใน Environment Variables")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 2. รายชื่อกองทุน MFC 6 ชื่อหลักที่ผ่านการทดสอบ
# ==========================================
TARGET_FUNDS = [
    'IGOLD-G',
    'MGTECH',
    'M-EM',
    'MEURO-G',
    'MGFPVD',
    'M-ASIA'
]

def fetch_mfc_nav() -> Dict[str, float]:
    """ดึงข้อมูล NAV ผ่าน pythainav เฉพาะ 6 กองทุนหลักที่ระบุ"""
    nav_results: Dict[str, float] = {}
    print("📡 กำลังดึงข้อมูล NAV ผ่าน pythainav...")

    for symbol in TARGET_FUNDS:
        try:
            result = nav.get(symbol)
            nav_val = None

            if hasattr(result, 'value') and result.value is not None:
                nav_val = float(result.value)
            elif isinstance(result, (int, float)):
                nav_val = float(result)

            if nav_val and nav_val > 0:
                nav_results[symbol] = nav_val
                print(f"✅ {symbol:<10} -> NAV: {nav_val}")
            else:
                print(f"⚠️ {symbol:<10} -> ไม่พบค่า NAV")
        except Exception as e:
            print(f"❌ {symbol:<10} -> Error: {e}")

    return nav_results

def update_supabase_batch(nav_data: Dict[str, float]) -> None:
    """อัปเดตข้อมูล NAV ลง Supabase แบบ Batch Update (Upsert)"""
    if not nav_data:
        print("⚠️ ไม่มีข้อมูล NAV ที่จะอัปเดต")
        return

    thai_tz = timezone(timedelta(hours=7))
    now_thai_dt = datetime.now(thai_tz)
    now_thai_iso = now_thai_dt.isoformat()
    today_date_str = now_thai_dt.strftime("%Y-%m-%d")

    try:
        db_res = supabase.table("user_portfolios").select("*").ilike("app_source", "MFC").execute()
        mfc_items = db_res.data or []
    except Exception as e:
        print(f"❌ ไม่สามารถดึงข้อมูลจาก Supabase ได้: {e}")
        return

    batch_payload: List[Dict[str, Any]] = []

    for item in mfc_items:
        item_id = item["id"]
        asset_name = item.get("asset_name", "").strip()
        units = float(item.get("units") or 0)

        latest_nav = nav_data.get(asset_name)

        if latest_nav:
            current_value = round(units * latest_nav, 4)
            batch_payload.append({
                "id": item_id,
                "current_nav": round(latest_nav, 4),
                "current_value": current_value,
                "nav_date": today_date_str,
                "updated_at": now_thai_iso
            })

    if batch_payload:
        try:
            supabase.table("user_portfolios").upsert(batch_payload).execute()
            print(f"💾 อัปเดต Supabase แบบ Batch สำเร็จทั้งหมด {len(batch_payload)} รายการ")
        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาดในการอัปเดตแบบ Batch: {e}")
    else:
        print("⚠️ ไม่พบ asset_name ใน Supabase ที่ตรงกับ 6 กองทุนนี้ (ตรวจสอบว่า asset_name ใน Supabase สะกดตรงกันหรือไม่)")

if __name__ == "__main__":
    print("🚀 เริ่มต้นกระบวนการ Auto Update NAV (pythainav)...")
    nav_data = fetch_mfc_nav()

    print("-" * 40)
    print(f"📊 สรุปข้อมูลที่ดึงได้ ({len(nav_data)}/6 กองทุน): {nav_data}")
    print("-" * 40)

    update_supabase_batch(nav_data)
    print("✨ ทำงานเสร็จสิ้น!")
