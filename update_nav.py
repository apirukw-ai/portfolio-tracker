import os
import re
import requests
import yfinance as yf
from bs4 import BeautifulSoup
from supabase import create_client, Client

# ----------------------------------------------------
# 1. เชื่อมต่อ Supabase
# ----------------------------------------------------
SUPABASE_URL = os.environ.get('SUPABASE_URL','https://iproktvvetsbxxmpptuj.supabase.co')
SUPABASE_SERVICE_ROLE_KEY = os.environ.get('SUPABASE_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlwcm9rdHZ2ZXRzYnh4bXBwdHVqIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NzI5NTc0MSwiZXhwIjoyMTAyODcxNzQxfQ.THAP7rEfCRacre7gDGsQxKmjw-DHbUf6kIoimDQl2Wk')
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError("Missing Supabase credentials in environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept-Language': 'th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7'
}

# ----------------------------------------------------
# 2. ฟังก์ชันเฉพาะสำหรับ MFC (ใช้ Logic Scraping ของคุณ)
# ----------------------------------------------------
def fetch_mfc_html_content():
    """ ดึงหน้า HTML จากเว็บ MFC มาเตรียมไว้ก่อนลูป """
    target_url = "https://mfcfund.com/unit-value/"
    try:
        print("🌐 กำลังโหลดข้อมูลหน้าเว็บ MFC (https://mfcfund.com/unit-value/)...")
        res = requests.get(target_url, headers=HEADERS, timeout=20)
        if res.status_code == 200:
            return res.text
        else:
            print(f"❌ ไม่สามารถเข้าถึงหน้าเว็บ MFC ได้ Status Code: {res.status_code}")
    except Exception as e:
        print(f"❌ Error fetching MFC Website: {e}")
    return ""

def get_nav_from_mfc_page(fund_code, fund_name, html_content):
    """ ค้นหาตัวเลข NAV โดยใช้ทั้งรหัสกองทุน และ ชื่อกองทุน จาก HTML ของ MFC """
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
# 3. ฟังก์ชันดึง NAV ของ SCB / GPF / หุ้น US
# ----------------------------------------------------
def get_scb_nav_wealthx(code):
    """ ดึง NAV กองทุน SCB ผ่าน WealthX """
    variations = [code.strip(), code.strip().replace('(', '').replace(')', ''), code.strip().replace('(E)', '-E')]
    for symbol in variations:
        try:
            url = f"https://www.wealthx.co/funds/{symbol}"
            res = requests.get(url, headers=HEADERS, timeout=8)
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
    """ ดึง NAV แผน กบข. """
    nav_map = {}
    try:
        url = "https://www.gpf.or.th/thai2019/About/main.php?page=memberfund&lang=th&size=n&pattern=n&menu=statistic"
        res = requests.get(url, headers=HEADERS, timeout=15)
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
    """ ดึงราคาหุ้น US (Dime) """
    if FINNHUB_API_KEY:
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
            res = requests.get(url, timeout=10).json()
            if res.get("c"):
                return float(res["c"])
        except Exception:
            pass

    try:
        ticker = yf.Ticker(symbol)
        todays_data = ticker.history(period='1d')
        if not todays_data.empty:
            return float(todays_data['Close'].iloc[-1])
    except Exception as e:
        print(f"⚠️ yfinance Error [{symbol}]: {e}")
    return None

# ----------------------------------------------------
# 4. ฟังก์ชันหลักสำหรับอัปเดตลง Supabase
# ----------------------------------------------------
def main():
    print("🚀 Starting NAV Auto Update Process...")
    
    response = supabase.table("user_portfolios").select("*").execute()
    portfolio = response.data

    if not portfolio:
        print("❌ No items found in user_portfolios table.")
        return

    print(f"📦 Found {len(portfolio)} assets to process.")
    
    # ดึง HTML MFC และข้อมูล GPF ไว้ก่อนลูป
    mfc_html = fetch_mfc_html_content()
    gpf_nav_data = get_gpf_nav_direct()

    for item in portfolio:
        item_id = item["id"]
        app = item["app_source"].lower()
        code = item.get("asset_code", "")
        name = item.get("asset_name", "")
        current_nav = float(item.get("current_nav") or 0)
        units = float(item.get("units") or 0)
        new_nav = None

        print(f"🔄 Processing [{app.upper()}] - {code} ...")

        if app == "dime":
            new_nav = get_us_stock_price(code)
        elif app == "gpf":
            new_nav = gpf_nav_data.get(code)
        elif app == "scb":
            new_nav = get_scb_nav_wealthx(code)
        elif app == "mfc":
            # ใช้วิธีสแกนหาจาก HTML ตาราง MFC ตามโค้ดของคุณ
            new_nav = get_nav_from_mfc_page(code, name, mfc_html)

        # อัปเดตราคา NAV เข้า Supabase
        if new_nav and new_nav > 0:
            if new_nav != current_nav:
                current_value = units * new_nav
                supabase.table("user_portfolios").update({
                    "current_nav": new_nav,
                    "current_value": current_value,
                    "updated_at": "now()"
                }).eq("id", item_id).execute()
                print(f" ✅ Updated {code}: {current_nav} ➔ {new_nav}")
            else:
                print(f" ℹ️ {code}: Price unchanged ({new_nav})")
        else:
            print(f" ❌ Failed to fetch new NAV for {code}")

if __name__ == "__main__":
    main()
