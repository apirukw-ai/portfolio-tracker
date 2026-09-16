import os
import re
from datetime import datetime, timedelta, timezone
import requests
from supabase import Client, create_client

# ==========================================
# 1. ตั้งค่าการเชื่อมต่อ Supabase
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Error: กรุณาตั้งค่า SUPABASE_URL และ SUPABASE_KEY ใน GitHub Secrets")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 2. จับคู่ asset_name ใน Supabase -> ชื่อสัญลักษณ์บนเว็บ/ก.ล.ต.
# ==========================================
FUND_MAP = {
    'IGOLD-G': ['IGOLD-G', 'IGOLD'],         # MPF07
    'MGTECH':  ['MGTECH', 'MTECH', 'M-TECH'],  # MPF15
    'M-EM':    ['M-EM', 'MEM'],              # MPF18
    'MEURO-G': ['MEURO-G', 'MEURO'],         # MPF19
    'MGFPVD':  ['MGFPVD', 'MGF'],            # MPF23
    'M-ASIA':  ['M-ASIA', 'MASIA']           # MPF27
}


def fetch_mfc_nav():
    # SEC Open API สำหรับกองทุนรวม MFC (AMC ID: C0000000062)
    sec_url = "https://api.sec.or.th/FundDailyInfo/C0000000062/dailynav"
    nav_results = {}

    # Standard SEC Open API public key (สามารถขอ API Key ฟรีจากเว็บ SEC Open Data เพิ่มเติมได้)
    headers = {
        "Ocp-Apim-Subscription-Key": "260c6d98184a4ec491ff27a5ad8f226b",
        "User-Agent": "Mozilla/5.0"
    }

    print(f"📡 กำลังดึงข้อมูล NAV ผ่าน SEC Open API...")

    try:
        response = requests.get(sec_url, headers=headers, timeout=30)
        
        # กรณี SEC API ติด Rate Limit หรือต้องใช้ URL สำรอง (SEC Open Data Public API)
        if response.status_code != 200:
            print(f"⚠️ SEC Main API status: {response.status_code} กำลังลอง Endpoint สำรอง...")
            fallback_url = "https://backend.finnomena.com/api/v1/fund/nav/latest"
            res_fn = requests.get(fallback_url, timeout=30)
            if res_fn.status_code == 200:
                fn_data = res_fn.json().get("data", [])
                for item in fn_data:
                    fund_code = str(item.get("fund_code", "")).strip().upper()
                    nav_val = item.get("nav")
                    if not fund_code or nav_val is None:
                        continue
                    
                    clean_fund_code = re.sub(r'[\s\-]+', '', fund_code)
                    for asset_name, aliases in FUND_MAP.items():
                        if asset_name in nav_results:
                            continue
                        for alias in aliases:
                            clean_alias = re.sub(r'[\s\-]+', '', alias).upper()
                            if clean_alias == clean_fund_code:
                                nav_results[asset_name] = float(nav_val)
                                print(f"✅ เจอ {asset_name} ({fund_code}) -> NAV: {nav_val}")
                                break
                return nav_results

        sec_data = response.json()
        items = sec_data if isinstance(sec_data, list) else sec_data.get("last_val", [])

        print(f"ℹ️ ดึงข้อมูลสำเร็จ พบข้อมูลกองทุนทั้งหมด: {len(items)} รายการ")

        for item in items:
            fund_name = str(item.get("proj_abbr_name", "") or item.get("proj_name_en", "")).strip().upper()
            nav_val_raw = item.get("nav_price") or item.get("net_val")

            if not fund_name or nav_val_raw is None:
                continue

            try:
                nav_val = float(nav_val_raw)
            except ValueError:
                continue

            clean_fund_name = re.sub(r'[\s\-]+', '', fund_name)

            for asset_name, aliases in FUND_MAP.items():
                if asset_name in nav_results:
                    continue

                for alias in aliases:
                    clean_alias = re.sub(r'[\s\-]+', '', alias).upper()
                    if clean_alias == clean_fund_name:
                        if 1.0 <= nav_val <= 1000.0:
                            nav_results[asset_name] = nav_val
                            print(f"✅ เจอ {asset_name} ({fund_name}) -> NAV: {nav_val}")
                            break

        return nav_results

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดขณะดึง NAV ผ่าน API: {e}")
        return nav_results


def update_supabase(nav_data):
    if not nav_data:
        print("⚠️ ไม่มีข้อมูล NAV ที่จะอัปเดต")
        return

    thai_tz = timezone(timedelta(hours=7))
    now_thai_dt = datetime.now(thai_tz)
    now_thai = now_thai_dt.strftime("%Y-%m-%dT%H:%M:%S+07:00")
    today_date_str = now_thai_dt.strftime("%d/%m/%Y")

    db_res = supabase.table("user_portfolios").select("*").ilike("app_source", "MFC").execute()
    mfc_items = db_res.data or []

    for item in mfc_items:
        item_id = item["id"]
        asset_name = item.get("asset_name", "").strip()
        units = float(item.get("units") or 0)

        latest_nav = nav_data.get(asset_name)

        if latest_nav:
            try:
                update_payload = {
                    "current_nav": round(latest_nav, 4),
                    "current_value": round(units * latest_nav, 4),
                    "nav_date": today_date_str,
                    "updated_at": now_thai
                }
                supabase.table("user_portfolios").update(update_payload).eq("id", item_id).execute()
                print(f"💾 อัปเดต Supabase สำเร็จ: {asset_name} = NAV: {latest_nav}, Value: ฿{units * latest_nav:,.2f}")
            except Exception as e:
                print(f"❌ อัปเดต Supabase ไม่สำเร็จ ({asset_name}): {e}")


if __name__ == "__main__":
    print("🚀 เริ่มต้นกระบวนการ Auto Update NAV (SEC Open API)...")
    nav_data = fetch_mfc_nav()
    print(f"📊 สรุปข้อมูลที่ดึงได้ ({len(nav_data)} กองทุน): {nav_data}")
    update_supabase(nav_data)
    print("✨ ทำงานเสร็จสิ้น!")
