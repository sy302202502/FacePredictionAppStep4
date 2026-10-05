// review_card.mjs — 週末の「答え合わせ」を X 用の画像1枚にする（Mac で実行。画面なしの Chrome を DevTools プロトコルで直接操作）
//
//   node tools/review_card.mjs [土曜の日付 YYYY-MM-DD] [出力.png]
//   ・日付を省くと直近の土曜（今日が土日ならその週）。対象は土曜・日曜
//   ・対象は各場の11R（当日の予想ポストと同じ）。判定は /review/api（画面・Discord と同じ判定）をそのまま使う
//   ・出力を省くと ~/舞鬼法師/競馬/X投稿画像/<日曜の日付>_答え合わせ/答え合わせ.png
//   ・秋のG1は「鬼眼G1ロード」として成績を台帳に積み、画像の下に通算を出す
//       台帳: ~/舞鬼法師/競馬/鬼眼G1ロード/<年>秋.json （/review は直近30レースしか見られないため、手元に残す）
//   ・情報元・第三者の名前は画像に出さない（舞鬼法師の公開物のルール）
import { spawn } from 'node:child_process';
import { writeFileSync, readFileSync, existsSync, mkdirSync, mkdtempSync } from 'node:fs';
import { tmpdir, homedir } from 'node:os';
import { join, dirname } from 'node:path';

const BASE = process.env.APP_PUBLIC_URL || 'https://160-251-251-73.sslip.io';
const HOME = homedir();

// 秋のG1（開催順）。/review のレース名は途中で切れることがあるので先頭一致で見る
const G1_AUTUMN = [
  ['スプリンター', 'スプリンターズS'], ['秋華賞', '秋華賞'], ['菊花賞', '菊花賞'], ['天皇賞', '天皇賞（秋）'],
  ['エリザベス', 'エリザベス女王杯'], ['マイルチャ', 'マイルCS'], ['ジャパンC', 'ジャパンC'], ['ジャパンカ', 'ジャパンC'],
  ['チャンピオンズ', 'チャンピオンズC'], ['阪神JF', '阪神JF'], ['阪神ジュベ', '阪神JF'], ['朝日杯', '朝日杯FS'],
  ['有馬記念', '有馬記念'], ['ホープフル', 'ホープフルS'],
];
const G1_ORDER = ['スプリンターズS', '秋華賞', '菊花賞', '天皇賞（秋）', 'エリザベス女王杯', 'マイルCS',
                  'ジャパンC', 'チャンピオンズC', '阪神JF', '朝日杯FS', '有馬記念', 'ホープフルS'];
const g1Name = name => (G1_AUTUMN.find(([p]) => name.startsWith(p)) || [])[1] || null;

// ---- 対象の週末 ----
const ymd = d => d.toISOString().slice(0, 10);
const jstToday = () => new Date(Date.now() + 9 * 3600e3);
let sat;
if (process.argv[2]) sat = new Date(process.argv[2] + 'T00:00:00Z');
else { const t = jstToday(); sat = new Date(Date.UTC(t.getUTCFullYear(), t.getUTCMonth(), t.getUTCDate()));
       sat.setUTCDate(sat.getUTCDate() - ((sat.getUTCDay() + 1) % 7)); }
if (sat.getUTCDay() !== 6) { console.error('土曜の日付を指定してください:', ymd(sat)); process.exit(1); }
const sun = new Date(sat); sun.setUTCDate(sat.getUTCDate() + 1);
const days = [ymd(sat), ymd(sun)];
const out = process.argv[3] || join(HOME, '舞鬼法師/競馬/X投稿画像', `${days[1]}_答え合わせ`, '答え合わせ.png');

// ---- データ（/review の選択肢 → 11R → /review/api） ----
const html = await (await fetch(`${BASE}/review`)).text();
const opts = [...html.matchAll(/<option value="(\d{4}[0-9A-Z]{8})"[^>]*>\s*(\d{4}-\d{2}-\d{2})/g)]
  .map(m => ({ raceId: m[1], date: m[2] }))
  .filter(o => days.includes(o.date) && o.raceId.endsWith('11'));
const seen = new Set();
const races = [];
for (const o of opts) {
  if (seen.has(o.raceId)) continue; seen.add(o.raceId);
  const v = await (await fetch(`${BASE}/review/api?raceId=${o.raceId}`)).json();
  if (v.available) races.push(v);
}
if (!races.length) {
  console.error(`答え合わせに ${days.join('・')} の11Rが1件もありません（結果の自動取得が止まっていないか確認）`);
  process.exit(1);
}
races.sort((a, b) => a.raceDate.localeCompare(b.raceDate) || a.raceId.localeCompare(b.raceId));

// ---- 鬼眼G1ロードの台帳 ----
const year = days[0].slice(0, 4);
const ledgerPath = join(HOME, '舞鬼法師/競馬/鬼眼G1ロード', `${year}秋.json`);
const ledger = existsSync(ledgerPath) ? JSON.parse(readFileSync(ledgerPath, 'utf8')) : {};
for (const r of races) {
  const g = g1Name(r.raceName);
  if (g && r.settled) ledger[g] = { raceId: r.raceId, date: r.raceDate, honmei: r.honmeiName,
                                    rank: r.honmeiRank, hit: r.hitTypes, ret: r.returnTotal, inv: r.invested };
}
mkdirSync(dirname(ledgerPath), { recursive: true });
writeFileSync(ledgerPath, JSON.stringify(ledger, null, 2));

// ---- 集計 ----
const settled = races.filter(r => r.settled);
const known = settled.filter(r => r.payoutKnown);
const inv = known.reduce((s, r) => s + r.invested, 0), ret = known.reduce((s, r) => s + r.returnTotal, 0);
const win = settled.filter(r => r.honmeiRank === 1).length;
const place = settled.filter(r => r.honmeiRank && r.honmeiRank <= 3).length;
const wd = d => '日月火水木金土'[new Date(d + 'T00:00:00Z').getUTCDay()];
const md = d => `${+d.slice(5, 7)}/${+d.slice(8, 10)}(${wd(d)})`;
const yen = n => n.toLocaleString('ja-JP');
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

const rows = races.map(r => {
  const rank = r.honmeiRank;
  const cls = rank === 1 ? 'f1' : rank && rank <= 3 ? 'f3' : 'fx';
  const verdict = !r.settled ? '<span class="pending">判定待ち</span>'
    : r.hitTypes.length ? r.hitTypes.map(t => `<span class="chip">${esc(t)}</span>`).join('')
    : '<span class="miss">的中なし</span>';
  const money = r.settled && r.payoutKnown
    ? `<div class="money ${r.returnTotal > 0 ? 'plus' : ''}">払戻 ${yen(r.returnTotal)}円<small> / ${yen(r.invested)}円</small></div>` : '';
  const g = g1Name(r.raceName);
  return `<div class="race">
    <div class="rname">${g ? '<span class="g1">G1</span>' : ''}${esc(g || r.raceName)}<small>${md(r.raceDate)}</small></div>
    <div class="line"><span class="mark">◎</span><span class="num">${r.honmeiNumber ?? ''}</span>
      <span class="horse">${esc(r.honmeiName)}</span><span class="rank ${cls}">${rank ? rank + '着' : '—'}</span></div>
    <div class="foot"><div class="verdict">${verdict}</div>${money}</div></div>`;
}).join('');

const road = G1_ORDER.map(n => {
  const e = ledger[n];
  const cls = !e ? 'todo' : e.rank === 1 ? 'f1' : e.rank && e.rank <= 3 ? 'f3' : 'fx';
  return `<div class="dot ${cls}"><b>${e ? (e.rank ?? '—') : ''}</b><span>${esc(n.replace(/（秋）/, '秋'))}</span></div>`;
}).join('');
const roadDone = G1_ORDER.filter(n => ledger[n]);
const showRoad = roadDone.length > 0;
const roadSum = roadDone.length
  ? `${roadDone.length}/${G1_ORDER.length}戦　◎1着 ${roadDone.filter(n => ledger[n].rank === 1).length}・3着内 ${roadDone.filter(n => ledger[n].rank && ledger[n].rank <= 3).length}`
  : '';

const logo = join(HOME, '舞鬼法師/共有ブランド素材/maiki-logo.png');
const page = `<!doctype html><html lang="ja"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Noto+Sans+JP:wght@500;700;900&display=swap" rel="stylesheet">
<style>
  :root { --neon:#7dff4f; --gold:#c9a84c; --gold-light:#f5d878; --deep:#050708; --panel:#0c120c; --line:#1d2a1d;
          --text:#d4e8cc; --muted:#6f8a6f; --silver:#cfd8e3; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { width:540px; background:var(--deep); color:var(--text); font-family:'Noto Sans JP',sans-serif; }
  #card { padding:26px 24px 20px; background:radial-gradient(circle at 80% 0%, rgba(125,255,79,.10), transparent 55%), var(--deep); }
  header { display:flex; align-items:center; justify-content:space-between; margin-bottom:14px; }
  h1 { font-size:27px; font-weight:900; letter-spacing:.06em; color:#fff; }
  h1 em { font-style:normal; color:var(--neon); }
  .date { font-family:'Bebas Neue',sans-serif; font-size:19px; letter-spacing:2px; color:var(--muted); margin-top:2px; }
  header img { height:46px; }
  .race { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:9px 14px; margin-bottom:8px; }
  .rname { font-size:14px; font-weight:700; color:var(--muted); display:flex; align-items:center; gap:6px; }
  .rname small { margin-left:auto; font-size:12px; }
  .g1 { font-family:'Bebas Neue',sans-serif; font-size:13px; letter-spacing:1px; background:var(--gold); color:#111; border-radius:4px; padding:0 5px; }
  .line { display:flex; align-items:baseline; gap:8px; margin-top:2px; }
  .mark { color:#ff5a5a; font-weight:900; font-size:20px; }
  .num { font-family:'Bebas Neue',sans-serif; font-size:20px; color:#fff; min-width:18px; }
  .horse { font-size:20px; font-weight:900; color:#fff; }
  .rank { margin-left:auto; font-size:24px; font-weight:900; }
  .f1 { color:var(--gold-light); } .f3 { color:var(--silver); } .fx { color:var(--muted); }
  .foot { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-top:3px; }
  .verdict { display:flex; gap:5px; flex-wrap:wrap; }
  .chip { font-size:12px; font-weight:700; color:#0a0f0a; background:var(--neon); border-radius:99px; padding:2px 9px; }
  .miss, .pending { font-size:12px; color:var(--muted); }
  .money { font-size:13px; color:var(--muted); white-space:nowrap; }
  .money.plus { color:var(--gold-light); font-weight:700; }
  .money small { color:var(--muted); font-weight:500; }
  .total { display:grid; grid-template-columns:repeat(3,1fr); gap:6px; margin-top:12px; }
  .total div { border:1px solid var(--line); border-radius:10px; padding:8px 4px; text-align:center; }
  .total b { display:block; font-size:22px; font-weight:900; color:var(--gold-light); }
  .total span { font-size:11px; color:var(--muted); }
  .road { margin-top:14px; border-top:1px solid var(--line); padding-top:12px; }
  .road h2 { font-size:15px; font-weight:900; color:#fff; display:flex; justify-content:space-between; align-items:baseline; }
  .road h2 small { font-size:12px; color:var(--gold-light); font-weight:700; }
  .dots { display:grid; grid-template-columns:repeat(6,1fr); gap:5px; margin-top:8px; }
  .dot { text-align:center; }
  .dot b { display:flex; align-items:center; justify-content:center; height:30px; border-radius:8px; font-size:16px; font-weight:900;
           border:1px solid var(--line); background:var(--panel); }
  .dot.todo b { border-style:dashed; }
  .dot.f1 b { border-color:var(--gold); } .dot.f3 b { border-color:var(--silver); }
  .dot span { display:block; font-size:9px; color:var(--muted); margin-top:2px; white-space:nowrap; overflow:hidden; }
  footer { margin-top:12px; font-size:12px; color:var(--muted); text-align:center; }
</style></head><body><div id="card">
<header><div><h1>鬼眼 <em>答え合わせ</em></h1><div class="date">${md(days[0])} – ${md(days[1])}</div></div>
${existsSync(logo) ? `<img src="file://${logo}">` : ''}</header>
${rows}
<div class="total">
  <div><b>${win}</b><span>◎ 1着</span></div>
  <div><b>${place}/${settled.length}</b><span>◎ 3着以内</span></div>
  <div><b>${inv ? Math.round(ret * 100 / inv) + '%' : '—'}</b><span>回収率（${known.length}レース）</span></div>
</div>
${showRoad ? `<div class="road"><h2>鬼眼G1ロード ${year}秋<small>${roadSum}</small></h2><div class="dots">${road}</div></div>` : ''}
<footer>当たりも外れも、ぜんぶ載せます。</footer>
</div></body></html>`;

// ---- 撮影（prediction_shot.mjs と同じ方式） ----
const tmp = mkdtempSync(join(tmpdir(), 'rcard-'));
const htmlPath = join(tmp, 'card.html');
writeFileSync(htmlPath, page);
const port = 9335;
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${join(tmp, 'profile')}`,
   '--allow-file-access-from-files', '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
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
await send('Emulation.setDeviceMetricsOverride', { width: 540, height: 900, deviceScaleFactor: 2, mobile: false });
await send('Page.navigate', { url: 'file://' + htmlPath });
await sleep(1500);
await send('Runtime.evaluate', { awaitPromise: true, expression: 'document.fonts.ready.then(() => true)' });
await sleep(500);
const r = await send('Runtime.evaluate', { returnByValue: true,
  expression: '(() => { const b = document.getElementById("card").getBoundingClientRect(); return {w: b.width, h: b.height}; })()' });
const { w, h } = r.result.result.value;
const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true,
  clip: { x: 0, y: 0, width: w, height: h, scale: 1 } });
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, Buffer.from(shot.result.data, 'base64'));
console.log(out, Math.round(w * 2), 'x', Math.round(h * 2));
console.log(`対象 ${races.length}レース / ◎1着 ${win}・3着内 ${place} / 回収率 ${inv ? Math.round(ret * 100 / inv) : '-'}%`);
if (showRoad) console.log(`鬼眼G1ロード: ${roadSum}（台帳 ${ledgerPath}）`);
ws.close(); chrome.kill();
process.exit(0);
