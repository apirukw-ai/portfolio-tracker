import os
import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup
import requests
from supabase import Client, create_client
import yfinance as yf

# ----------------------------------------------------
# 1. เชื่อมต่อ Supabase
# ----------------------------------------------------
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

if not url or not key:
    print("❌ Missing Supabase Credentials")
    exit(1)

supabase: Client = create_client(url, key)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7",
}


# ----------------------------------------------------
# 2. ฟังก์ชันดึง NAV สำหรับ GPF และ Dime
# ----------------------------------------------------
def get_gpf_nav_direct():
    nav_map = {}
    try:
        gpf_url = "https://www.gpf.or.th/thai2019/About/main.php?page=memberfund&lang=th&size=n&pattern=n&menu=statistic"
        res = requests.get(gpf_url, headers=HEADERS, timeout=15)
        res.encoding = "utf-8" if "utf-8" in res.text.lower() else "tis-620"

        soup = BeautifulSoup(res.text, "html.parser")
        rows = soup.find_all("tr")

        for row in rows:
            text = row.get_text()

            # ค้นหาคอลัมน์ (td/th) ในแถว
            cols = [
                re.sub(r"\s+", "", col.get_text()) for col in row.find_all(["td", "th"])
            ]
            if not cols:
                continue

            # ดึงตัวเลขทศนิยมทั้งหมดจากคอลัมน์ในแถวนั้น (คอลัมน์ NAV ของ กบข. มักจะใช้ทศนิยม 4 ตำแหน่ง)
            nav_candidates = []
            for col_text in cols:
                match = re.search(r"^\d{1,3}(?:,\d{3})*\.\d{4}$", col_text)
                if match:
                    nav_candidates.append(
                        float(match.group(0).replace(",", ""))
                    )

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
        todays_data = ticker.history(period="1d")
        if not todays_data.empty:
            return float(todays_data["Close"].iloc[-1])
    except Exception as e:
        print(f"⚠️ yfinance Error [{symbol}]: {e}")
    return None


# ----------------------------------------------------
# 3. ฟังก์ชันหลักสำหรับประมวลผลและอัปเดตลง user_portfolios
# ----------------------------------------------------
def fetch_and_update():
    try:
        thai_tz = timezone(timedelta(hours=7))
        now_thai_dt = datetime.now(thai_tz)
        now_thai = now_thai_dt.strftime("%Y-%m-%dT%H:%M:%S+07:00")
        today_date_str = now_thai_dt.strftime("%d/%m/%Y")

        # 1. โหลดข้อมูล GPF ล่วงหน้า
        gpf_nav_data = get_gpf_nav_direct()

        # 2. ดึงรายการสินทรัพย์ทั้งหมดจาก user_portfolios
        db_res = supabase.table("user_portfolios").select("*").execute()
        portfolio_items = db_res.data or []

        print(f"📦 พบรายการสินทรัพย์ทั้งหมดใน DB {len(portfolio_items)} รายการ")

        for item in portfolio_items:
            item_id = item["id"]
            app = item.get("app_source", "").lower()
            code = item.get("asset_code", "").strip()
            name = item.get("asset_name", "")
            current_nav = float(item.get("current_nav") or 0)
            units = float(item.get("units") or 0)
            latest_nav = None
            nav_date = today_date_str

            # ข้ามรายการที่ไม่ใช่ GPF หรือ DIME
            if app not in ["gpf", "dime"]:
                continue

            print(f"🔄 กำลังประมวลผล [{app.upper()}] {code} - {name}...")

            # ดึงราคาตามประเภทแอป
            if app == "gpf":
                latest_nav = gpf_nav_data.get(code)
            elif app == "dime":
                latest_nav = get_us_stock_price(code)

            final_nav = (
                latest_nav
                if (latest_nav and latest_nav > 0)
                else current_nav
            )

            # อัปเดตข้อมูลลง Supabase
            if latest_nav and latest_nav != current_nav:
                supabase.table("user_portfolios").update(
                    {
                        "current_nav": final_nav,
                        "current_value": units * final_nav,
                        "nav_date": nav_date,
                        "updated_at": now_thai,
                    }
                ).eq("id", item_id).execute()
                print(
                    f" ✅ อัปเดตสำเร็จ {code}: {current_nav} ➔"
                    f" {final_nav} ({nav_date})"
                )
            else:
                supabase.table("user_portfolios").update(
                    {"nav_date": nav_date, "updated_at": now_thai}
                ).eq("id", item_id).execute()
                print(
                    f" ℹ️ {code} ราคาล่าสุด: {final_nav} ({nav_date})"
                    " (อัปเดตสถานะเสร็จสิ้น)"
                )

        print(f"✅ อัปเดต NAV ปัจจุบัน (GPF & Dime) เสร็จสิ้นเมื่อ: {now_thai}")

    except Exception as e:
        print(f"❌ Error: {e}")


# ----------------------------------------------------
# 4. ฟังก์ชันสำหรับบันทึก Snapshot รายวัน
# ----------------------------------------------------
def save_daily_snapshot(supabase_client, app_source, total_thb):
    try:
        today_str = (
            datetime.now(timezone.utc) + timedelta(hours=7)
        ).strftime("%Y-%m-%d")

        data = {
            "snapshot_date": today_str,
            "app_source": app_source,
            "total_value_thb": float(total_thb),
        }

        supabase_client.table("portfolio_snapshots").upsert(
            data, on_conflict="snapshot_date,app_source"
        ).execute()
        print(f"✅ Saved snapshot for {app_source}: ฿{total_thb:,.2f}")
    except Exception as e:
        print(f"⚠️ Failed to save snapshot for {app_source}: {e}")


if __name__ == "__main__":
    fetch_and_update()
