import os
import re
import requests
import yfinance as yf
from supabase import create_client, Client

# ----------------------------------------------------
# 1. เชื่อมต่อ Supabase
# ----------------------------------------------------
SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://iproktvvetsbxxmpptuj.supabase.co')
SUPABASE_SERVICE_ROLE_KEY = os.environ.get.('SUPABASE_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlwcm9rdHZ2ZXRzYnh4bXBwdHVqIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NzI5NTc0MSwiZXhwIjoyMTAyODcxNzQxfQ.THAP7rEfCRacre7gDGsQxKmjw-DHbUf6kIoimDQl2Wk')
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "da22fjpr01qp0a26e6ugda22fjpr01qp0a26e6v0")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError("Missing Supabase credentials in environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

# ----------------------------------------------------
# 2. ฟังก์ชันดึง NAV แต่ละแหล่ง (ใช้ Direct API)
# ----------------------------------------------------

def get_thai_fund_nav_finnomena(fund_code):
    """ ดึง NAV กองทุนรวมไทย (SCB / MFC / อื่นๆ) ผ่าน Finnomena Direct API """
    try:
        # ล้างชื่อกองทุน เช่น SCBWORLD(E) -> SCBWORLD-E
        clean_code = fund_code.strip().replace('(', '-').replace(')', '')
        url = f"https://mkt-fund.finnomena.com/api/fund/public/v1/fund/prices/{clean_code}/latest"
        
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json()
            # ดึงค่า nav ล่าสุด
            if 'data' in data and 'nav' in data['data']:
                return float(data['data']['nav'])
            elif 'nav' in data:
                return float(data['nav'])
    except Exception as e:
        print(f"⚠️ Finnomena API Error [{fund_code}]: {e}")
    return None

def get_gpf_nav_direct():
    """ ดึง NAV แผน กบข. ผ่าน API กบข. โดยตรง """
    nav_map = {}
    try:
        url = "https://www.gpf.or.th/thai2019/About/main.php?page=memberfund&lang=th&size=n&pattern=n&menu=statistic"
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.encoding = 'utf-8' if 'utf-8' in res.text.lower() else 'tis-620'
        html = res.text

        # แกะข้อมูลผ่าน Regex จากโครงสร้างตาราง กบข.
        rows = re.findall(r'<tr.*?>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE)
        for row in rows:
            nav_match = re.search(r'(\d+\.\d{4})', row)
            if not nav_match:
                continue
            
            nav_val = float(nav_match.group(1))

            if 'หุ้นต่างประเทศ' in row or '1788632129596' in row:
                nav_map['gpf_1788632129596'] = nav_val
                nav_map['แผนหุ้นต่างประเทศ'] = nav_val
            elif 'หุ้นไทย' in row and 'ต่างประเทศ' not in row:
                nav_map['gpf_1788631314182'] = nav_val
                nav_map['แผนหุ้นไทย'] = nav_val
            elif 'อสังหาริมทรัพย์' in row or '1788632247228' in row:
                nav_map['gpf_1788632247228'] = nav_val
                nav_map['แผนอสังหาริมทรัพย์ไทย'] = nav_val
    except Exception as e:
        print(f"⚠️ GPF Fetch Error: {e}")
    return nav_map

def get_us_stock_price(symbol):
    """ ดึงราคาหุ้น US / ETF (Dime) ผ่าน yfinance หรือ Finnhub """
    # ลองดึงจาก Finnhub ก่อนถ้ามี Key
    if FINNHUB_API_KEY:
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
            res = requests.get(url, timeout=10).json()
            if res.get("c"):
                return float(res["c"])
        except Exception:
            pass

    # Fallback ใช้ yfinance (ไม่ต้องใช้ Key)
    try:
        ticker = yf.Ticker(symbol)
        todays_data = ticker.history(period='1d')
        if not todays_data.empty:
            return float(todays_data['Close'].iloc[-1])
    except Exception as e:
        print(f"⚠️ yfinance Error [{symbol}]: {e}")
    
    return None

# ----------------------------------------------------
# 3. ฟังก์ชันหลักวนลูปอัปเดตตาราง user_portfolios ใน Supabase
# ----------------------------------------------------
def main():
    print("🚀 Starting NAV Auto Update Process...")
    
    # ดึงรายการสินทรัพย์ทั้งหมดจาก Supabase
    response = supabase.table("user_portfolios").select("*").execute()
    portfolio = response.data

    if not portfolio:
        print("❌ No items found in user_portfolios table.")
        return

    print(f"📦 Found {len(portfolio)} assets to process.")
    
    # โหลด NAV กบข. ลำดับแรก
    gpf_nav_data = get_gpf_nav_direct()

    for item in portfolio:
        item_id = item["id"]
        app = item["app_source"].lower()
        code = item["asset_code"]
        current_nav = float(item.get("current_nav") or 0)
        units = float(item.get("units") or 0)
        new_nav = None

        print(f"🔄 Processing [{app.upper()}] - {code} ...")

        # 1. กลุ่ม Dime (หุ้น US)
        if app == "dime":
            new_nav = get_us_stock_price(code)

        # 2. กลุ่ม GPF (กบข.)
        elif app == "gpf":
            new_nav = gpf_nav_data.get(code)

        # 3. กลุ่ม SCB, MFC และกองทุนรวมอื่นๆ
        elif app in ["scb", "mfc"]:
            new_nav = get_thai_fund_nav_finnomena(code)

        # ตรวจสอบและอัปเดตลง Supabase
        if new_nav and new_nav > 0:
            if new_nav != current_nav:
                current_value = units * new_nav
                
                # อัปเดตตาราง user_portfolios ใน Supabase
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
