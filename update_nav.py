from datetime import date, datetime, timedelta, timezone
import os
import re

from bs4 import BeautifulSoup
import requests
from supabase import Client, create_client
import yfinance as yf

# ----------------------------------------------------
# 1. เชื่อมต่อ Supabase
# ----------------------------------------------------
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get(
    "SUPABASE_KEY"
)

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

# แมป Asset Code บน Supabase เข้ากับ ชื่อกองทุนบนหน้าเว็บ MFC
MFC_SYMBOL_MAP = {
    "MPF07": "IGOLD-G",
    "MPF15": "MGTECH",
    "MPF18": "M-EM",
    "MPF19": "MEURO-G",
    "MPF23": "MGFPVD",
    "MPF27": "M-ASIA",
    "MPF16": "M-FM",
}


# ----------------------------------------------------
# 2. ฟังก์ชันดึงและแกะ NAV จากหน้าเว็บ MFC (https://mfcfund.com/unit-value/)
# ----------------------------------------------------
def fetch_mfc_html_content():
    target_url = "https://mfcfund.com/unit-value/"
    try:
        print("🌐 กำลังโหลดข้อมูลจาก https://mfcfund.com/unit-value/...")
        res = requests.get(target_url, headers=HEADERS, timeout=20)
        if res.status_code == 200:
            return res.text
        else:
            print(
                f"❌ ไม่สามารถเข้าถึงหน้าเว็บ MFC ได้ Status Code:"
                f" {res.status_code}"
            )
    except Exception as e:
        print(f"❌ Error fetching MFC Website: {e}")
    return ""


def get_mfc_nav_from_web(fund_code, html_content):
    if not html_content:
        return None
    try:
        target_symbol = MFC_SYMBOL_MAP.get(
            fund_code.upper(), fund_code
        ).upper()
        soup = BeautifulSoup(html_content, "html.parser")

        # วนลูปหาแถวหรือบล็อกที่มีชื่อกองทุนอยู่
        for element in soup.find_all(["tr", "div"]):
            text = element.get_text(separator=" ", strip=True)

            if target_symbol in text.upper():
                idx = text.upper().find(target_symbol)
                chunk = text[idx : idx + 300]
                print(f"พบข้อมูล MFC [{target_symbol}]: {chunk}")

                # ดึงตัวเลข NAV (ทศนิยม 4 ตำแหน่ง)
                nav_match = re.search(r"(\d+\.\d{4})", chunk)
                if nav_match:
                    return float(nav_match.group(1))

    except Exception as e:
        print(f"⚠️ เกิดข้อผิดพลาดในการแกะ MFC [{fund_code}]: {e}")
    return None


# ----------------------------------------------------
# 3. ฟังก์ชันดึง NAV แอปอื่นๆ (SCB / GPF / Dime)
# ----------------------------------------------------
def get_scb_nav_wealthx(code):
    clean = code.strip()
    variations = [
        clean,
        clean.replace("(", "").replace(")", ""),
        clean.replace("(E)", "-E"),
    ]
    for symbol in variations:
        try:
            url_target = f"https://www.wealthx.co/funds/{symbol}"
            res = requests.get(url_target, headers=HEADERS, timeout=8)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                text = soup.get_text()
                match = re.search(
                    r"มูลค่าหน่วยลงทุน\s*\(NAV\)\s*(\d+\.\d{4})", text
                )
                if match:
                    return float(match.group(1))
                matches = re.findall(r"(\d+\.\d{4})", text)
                if matches:
                    return float(matches[0])
        except Exception:
            pass
    return None


def get_gpf_nav_direct():
    nav_map = {}
    try:
        gpf_url = (
            "https://www.gpf.or.th/thai2019/About/main.php?page=memberfund&lang=th&size=n&pattern=n&menu=statistic"
        )
        res = requests.get(gpf_url, headers=HEADERS, timeout=15)
        res.encoding = "utf-8" if "utf-8" in res.text.lower() else "tis-620"
        html = res.text

        rows = re.findall(
            r"<tr.*?>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE
        )
        for row in rows:
            nav_match = re.search(r"(\d+\.\d{4})", row)
            if not nav_match:
                continue
            nav_val = float(nav_match.group(1))

            if "หุ้นต่างประเทศ" in row or "1788632129596" in row:
                nav_map["1788632129596"] = nav_val
                nav_map["แผนหุ้นต่างประเทศ"] = nav_val
            elif "หุ้นไทย" in row and "ต่างประเทศ" not in row:
                nav_map["1788631314182"] = nav_val
                nav_map["แผนหุ้นไทย"] = nav_val
            elif "อสังหาริมทรัพย์" in row or "1788632247228" in row:
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
# 4. ฟังก์ชันหลักสำหรับประมวลผลและอัปเดตลง user_portfolios
# ----------------------------------------------------
def fetch_and_update():
    try:
        thai_tz = timezone(timedelta(hours=7))
        now_thai_dt = datetime.now(thai_tz)
        now_thai = now_thai_dt.strftime('%d/%m/%Y %H:%M:%S')
        today_date_str = now_thai_dt.strftime('%d/%m/%Y')

        # 1. โหลดข้อมูล GPF ล่วงหน้า
        gpf_nav_data = get_gpf_nav_direct()

        # 2. ดึงรายการสินทรัพย์ทั้งหมดจาก user_portfolios
        db_res = supabase.table('user_portfolios').select('*').execute()
        portfolio_items = db_res.data or []

        print(f"📦 พบรายการสินทรัพย์ทั้งหมด {len(portfolio_items)} รายการ")

        for item in portfolio_items:
            item_id = item["id"]
            app = item.get("app_source", "").lower()
            code = item.get("asset_code", "").strip()
            name = item.get("asset_name", "")
            current_nav = float(item.get("current_nav") or 0)
            units = float(item.get("units") or 0)
            latest_nav = None
            nav_date = today_date_str

            print(f"🔄 กำลังประมวลผล [{app.upper()}] {code} - {name}...")

            # ดึง NAV และ วันที่ ตามประเภทแอป
            if app in ["mfc", "mfc_fund"]:
                p_res = supabase.table('policies').select('nav, updated_at').eq('code', code).execute()
                if p_res.data and len(p_res.data) > 0:
                    latest_nav = float(p_res.data[0]['nav'])
                    policy_date = p_res.data[0].get('updated_at')
                    if policy_date:
                        nav_date = policy_date
            elif app == "scb":
                latest_nav = get_scb_nav_wealthx(code)
            elif app == "gpf":
                latest_nav = gpf_nav_data.get(code)
            elif app == "dime":
                latest_nav = get_us_stock_price(code)

            final_nav = latest_nav if (latest_nav and latest_nav > 0) else current_nav
            
            # อัปเดตทั้ง current_nav, current_value และ nav_date ลง user_portfolios
            if latest_nav and latest_nav != current_nav:
                supabase.table('user_portfolios').update({
                    'current_nav': final_nav,
                    'current_value': units * final_nav,
                    'nav_date': nav_date,
                    'updated_at': now_thai
                }).eq('id', item_id).execute()
                print(f" ✅ อัปเดตสำเร็จ {code}: {current_nav} ➔ {final_nav} ({nav_date})")
            else:
                supabase.table('user_portfolios').update({
                    'nav_date': nav_date,
                    'updated_at': now_thai
                }).eq('id', item_id).execute()
                print(f" ℹ️ {code} ราคาล่าสุด: {final_nav} ({nav_date}) (อัปเดตสถานะเสร็จสิ้น)")

        print(f"✅ อัปเดต NAV ปัจจุบันเสร็จสิ้นเมื่อ: {now_thai}")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    fetch_and_update()
