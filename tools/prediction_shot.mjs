// prediction_shot.mjs — 予想画面を X の「予想詳細」リプ用の画像にする（Mac で実行。画面なしの Chrome を DevTools プロトコルで直接操作）
//
//   node tools/prediction_shot.mjs <URL> <出力の頭.png>
//   ・URL=/predict-v2?raceId=…
//   ・スマホの幅（390px・3倍の解像度）で4枚撮る:
//       <出力>_1.png ◎○ / _2.png ▲△ / _3.png 注☆ （印の上位6頭のカード、2頭ずつ）
//       <出力>_4.png 鬼眼買い目
//   画面に固定表示のロゴなどは隠して撮る。
import { spawn } from 'node:child_process';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const [url, out] = process.argv.slice(2);
const port = 9334;
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), 'pshot-'))}`,
   '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let ws;
for (let i = 0; i < 50; i++) {
  try { const t = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
        const p = t.find(x => x.type === 'page'); if (p) { ws = new WebSocket(p.webSocketDebuggerUrl); break; } } catch {}
  await sleep(200);
}
await new Promise(r => ws.onopen = r);
let id = 0; const pending = new Map();
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 3, mobile: true });
await send('Page.navigate', { url });
await sleep(5000);   // フォントの読み込み待ち
// カードは画面に入ったときに表示される（フェードイン）ので、上位6頭のカードまで順に送って表示・点数バーを出し、
// 遅れて読み込まれる馬の写真も読み込ませる
await send('Runtime.evaluate', { awaitPromise: true, expression:
  `(async () => { const cards = [...document.querySelectorAll('div.horse-card')].slice(0, 6);
     for (const c of cards) { c.scrollIntoView({block: 'center'}); await new Promise(r => setTimeout(r, 400)); }
     cards.forEach(c => { c.classList.add('revealed'); c.style.transitionDelay = '0ms';
       const f = c.querySelector('.score-bar-fill'); if (f && f.dataset.width) f.style.width = f.dataset.width + '%'; });
     await Promise.all([...document.images].filter(i => !i.complete).map(i => new Promise(r => { i.onload = i.onerror = r; setTimeout(r, 5000); })));
     scrollTo(0, 0); })()` });
await sleep(1500);   // フェードイン・点数バーの動きが終わるまで
const r = await send('Runtime.evaluate', { returnByValue: true, expression:
  `(() => { document.querySelectorAll('body *').forEach(el => { const p = getComputedStyle(el).position;
              if (p === 'fixed' || p === 'sticky') el.style.display = 'none'; });
            const abs = el => { const b = el.getBoundingClientRect(); return {x: b.left + scrollX, y: b.top + scrollY, w: b.width, h: b.height}; };
            const union = els => { const bs = els.map(abs); const x = Math.min(...bs.map(b => b.x)), y = Math.min(...bs.map(b => b.y));
              return {x, y, w: Math.max(...bs.map(b => b.x + b.w)) - x, h: Math.max(...bs.map(b => b.y + b.h)) - y}; };
            const cards = [...document.querySelectorAll('div.horse-card')];
            const marks = cards.map(c => (c.querySelector('.rank-mark') || {}).textContent?.trim());
            const want = ['◎', '○', '▲', '△', '注', '☆'];
            if (want.some((m, i) => marks[i] !== m)) return {error: '印の並びが ◎○▲△注☆ ではない: ' + marks.slice(0, 6).join('')};
            const head = [...document.querySelectorAll('.section-heading')].find(h => h.textContent.includes('鬼眼買い目'));
            const bet = head && head.nextElementSibling;
            if (!bet) return {error: '鬼眼買い目が見つからない'};
            return {parts: [union(cards.slice(0, 2)), union(cards.slice(2, 4)), union(cards.slice(4, 6)), union([head, bet])],
                    names: cards.slice(0, 6).map(c => (c.querySelector('.horse-name') || c).textContent.trim())}; })()` });
const v = r.result.result.value;
if (!v || v.error) { console.error(v ? v.error : '読み取りに失敗'); ws.close(); chrome.kill(); process.exit(1); }
await sleep(500);
const pad = 8;
for (const [i, c] of v.parts.entries()) {
  const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true,
    clip: { x: Math.max(0, c.x - pad), y: c.y - pad, width: c.w + pad * 2, height: c.h + pad * 2, scale: 1 } });
  const f = out.replace(/\.png$/, `_${i + 1}.png`);
  writeFileSync(f, Buffer.from(shot.result.data, 'base64'));
  console.log(f, Math.round(c.w), 'x', Math.round(c.h));
}
console.log('上位6頭:', v.names.join(' / '));
ws.close(); chrome.kill();
process.exit(0);
