// 鬼眼競馬予想のサービスワーカー（ホーム画面に追加できるようにするための最小構成）。
// 予想やオッズは常に最新が必要なので、ページは一切キャッシュせずネットワークから取る。
// オフライン時だけ、短いお知らせを返す。
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (e) => {
  if (e.request.mode !== 'navigate') return;  // 画像・CSS などはブラウザの通常処理に任せる
  e.respondWith(fetch(e.request).catch(() => new Response(
    '<meta charset="utf-8"><meta name="viewport" content="width=device-width">' +
    '<body style="background:#050708;color:#d4e8cc;font-family:sans-serif;text-align:center;padding-top:40vh">' +
    '📡 オフラインです。電波の良いところで開き直してね</body>',
    { headers: { 'Content-Type': 'text/html; charset=utf-8' } })));
});
