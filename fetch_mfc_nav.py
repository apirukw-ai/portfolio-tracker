def fetch_mfc_nav():
    url = "https://mfcfund.com/unit-value/"
    nav_results = {}

    print(f"📡 กำลังเปิด Headless Browser เพื่อดึงข้อมูลจาก: {url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()

            # เปลี่ยนเป็น load และเพิ่ม timeout เป็น 60 วินาที
            page.goto(url, wait_until="load", timeout=60000)

            # บังคับรอให้ข้อมูลในตาราง (tr) ถูก Render ขึ้นมาก่อน
            try:
                page.wait_for_selector("tr", timeout=20000)
                page.wait_for_timeout(3000)  # หน่วงเวลา 3 วินาทีเพื่อให้ JS วาดตารางเสร็จเรียบร้อย
            except Exception as wait_err:
                print(f"⚠️ รอ Selector ตารางไม่ทัน: {wait_err}")

            html_content = page.content()
            browser.close()

        soup = BeautifulSoup(html_content, 'html.parser')
        rows = soup.find_all('tr')
        print(f"ℹ️ พบแถวตาราง (tr) ทั้งหมด: {len(rows)} แถว")

        for row in rows:
            raw_text = row.get_text()
            clean_text = re.sub(r'[\s\-]+', '', raw_text).upper()

            for asset_name, aliases in FUND_MAP.items():
                if asset_name in nav_results:
                    continue

                for alias in aliases:
                    clean_alias = re.sub(r'[\s\-]+', '', alias).upper()

                    if clean_alias in clean_text:
                        matches = re.findall(r'\d[\d\,]*\.\d{4}', raw_text)
                        if matches:
                            try:
                                nav_val = float(matches[0].replace(',', ''))
                                if 1.0 <= nav_val <= 500.0:
                                    nav_results[asset_name] = nav_val
                                    print(f"✅ เจอ {asset_name} (จากชื่อบนเว็บ '{alias}') -> NAV: {nav_val}")
                                    break
                            except ValueError:
                                continue

        return nav_results

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดขณะดึง NAV: {e}")
        return nav_results
