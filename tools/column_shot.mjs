// column_shot.mjs — コラムを X に載せる画像にする（Mac で実行。画面なしの Chrome を DevTools プロトコルで直接操作）
//
//   node tools/column_shot.mjs <URL> <CSSセレクタ> <出力.png> [幅=760] [split|single]
//   ・鬼眼コラム: URL=/predict-v2?raceId=…  セレクタ=.glass-card.column-card  split（本文 と 展開図 の2枚）
//       → <出力>_text.png / <出力>_diagram.png
//   ・週中コラム: URL=/column  セレクタ=#race-<race_id>  single（1枚）→ <出力>.png
//   画面に固定表示のロゴ・押せない「根拠を見る」・タップの案内は隠して撮る。2倍の解像度。
import { spawn } from 'node:child_process';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const [url, selector, out, width = '760', mode = 'split'] = process.argv.slice(2);
const port = 9333;
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), 'cshot-'))}`,
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
await send('Emulation.setDeviceMetricsOverride', { width: +width, height: 1000, deviceScaleFactor: 2, mobile: false });
await send('Page.navigate', { url });
await sleep(6000);   // フォント・画像の読み込み待ち
// 画像に不要なもの（画面に固定表示のロゴ・押せない「根拠を見る」・タップの案内）を隠し、
// コラムを「本文」と「展開図」の2枚に分けて撮る
const r = await send('Runtime.evaluate', { returnByValue: true, expression:
  `(() => { const card = document.querySelector(${JSON.stringify(selector)}); if (!card) return null;
            document.querySelectorAll('body *').forEach(el => { const p = getComputedStyle(el).position;
              if ((p === 'fixed' || p === 'sticky') && !card.contains(el)) el.style.display = 'none'; });
            card.querySelectorAll('.diagram-why, .tweet-box, .older, .links').forEach(el => el.style.display = 'none');
            const note = card.querySelector('.diagram-note'); if (note) note.textContent = '丸の数字は馬番、色は枠の色、上の記号は鬼眼の印。近走の位置取り・末脚・想定ペースから描いたイメージで、実際の展開は出遅れや騎手の判断で変わります。';
            const abs = el => { const b = el.getBoundingClientRect(); return {x: b.left + scrollX, y: b.top + scrollY, w: b.width, h: b.height}; };
            const c = abs(card), d = card.querySelector('.diagram');
            const split = d ? abs(d).y - 6 : c.y + c.h;
            return {card: c, split}; })()` });
const v = r.result.result.value;
if (!v) { console.error('要素が見つかりません'); process.exit(1); }
await sleep(500);
const pad = 12, c = v.card;
const parts = mode === 'single' ? [['', c.y - pad, c.y + c.h + pad]]
  : [['text', c.y - pad, v.split], ['diagram', v.split, c.y + c.h + pad]];
for (const [name, y0, y1] of parts) {
  if (y1 - y0 < 20) continue;
  const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true,
    clip: { x: Math.max(0, c.x - pad), y: y0, width: c.w + pad * 2, height: y1 - y0, scale: 1 } });
  const f = name ? out.replace(/\.png$/, `_${name}.png`) : out;
  writeFileSync(f, Buffer.from(shot.result.data, 'base64'));
  console.log(f, Math.round(c.w), 'x', Math.round(y1 - y0));
}
ws.close(); chrome.kill();
process.exit(0);
