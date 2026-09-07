import os
import requests
from supabase import create_client, Client

# 1. เชื่อมต่อ Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError("Missing Supabase credentials in environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

def get_fund_nav_th(asset_code):
    """ ดึงราคา NAV กองทุนรวมไทยผ่าน SEC Open API หรือ Fund API """
    try:
        # ตัวอย่างการเรียก API ดึง NAV กองทุนไทย (สามารถเปลี่ยน Endpoint ตาม API ที่ใช้งานได้)
        url = f"https://api.stateless.co.th/fund/{asset_code}/latest" 
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            return float(data.get("nav", 0))
    except Exception as e:
        print(f"Error fetching NAV for {asset_code}: {e}")
    return None

def get_us_stock_price(symbol):
    """ ดึงราคาหุ้น US ผ่าน Yahoo Finance API (ไม่ใช้ Key) """
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            price = data['chart']['result'][0]['meta']['regularMarketPrice']
            return float(price)
    except Exception as e:
        print(f"Error fetching US price for {symbol}: {e}")
    return None

def main():
    # 2. ดึงรายการสินทรัพย์ทั้งหมดในพอร์ต
    response = supabase.table("user_portfolios").select("id, app_source, asset_code, current_nav").execute()
    portfolio = response.data

    print(f"Found {len(portfolio)} assets to update.")

    for item in portfolio:
        item_id = item["id"]
        app = item["app_source"].lower()
        code = item["asset_code"]
        current_nav = item["current_nav"]
        new_nav = None

        # แยกประเภทการดึงข้อมูลตามแหล่งที่มา
        if app == "dime":
            # หุ้น US / ETF
            new_nav = get_us_stock_price(code)
        elif app in ["gpf", "mfc", "scb"]:
            # กองทุนรวมไทย
            new_nav = get_fund_nav_th(code)

        # 3. อัปเดตราคา NAV ลง Supabase หากได้ราคาใหม่
        if new_nav and new_nav != current_nav:
            supabase.table("user_portfolios").update({
                "current_nav": new_nav,
                "current_value": item.get("units", 0) * new_nav,
                "updated_at": "now()"
            }).eq("id", item_id).execute()
            print(f"✅ Updated {code}: {current_nav} -> {new_nav}")
        else:
            print(f"Skipped {code}: No change or fetch failed.")

if __name__ == "__main__":
    main()
