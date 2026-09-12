import os
import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup
import requests
from supabase import Client, create_client
import yfinance as yf

# ----------------------------------------------------
# 1. เชื่อมต่อ Supabase และตั้งค่าคงที่
# ----------------------------------------------------
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

if not url or not key:
    print("❌ Missing Supabase Credentials")
    exit(1)

supabase: Client = create_client(url, key)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7",
}


# ----------------------------------------------------
# 2. ฟังก์ชันดึง NAV และอัตราแลกเปลี่ยน
# ----------------------------------------------------
def get_usd_thb_rate():
    """ดึงอัตราแลกเปลี่ยน USD/THB ล่าสุด"""
    try:
        ticker = yf.Ticker("THB=X")
        hist = ticker.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        print(f"⚠️ Exchange Rate Fetch Error: {e}")
    return 33.00


def get_gpf_nav_direct():
    nav_map = {}
    try:
        gpf_url = (
            "https://www.gpf.or.th/thai2019/About/main.php?"
            "page=memberfund&lang=th&size=n&pattern=n&menu=statistic"
        )
        res = requests.get(gpf_url, headers=HEADERS, timeout=15)
        res.encoding = "utf-8" if "utf-8" in res.text.lower() else "tis-620"

        soup = BeautifulSoup(res.text, "html.parser")
        rows = soup.find_all("tr")

        for row in rows:
            text = row.get_text()
            cols = [
                re.sub(r"\s+", "", col.get_text())
                for col in row.find_all(["td", "th"])
            ]
            if not cols:
                continue

            nav_candidates = []
            for col_text in cols:
                match = re.search(r"^\d{1,3}(?:,\d{3})*\.\d{4}$", col_text)
                if match:
                    nav_candidates.append(float(match.group(0).replace(",", "")))

            if not nav_candidates:
                continue

            nav_val = nav_candidates[0]

            if "หุ้นต่างประเทศ" in text or "1788632129596" in text:
                nav_map["1788632129596"] = nav_val
                nav_map["แผนหุ้นต่างประเทศ"] = nav_val
            elif "หุ้นไทย" in text and "ต่างประเทศ" not in text:
                nav_map["1788631314182"] = nav_val
                nav_map["แผนหุ้นไทย"] = nav_val
            elif "อสังหาริมทรัพย์" in text or "1788632247228" in text:
                nav_map["1788632247228"] = nav_val
                nav_map["แผนอสังหาริมทรัพย์ไทย"] = nav_val

    except Exception as e:
        print(f"⚠️ GPF Fetch Error: {e}")

    return nav_map


def get_us_stock_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="5d")

        if len(hist) >= 2:
            current_price = round(float(hist["Close"].iloc[-1]), 4)
            prev_close = round(float(hist["Close"].iloc[-2]), 4)
            return current_price, prev_close

    except Exception as e:
        print(f"⚠️ yfinance Error [{symbol}]: {e}")
    return None, None


# ----------------------------------------------------
# 3. ฟังก์ชันหลักสำหรับประมวลผล อัปเดต NAV และ Snapshot
# ----------------------------------------------------
def fetch_and_update():
    try:
        thai_tz = timezone(timedelta(hours=7))
        now_thai_dt = datetime.now(thai_tz)
        now_thai = now_thai_dt.strftime("%Y-%m-%dT%H:%M:%S+07:00")
        today_date_str = now_thai_dt.strftime("%d/%m/%Y")

        gpf_nav_data = get_gpf_nav_direct()
        usd_rate = get_usd_thb_rate()

        db_res = supabase.table("user_portfolios").select("*").execute()
        portfolio_items = db_res.data or []

        print(f"📦 พบรายการสินทรัพย์ทั้งหมดใน DB {len(portfolio_items)} รายการ")

        # --- อัปเดต current_nav และ prev_nav เฉพาะ GPF และ Dime ---
        for item in portfolio_items:
            item_id = item["id"]
            app = item.get("app_source", "").lower()
            code = item.get("asset_code", "").strip()
            name = item.get("asset_name", "")
            current_nav = float(item.get("current_nav") or 0)
            units = float(item.get("units") or 0)

            if app not in ["gpf", "dime"]:
                continue

            print(f"🔄 กำลังประมวลผล [{app.upper()}] {code} - {name}...")

            update_payload = {"nav_date": today_date_str, "updated_at": now_thai}

            if app == "gpf":
                latest_nav = gpf_nav_data.get(code)
                if latest_nav and latest_nav > 0:
                    update_payload["current_nav"] = round(latest_nav, 4)
                    update_payload["current_value"] = round(units * latest_nav, 4)

            elif app == "dime":
                latest_nav, latest_prev_nav = get_us_stock_price(code)
                
                if latest_nav and latest_nav > 0:
                    update_payload["current_nav"] = round(latest_nav, 4)
                    update_payload["current_value"] = round(units * latest_nav, 4)
                
                if latest_prev_nav and latest_prev_nav > 0:
                    update_payload["prev_nav"] = round(latest_prev_nav, 4)

            # อัปเดตลง Supabase
            supabase.table("user_portfolios").update(update_payload).eq(
                "id", item_id
            ).execute()

            c_nav = update_payload.get("current_nav", current_nav)
            p_nav = update_payload.get("prev_nav", "-")
            print(f" ✅ อัปเดตสำเร็จ {code}: NAV={c_nav}, PrevNAV={p_nav}")

        # --- ดึงข้อมูลล่าสุดหลังอัปเดตเพื่อบันทึก Snapshot รายวัน (รวมทุกแอป) ---
        updated_db = supabase.table("user_portfolios").select("*").execute()
        latest_items = updated_db.data or []

        # ครอบคลุมทั้ง GPF, DIME, SCB, MFC และแปลงชื่อเป็นตัวพิมพ์ใหญ่เพื่อความสอดคล้อง
        all_apps = ["GPF", "DIME", "SCB", "MFC"]

        for app in all_apps:
            app_items = [i for i in latest_items if i.get("app_source", "").upper() == app]
            
            if app == "GPF":
                total_thb = sum(float(i.get("current_value") or 0) for i in app_items)
            elif app == "DIME":
                total_usd = sum(float(i.get("current_value") or 0) for i in app_items)
                total_thb = total_usd * usd_rate  # แปลง USD เป็น THB
            else:
                # สำหรับ SCB และ MFC ใช้ค่าน้ำหนัก THB ล่าสุดที่มีอยู่ในฐานข้อมูล
                total_thb = sum(float(i.get("current_value") or 0) for i in app_items)

            if total_thb > 0:
                save_daily_snapshot(supabase, app, total_thb)

        print(f"✅ อัปเดต NAV และ Snapshot ทั้งหมดเสร็จสิ้นเมื่อ: {now_thai}")

    except Exception as e:
        print(f"❌ Error: {e}")


# ----------------------------------------------------
# 4. ฟังก์ชันสำหรับบันทึก Snapshot รายวัน
# ----------------------------------------------------
def save_daily_snapshot(supabase_client, app_source, total_thb):
    try:
        today_str = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime(
            "%Y-%m-%d"
        )

        data = {
            "snapshot_date": today_str,
            "app_source": app_source.upper(),  # บันทึกเป็นตัวพิมพ์ใหญ่เสมอ (GPF, DIME, SCB, MFC)
            "total_value_thb": float(total_thb),
        }

        supabase_client.table("portfolio_snapshots").upsert(
            data, on_conflict="snapshot_date,app_source"
        ).execute()
        print(f"✅ Saved snapshot for {app_source.upper()}: ฿{total_thb:,.2f}")
    except Exception as e:
        print(f"⚠️ Failed to save snapshot for {app_source}: {e}")


if __name__ == "__main__":
    fetch_and_update()
