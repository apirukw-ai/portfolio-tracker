const CACHE_NAME = 'portfolio-pwa-v2';

// รายชื่อไฟล์โครงสร้างหน้าเว็บที่จะทำการ Cache ไว้ล่วงหน้า (Static Assets)
const STATIC_ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png'
];

// ----------------------------------------------------
// 1. Install Event: Cache Static Assets ล่วงหน้า
// ----------------------------------------------------
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('📦 [Service Worker] Pre-caching static assets');
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

// ----------------------------------------------------
// 2. Activate Event: ลบ Cache เก่าเมื่อมีการอัปเดต Version
// ----------------------------------------------------
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cache) => {
          if (cache !== CACHE_NAME) {
            console.log('🧹 [Service Worker] Removing old cache:', cache);
            return caches.delete(cache);
          }
        })
      );
    })
  );
  self.clients.claim();
});

// ----------------------------------------------------
// 3. Fetch Event: จัดการ Cacheตามประเภทของ Request
// ----------------------------------------------------
self.addEventListener('fetch', (event) => {
  const requestUrl = new URL(event.request.url);

  // --------------------------------------------------
  // กลยุทธ์ 1: Network Only สำหรับ Supabase API (NAV & Portfolio Data)
  // --------------------------------------------------
  // ตรวจสอบว่าเป็นการเรียกไปยัง Supabase หรือการดึงข้อมูลตัวเลขผ่าน REST API
  if (requestUrl.hostname.includes('supabase.co') || requestUrl.pathname.includes('/rest/v1/')) {
    event.respondWith(
      fetch(event.request).catch((err) => {
        console.error('❌ [SW Network Only] Fetching portfolio data failed (Offline):', err);
        // สามารถคืนค่า Response จำลองเมื่อ Offline ได้หากต้องการ
        return new Response(JSON.stringify({ error: 'Offline', message: 'ไม่สามารถเชื่อมต่อเครือข่ายเพื่อดึง NAV ปัจจุบันได้' }), {
          headers: { 'Content-Type': 'application/json' }
        });
      })
    );
    return;
  }

  // --------------------------------------------------
  // กลยุทธ์ 2: Stale-While-Revalidate สำหรับ HTML, JS, CSS, และ CDN Assets
  // --------------------------------------------------
  event.respondWith(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.match(event.request).then((cachedResponse) => {
        // ดึงข้อมูลสดจาก Network มาอัปเดต Cache ไว้เบื้องหลัง (Revalidate)
        const fetchPromise = fetch(event.request).then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200 && event.request.method === 'GET') {
            cache.put(event.request, networkResponse.clone());
          }
          return networkResponse;
        }).catch(() => {
          // หากไม่มีเน็ตและดึงจาก Network ไม่ได้ ให้ใช้ Cached Response ตัวเดิม
        });

        // ส่ง Response จาก Cache ให้ผู้ใช้ทันทีเพื่อความเร็ว (Stale) ถ้าไม่มี Cache จึงรอ Network
        return cachedResponse || fetchPromise;
      });
    })
  );
});
