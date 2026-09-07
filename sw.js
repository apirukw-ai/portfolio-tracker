const CACHE_NAME = 'portfolio-pwa-v1';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(clients.claim());
});

self.addEventListener('fetch', (event) => {
  // ให้ดึงข้อมูลสดจากเครือข่ายเสมอเพื่อความอัปเดตของ NAV และ Supabase
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
