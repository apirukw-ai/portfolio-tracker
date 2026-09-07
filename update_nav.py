import os
import re
import requests
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta, date
from supabase import create_client, Client

# ----------------------------------------------------
# 1. เชื่อมต่อ Supabase และรับค่า Secrets
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
# 2. ฟังก์ชันดึง NAV แต่ละแหล่งข้อมูล
# ----------------------------------------------------

# ----------------------------------------------------
# ฟังก์ชันดึง NAV ของ MFC จาก Firebase โดยตรง (แม่นยำ 100%)
# ----------------------------------------------------
def get_mfc_nav_from_firebase():
    """ ดึงข้อมูล NAV ของ MFC ที่บันทึกไว้ใน Firebase Realtime Database """
    mfc_map = {}
    try:
        url = "https://scb-e-class-default-rtdb.asia-southeast1.firebasedatabase.app/mfc_ports.json"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            # รองรับทั้งแบบ List หรือ Dict
            items = data if isinstance(data, list) else data.get('funds', []) if isinstance(data, dict) else []
            for item in items:
                if isinstance(item, dict):
                    code = item.get('code')
                    nav = item.get('nav') or item.get('currentNav')
                    if code and nav:
                        mfc_map[code.strip().upper()] = float(nav)
            print(f"✅ โหลดข้อมูล NAV MFC จาก Firebase สำเร็จ ({len(mfc_map)} รายการ)")
    except Exception as e:
        print(f"⚠️ ดึงข้อมูล MFC จาก Firebase ไม่สำเร็จ: {e}")
    return mfc_map

# [SCB] ดึงผ่าน WealthX
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

# [GPF] ดึงหน้าเว็บ กบข.
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

# [DIME] ดึงราคาหุ้น US
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
# 3. ฟังก์ชันหลักสำหรับประมวลผลและอัปเดตลง Supabase
# ----------------------------------------------------
def fetch_and_update():
    try:
        thai_tz = timezone(timedelta(hours=7))
        now_thai_dt = datetime.now(thai_tz)
        now_thai = now_thai_dt.strftime('%d/%m/%Y %H:%M:%S')

        # 1. โหลดข้อมูล MFC จาก Firebase
        mfc_firebase_data = get_mfc_nav_from_firebase()

        # 2. โหลดข้อมูล GPF
        gpf_nav_data = get_gpf_nav_direct()

        # 3. ดึงรายการสินทรัพย์ทั้งหมดจาก Supabase
        db_res = supabase.table('user_portfolios').select('*').execute()
        portfolio_items = db_res.data or []

        print(f"📦 พบรายการสินทรัพย์ทั้งหมด {len(portfolio_items)} รายการ")

        for item in portfolio_items:
            item_id = item["id"]
            app = item.get("app_source", "").lower()
            code = item.get("asset_code", "").strip().upper()
            name = item.get("asset_name", "")
            current_nav = float(item.get("current_nav") or 0)
            units = float(item.get("units") or 0)
            latest_nav = None

            print(f"🔄 กำลังดึง NAV ของ [{app.upper()}] {code} - {name}...")

            if app == "mfc":
                # ดึงตรงจาก Firebase Map
                latest_nav = mfc_firebase_data.get(code)
            elif app == "scb":
                latest_nav = get_scb_nav_wealthx(code)
            elif app == "gpf":
                latest_nav = gpf_nav_data.get(code)
            elif app == "dime":
                latest_nav = get_us_stock_price(code)

            # อัปเดตราคาลง Supabase user_portfolios
            final_nav = latest_nav if (latest_nav and latest_nav > 0) else current_nav
            
            if latest_nav and latest_nav != current_nav:
                supabase.table('user_portfolios').update({
                    'current_nav': final_nav,
                    'current_value': units * final_nav,
                    'updated_at': now_thai
                }).eq('id', item_id).execute()
                print(f"✅ อัปเดตสำเร็จ {code}: {current_nav} ➔ {final_nav}")
            else:
                supabase.table('user_portfolios').update({
                    'updated_at': now_thai
                }).eq('id', item_id).execute()
                print(f"ℹ️ {code} ราคาล่าสุด: {final_nav} (ไม่เปลี่ยนแปลง)")

        print(f"✅ อัปเดตระบบเสร็จสิ้นเมื่อ: {now_thai}")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    fetch_and_update()
