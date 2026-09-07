import os
import re
import requests
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta, date
from supabase import create_client, Client

# ----------------------------------------------------
# 1. เชื่อมต่อ Supabase
# ----------------------------------------------------
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")

if not url or not key:
    print("❌ Missing Supabase Credentials")
    exit(1)

supabase: Client = create_client(url, key)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept-Language': 'th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7'
}

# ----------------------------------------------------
# 2. ฟังก์ชันดึง NAV ปัจจุบันจากเว็บ MFC (https://mfcfund.com/unit-value/)
# ----------------------------------------------------
def fetch_mfc_html_content():
    target_url = "https://mfcfund.com/unit-value/"
    try:
        print("🌐 กำลังโหลดข้อมูลจาก https://mfcfund.com/unit-value/...")
        res = requests.get(target_url, headers=HEADERS, timeout=20)
        if res.status_code == 200:
            return res.text
        else:
            print(f"❌ ไม่สามารถเข้าถึงหน้าเว็บ MFC ได้ Status Code: {res.status_code}")
    except Exception as e:
        print(f"❌ Error fetching MFC Website: {e}")
    return ""

def get_nav_from_mfc_page(fund_code, fund_name, html_content):
    """ ค้นหาตัวเลข NAV โดยใช้ทั้งรหัสกองทุน และ ชื่อกองทุน จากหน้าเว็บ MFC """
    if not html_content:
        return None
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        clean_code = fund_code.replace(' ', '').lower() if fund_code else ""
        clean_name = fund_name.replace(' ', '').lower() if fund_name else ""

        for row in soup.find_all('tr'):
            row_text = row.get_text(strip=True)
            clean_row = row_text.replace(' ', '').lower()
            
            is_match = False
            if clean_code and clean_code in clean_row:
                is_match = True
            elif clean_name and clean_name in clean_row:
                is_match = True

            if is_match:
                numbers = re.findall(r'\d+\.\d{4}', row_text)
                if numbers:
                    return float(numbers[0])
    except Exception as e:
        print(f"⚠️ เกิดข้อผิดพลาดในการแกะข้อมูล MFC ({fund_code} / {fund_name}): {e}")
    return None

# ----------------------------------------------------
# 3. ฟังก์ชันดึง NAV แอปอื่นๆ (SCB / GPF / Dime)
# ----------------------------------------------------
def get_scb_nav_wealthx(code):
    clean = code.strip()
    variations = [clean, clean.replace('(', '').replace(')', ''), clean.replace('(E)', '-E')]
    for symbol in variations:
        try:
            url_target = f"https://www.wealthx.co/funds/{symbol}"
            res = requests.get(url_target, headers=HEADERS, timeout=8)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                text = soup.get_text()
                match = re.search(r'มูลค่าหน่วยลงทุน\s*\(NAV\)\s*(\d+\.\d{4})', text)
                if match:
                    return float(match.group(1))
                matches = re.findall(r'(\d+\.\d{4})', text)
                if matches:
                    return float(matches[0])
        except Exception:
            pass
    return None

def get_gpf_nav_direct():
    nav_map = {}
    try:
        gpf_url = "https://www.gpf.or.th/thai2019/About/main.php?page=memberfund&lang=th&size=n&pattern=n&menu=statistic"
        res = requests.get(gpf_url, headers=HEADERS, timeout=15)
        res.encoding = 'utf-8' if 'utf-8' in res.text.lower() else 'tis-620'
        html = res.text

        rows = re.findall(r'<tr.*?>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE)
        for row in rows:
            nav_match = re.search(r'(\d+\.\d{4})', row)
            if not nav_match:
                continue
            nav_val = float(nav_match.group(1))

            if 'หุ้นต่างประเทศ' in row or '1788632129596' in row:
                nav_map['1788632129596'] = nav_val
                nav_map['แผนหุ้นต่างประเทศ'] = nav_val
            elif 'หุ้นไทย' in row and 'ต่างประเทศ' not in row:
                nav_map['1788631314182'] = nav_val
                nav_map['แผนหุ้นไทย'] = nav_val
            elif 'อสังหาริมทรัพย์' in row or '1788632247228' in row:
                nav_map['1788632247228'] = nav_val
                nav_map['แผนอสังหาริมทรัพย์ไทย'] = nav_val
    except Exception as e:
        print(f"⚠️ GPF Fetch Error: {e}")
    return nav_map

def get_us_stock_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        todays_data = ticker.history(period='1d')
        if not todays_data.empty:
            return float(todays_data['Close'].iloc[-1])
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

        # 1. โหลดหน้า HTML ของ MFC และข้อมูล GPF
        mfc_html = fetch_mfc_html_content()
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

            if app == "mfc":
                # ดึง NAV ปัจจุบันจากเว็บ MFC
                latest_nav = get_nav_from_mfc_page(code, name, mfc_html)
            elif app == "scb":
                latest_nav = get_scb_nav_wealthx(code)
            elif app == "gpf":
                latest_nav = gpf_nav_data.get(code)
            elif app == "dime":
                latest_nav = get_us_stock_price(code)

            # อัปเดตเฉพาะ current_nav และ current_value (ไม่กระทบต้นทุนและหน่วย)
            final_nav = latest_nav if (latest_nav and latest_nav > 0) else current_nav
            
            if latest_nav and latest_nav != current_nav:
                supabase.table('user_portfolios').update({
                    'current_nav': final_nav,
                    'current_value': units * final_nav,
                    'nav_date': nav_date,
                    'updated_at': now_thai
                }).eq('id', item_id).execute()
                print(f" ✅ อัปเดตสำเร็จ {code}: {current_nav} ➔ {final_nav}")
            else:
                supabase.table('user_portfolios').update({
                    'nav_date': nav_date,
                    'updated_at': now_thai
                }).eq('id', item_id).execute()
                print(f" ℹ️ {code} ราคาล่าสุด: {final_nav} (อัปเดตสถานะเสร็จสิ้น)")

        print(f"✅ อัปเดต NAV ปัจจุบันเสร็จสิ้นเมื่อ: {now_thai}")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    fetch_and_update()
