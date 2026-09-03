/* ============================================================
   まいきーおしりビート — 舞鬼法師リズムゲーム
   ・音源ファイル不要（WebAudioで BGM / SE を合成）
   ・譜面はシード固定の疑似乱数で生成（同じ難易度なら毎回同じ譜面）
   ・判定クロックは AudioContext.currentTime（フレーム落ちに強い）
   ============================================================ */
(function () {
    'use strict';

    // ---------- 難易度設定 ----------
    // bars: 4拍1小節の数 / density: 8分グリッドにノーツを置く確率
    // travel: ノーツが画面上端から判定ラインに到達するまでの秒数
    var DIFFS = {
        easy:   { label: 'EASY',   bpm:  96, density: 0.42, travel: 1.90, chord: 0.00, hpMiss:  6, bars: 32, seed: 20260301 },
        normal: { label: 'NORMAL', bpm: 124, density: 0.60, travel: 1.55, chord: 0.06, hpMiss:  8, bars: 36, seed: 20260302 },
        hard:   { label: 'HARD',   bpm: 152, density: 0.78, travel: 1.25, chord: 0.14, hpMiss: 10, bars: 40, seed: 20260303 }
    };

    var W_PERFECT = 0.055, W_GREAT = 0.100, W_GOOD = 0.155;
    var LANES = 4;
    var KEYMAP = { KeyD: 0, KeyF: 1, KeyJ: 2, KeyK: 3,
                   ArrowLeft: 0, ArrowDown: 1, ArrowUp: 2, ArrowRight: 3 };
    var LEAD_IN = 2.4;            // カウントダウン後、最初のノーツまでの余白（秒）
    var FEVER_COMBO = 20;         // このコンボ毎にフィーバー突入
    var FEVER_SEC = 8;
    var LOOKAHEAD = 0.18;         // BGMスケジューラの先読み（秒）
    var HIT_TEXT = ['パンッ!', 'ペチッ!', 'スパーン!', 'ドンッ!'];
    var BEST_KEY = 'oshiriBeat.best.v1';

    // ---------- DOM ----------
    var $ = function (id) { return document.getElementById(id); };
    var stage, lanesEl, padsEl, noteLayers = [], chara,
        judgeEl, comboEl, comboNumEl, feverEl, hpFill, scoreEl, comboMaxEl,
        titleOv, pauseOv, resultOv, countEl, muteBtn, pauseBtn, rainEl;

    // ---------- 状態 ----------
    var diffKey = 'normal';
    var notes = [];               // { t, lane, judged, el, gold }
    var active = [];              // 表示中ノーツ
    var spawnIdx = 0;
    var state = 'title';          // title | count | play | pause | result
    var startTime = 0;            // songTime = clock() - startTime
    var pauseMark = 0;
    var songEnd = 0;
    var rafId = null;
    var stageH = 0, hitPx = 0, noteH = 0;
    var stats, hp, combo, maxCombo, score, feverUntil, nextBeat;
    var useAudioClock = false, audioStart = 0, audioPauseMark = 0;
    var muted = false;

    // ---------- WebAudio ----------
    var ctx = null, master = null, noiseBuf = null;

    function initAudio() {
        if (ctx) { return; }
        var AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) { return; }
        ctx = new AC();
        master = ctx.createGain();
        master.gain.value = muted ? 0 : 0.9;
        master.connect(ctx.destination);
        // ホワイトノイズ（ハイハット / スラップ音の素）
        noiseBuf = ctx.createBuffer(1, Math.floor(ctx.sampleRate * 0.5), ctx.sampleRate);
        var d = noiseBuf.getChannelData(0);
        for (var i = 0; i < d.length; i++) { d[i] = Math.random() * 2 - 1; }
    }

    // 判定クロックは AudioContext.currentTime を最優先で使う（rAFより安定）。
    // ただし音声デバイスが無い等で running にならない環境ではフレームクロックへ退避する。
    // どちらを使うかは1プレイの開始時に固定し、途中で切り替えない（時刻が飛ぶため）。
    function clock() {
        return useAudioClock ? ctx.currentTime : (performance.now() / 1000);
    }

    function env(node, at, peak, attack, decay) {
        var g = node.gain;
        g.setValueAtTime(0.0001, at);
        g.exponentialRampToValueAtTime(Math.max(peak, 0.0002), at + attack);
        g.exponentialRampToValueAtTime(0.0001, at + attack + decay);
    }

    function tone(at, freqFrom, freqTo, dur, peak, type, dest) {
        if (!ctx) { return; }
        var o = ctx.createOscillator(), g = ctx.createGain();
        o.type = type || 'sine';
        o.frequency.setValueAtTime(freqFrom, at);
        if (freqTo && freqTo !== freqFrom) {
            o.frequency.exponentialRampToValueAtTime(Math.max(freqTo, 1), at + dur);
        }
        env(g, at, peak, 0.005, dur);
        o.connect(g); g.connect(dest || master);
        o.start(at); o.stop(at + dur + 0.05);
    }

    function noise(at, dur, peak, filterType, freq, q) {
        if (!ctx || !noiseBuf) { return; }
        var s = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain();
        s.buffer = noiseBuf;
        f.type = filterType; f.frequency.value = freq;
        if (q) { f.Q.value = q; }
        env(g, at, peak, 0.004, dur);
        s.connect(f); f.connect(g); g.connect(master);
        s.start(at); s.stop(at + dur + 0.05);
    }

    // --- 効果音 ---
    function sfxSlap(kind) {
        if (!ctx) { return; }
        var at = ctx.currentTime + 0.001;
        noise(at, kind === 'perfect' ? 0.13 : 0.09, kind === 'miss' ? 0.10 : 0.34,
              'bandpass', kind === 'perfect' ? 2100 : 1500, 1.1);
        tone(at, kind === 'perfect' ? 320 : 240, 70, 0.10, 0.30, 'sine');
        if (kind === 'perfect') {
            tone(at + 0.02, 1568, 1568, 0.16, 0.10, 'triangle'); // キラッ
        }
    }
    function sfxMiss() {
        if (!ctx) { return; }
        var at = ctx.currentTime + 0.001;
        tone(at, 180, 60, 0.28, 0.22, 'sawtooth');
    }
    function sfxFever() {
        if (!ctx) { return; }
        var at = ctx.currentTime + 0.001, sc = [523, 659, 784, 1047];
        for (var i = 0; i < sc.length; i++) {
            tone(at + i * 0.055, sc[i], sc[i], 0.20, 0.16, 'square');
        }
    }

    // --- BGM（1拍ずつスケジュール） ---
    // Am - F - C - G のループ。ルート音（Hz）
    var BASS = [110.00, 87.31, 130.81, 98.00];

    function scheduleBeat(beat, at) {
        if (!ctx) { return; }
        var inBar = beat % 4;
        var bar = Math.floor(beat / 4);
        var root = BASS[bar % BASS.length];
        var fever = songTime() < feverUntil;

        // キック
        if (inBar === 0 || inBar === 2) {
            tone(at, 150, 46, 0.16, 0.72, 'sine');
        }
        // クラップ
        if (inBar === 1 || inBar === 3) {
            noise(at, 0.13, 0.24, 'bandpass', 1800, 0.8);
        }
        // ハイハット（8分）
        noise(at, 0.03, 0.07, 'highpass', 7000);
        noise(at + beatSec() / 2, 0.03, 0.05, 'highpass', 7000);
        // ベース
        tone(at, root, root, beatSec() * 0.85, 0.20, 'triangle');
        // フィーバー中はアルペジオを重ねる
        if (fever) {
            tone(at, root * 4, root * 4, 0.12, 0.09, 'square');
            tone(at + beatSec() / 2, root * 6, root * 6, 0.12, 0.08, 'square');
        }
    }

    function beatSec() { return 60 / DIFFS[diffKey].bpm; }

    // ---------- 譜面生成（シード固定LCG） ----------
    function makeChart(key) {
        var cfg = DIFFS[key];
        var seed = cfg.seed >>> 0;
        var rnd = function () {
            seed = (seed * 1664525 + 1013904223) >>> 0;
            return seed / 4294967296;
        };
        var step = 60 / cfg.bpm / 2;    // 8分音符
        var steps = cfg.bars * 8;
        var list = [], prevLane = -1;

        for (var s = 0; s < steps; s++) {
            var t = LEAD_IN + s * step;
            var onBeat = (s % 2 === 0);
            // 表拍は出やすく、裏拍は控えめに
            var p = cfg.density * (onBeat ? 1.0 : 0.55);
            // 最初の1小節はウォームアップ、最後の1小節は締め
            if (s < 8) { p *= 0.5; }
            if (rnd() > p) { continue; }

            var lane = Math.floor(rnd() * LANES);
            if (lane === prevLane && rnd() < 0.6) { lane = (lane + 1 + Math.floor(rnd() * (LANES - 1))) % LANES; }
            prevLane = lane;
            list.push({ t: t, lane: lane, gold: (s % 32 === 0) });

            // 同時押し（HARDほど多い）
            if (onBeat && rnd() < cfg.chord) {
                var l2 = (lane + 1 + Math.floor(rnd() * (LANES - 1))) % LANES;
                list.push({ t: t, lane: l2, gold: false });
            }
        }
        list.sort(function (a, b) { return a.t - b.t; });
        return { notes: list, end: LEAD_IN + steps * step + 1.5 };
    }

    // ---------- レイアウト ----------
    function measure() {
        if (!stage) { return; }
        stageH = stage.clientHeight;
        hitPx = stageH * 0.78;
        var laneW = stage.clientWidth / LANES;
        noteH = laneW * 0.70;
    }

    // ---------- ゲーム進行 ----------
    function songTime() { return clock() - startTime; }

    function resetRun() {
        var chart = makeChart(diffKey);
        notes = chart.notes.map(function (n) {
            return { t: n.t, lane: n.lane, gold: n.gold, judged: false, el: null };
        });
        songEnd = chart.end;
        spawnIdx = 0;
        active.forEach(function (n) { if (n.el && n.el.parentNode) { n.el.parentNode.removeChild(n.el); } });
        active = [];
        stats = { perfect: 0, great: 0, good: 0, miss: 0 };
        hp = 100; combo = 0; maxCombo = 0; score = 0; feverUntil = -1; nextBeat = 0;
        setHp();
        scoreEl.textContent = '0';
        comboMaxEl.textContent = '0';
        comboEl.classList.remove('orb-on');
        setFever(false);
        measure();
    }

    function startCountdown() {
        initAudio();
        if (ctx && ctx.state === 'suspended') { ctx.resume(); }
        resetRun();
        titleOv.hidden = true;
        resultOv.hidden = true;
        state = 'count';
        var n = 3;
        countEl.hidden = false;
        countEl.innerHTML = '<span>' + n + '</span>';
        sfxSlap('good');
        var iv = setInterval(function () {
            n--;
            if (n > 0) {
                countEl.innerHTML = '<span>' + n + '</span>';
                sfxSlap('good');
            } else {
                clearInterval(iv);
                countEl.innerHTML = '<span>START!</span>';
                sfxSlap('perfect');
                setTimeout(function () { countEl.hidden = true; }, 450);
                beginPlay();
            }
        }, 700);
    }

    function beginPlay() {
        useAudioClock = !!(ctx && ctx.state === 'running');
        audioStart = ctx ? ctx.currentTime : 0;
        startTime = clock();
        state = 'play';
        if (rafId) { cancelAnimationFrame(rafId); }
        rafId = requestAnimationFrame(loop);
    }

    function loop() {
        rafId = requestAnimationFrame(loop);
        if (state !== 'play') { return; }
        var now = songTime();

        // BGMスケジュール
        if (ctx) {
            while (nextBeat * beatSec() < now + LOOKAHEAD) {
                var at = audioStart + nextBeat * beatSec();
                if (at > ctx.currentTime) { scheduleBeat(nextBeat, at); }
                nextBeat++;
            }
        }

        // ノーツ出現
        var travel = DIFFS[diffKey].travel;
        while (spawnIdx < notes.length && notes[spawnIdx].t - now <= travel) {
            spawn(notes[spawnIdx]);
            spawnIdx++;
        }

        // 位置更新 & 見逃し判定
        for (var i = active.length - 1; i >= 0; i--) {
            var n = active[i];
            var dt = n.t - now;
            if (!n.judged && dt < -W_GOOD) {
                n.judged = true;
                onMiss();
            }
            var prog = 1 - dt / travel;
            n.el.style.transform = 'translateY(' + (-noteH + prog * (hitPx + noteH / 2)) + 'px)';
            if (n.judged || dt < -0.55) {
                if (n.el.parentNode) { n.el.parentNode.removeChild(n.el); }
                active.splice(i, 1);
            }
        }

        // フィーバー終了
        if (feverUntil > 0 && now >= feverUntil) { setFever(false); feverUntil = -1; }

        // 終了判定
        if (hp <= 0) { finish(true); return; }
        if (now >= songEnd && active.length === 0 && spawnIdx >= notes.length) { finish(false); }
    }

    function spawn(n) {
        var el = document.createElement('div');
        el.className = 'orb-note' + (n.gold ? ' orb-note-gold' : '');
        el.textContent = '👋';
        el.style.transform = 'translateY(' + (-noteH) + 'px)';
        noteLayers[n.lane].appendChild(el);
        n.el = el;
        active.push(n);
    }

    // ---------- 入力・判定 ----------
    function hitLane(lane) {
        if (state !== 'play') { return; }
        flashPad(lane);
        var now = songTime(), best = null, bestAbs = 9;
        for (var i = 0; i < active.length; i++) {
            var n = active[i];
            if (n.lane !== lane || n.judged) { continue; }
            var abs = Math.abs(n.t - now);
            if (abs < bestAbs) { bestAbs = abs; best = n; }
        }
        if (!best || bestAbs > W_GOOD) { return; }   // 空打ちはノーペナルティ
        best.judged = true;

        var kind = bestAbs <= W_PERFECT ? 'perfect' : (bestAbs <= W_GREAT ? 'great' : 'good');
        stats[kind]++;
        combo++;
        if (combo > maxCombo) { maxCombo = combo; }

        var base = kind === 'perfect' ? 1000 : (kind === 'great' ? 600 : 250);
        var mult = songTime() < feverUntil ? 2 : 1;
        score += Math.round((base + Math.min(combo, 100) * 4) * mult);

        hp = Math.min(100, hp + (kind === 'perfect' ? 2 : kind === 'great' ? 1 : 0.5));
        setHp();
        scoreEl.textContent = score.toLocaleString('en-US');
        comboMaxEl.textContent = maxCombo;
        showJudge(kind);
        showCombo();
        slapFx(lane, kind);
        sfxSlap(kind);
        bounceChara();

        if (combo > 0 && combo % FEVER_COMBO === 0) {
            feverUntil = songTime() + FEVER_SEC;
            setFever(true);
            sfxFever();
        }
    }

    function onMiss() {
        stats.miss++;
        combo = 0;
        comboEl.classList.remove('orb-on');
        hp -= DIFFS[diffKey].hpMiss;
        if (hp < 0) { hp = 0; }
        setHp();
        if (feverUntil > 0) { feverUntil = -1; setFever(false); }
        showJudge('miss');
        sfxMiss();
    }

    // ---------- 表示 ----------
    function setHp() {
        hpFill.style.width = hp + '%';
        hpFill.classList.toggle('orb-hp-low', hp <= 35);
    }

    function showJudge(kind) {
        var txt = { perfect: 'PERFECT', great: 'GREAT', good: 'GOOD', miss: 'MISS' }[kind];
        judgeEl.className = 'orb-judge orb-j-' + kind;
        judgeEl.textContent = txt;
        void judgeEl.offsetWidth;
        judgeEl.classList.add('orb-pop');
    }

    function showCombo() {
        comboNumEl.textContent = combo;
        comboEl.classList.add('orb-on');
        comboEl.classList.remove('orb-beat');
        void comboEl.offsetWidth;
        comboEl.classList.add('orb-beat');
    }

    function setFever(on) {
        feverEl.classList.toggle('orb-on', on);
        stage.classList.toggle('orb-fevering', on);
    }

    function flashPad(lane) {
        var pad = padsEl.children[lane];
        if (!pad) { return; }
        pad.classList.add('orb-pad-hit');
        setTimeout(function () { pad.classList.remove('orb-pad-hit'); }, 90);
        var lane_ = lanesEl.children[lane];
        lane_.classList.remove('orb-lane-lit');
        void lane_.offsetWidth;
        lane_.classList.add('orb-lane-lit');
    }

    function slapFx(lane, kind) {
        var fx = document.createElement('div');
        fx.className = 'orb-fx';
        fx.textContent = kind === 'perfect'
            ? HIT_TEXT[Math.floor(Math.random() * HIT_TEXT.length)]
            : (kind === 'great' ? 'ペシッ' : 'ぺち');
        fx.style.left = ((lane + 0.5) * (100 / LANES)) + '%';
        fx.style.top = 'calc(var(--orb-hit-y) - 34px)';
        fx.style.fontSize = kind === 'perfect' ? '22px' : '16px';
        fx.style.color = kind === 'perfect' ? '#ff8fd0' : '#f5d878';
        fx.style.setProperty('--orb-fx-rot', (Math.random() * 16 - 8) + 'deg');
        stage.appendChild(fx);
        setTimeout(function () { if (fx.parentNode) { fx.parentNode.removeChild(fx); } }, 560);

        if (kind === 'perfect') {
            stage.classList.remove('orb-shake');
            void stage.offsetWidth;
            stage.classList.add('orb-shake');
        }
    }

    function bounceChara() {
        if (!chara) { return; }
        chara.classList.remove('orb-bounce');
        void chara.offsetWidth;
        chara.classList.add('orb-bounce');
    }

    // ---------- 終了・リザルト ----------
    function finish(ko) {
        state = 'result';
        setFever(false);
        active.forEach(function (n) { if (n.el && n.el.parentNode) { n.el.parentNode.removeChild(n.el); } });
        active = [];

        var total = notes.length || 1;
        var acc = (stats.perfect + stats.great * 0.65 + stats.good * 0.3) / total;
        var rank;
        if (ko) { rank = 'KO'; }
        else if (stats.perfect === total) { rank = 'SS'; }
        else if (acc >= 0.93) { rank = 'S'; }
        else if (acc >= 0.85) { rank = 'A'; }
        else if (acc >= 0.72) { rank = 'B'; }
        else if (acc >= 0.55) { rank = 'C'; }
        else { rank = 'D'; }

        var rankEl = $('orbRank');
        rankEl.textContent = rank;
        rankEl.className = 'orb-rank' + (rank === 'SS' || rank === 'S' ? ' orb-rank-s' : '')
                                      + (rank === 'D' || rank === 'KO' ? ' orb-rank-d' : '');
        $('orbResultTitle').textContent = ko ? 'まいきー ダウン…' : 'ステージクリア！';
        $('orbResScore').textContent = score.toLocaleString('en-US');
        $('orbResCombo').textContent = maxCombo;
        $('orbResAcc').textContent = (acc * 100).toFixed(1) + '%';
        $('orbResPerfect').textContent = stats.perfect;
        $('orbResGreat').textContent = stats.great;
        $('orbResGood').textContent = stats.good;
        $('orbResMiss').textContent = stats.miss;
        $('orbResDiff').textContent = DIFFS[diffKey].label;

        var best = loadBest();
        var prev = best[diffKey] || 0;
        if (score > prev) {
            best[diffKey] = score;
            saveBest(best);
            $('orbBest').textContent = '★ ハイスコア更新！ (旧: ' + prev.toLocaleString('en-US') + ')';
        } else {
            $('orbBest').textContent = 'ベスト: ' + prev.toLocaleString('en-US');
        }
        resultOv.hidden = false;
    }

    function loadBest() {
        try { return JSON.parse(localStorage.getItem(BEST_KEY) || '{}') || {}; }
        catch (e) { return {}; }
    }
    function saveBest(o) {
        try { localStorage.setItem(BEST_KEY, JSON.stringify(o)); } catch (e) { /* 保存不可でも続行 */ }
    }

    // ---------- ポーズ ----------
    function togglePause() {
        if (state === 'play') {
            state = 'pause';
            pauseMark = clock();
            audioPauseMark = ctx ? ctx.currentTime : 0;
            if (master) { master.gain.value = 0; }
            pauseOv.hidden = false;
        } else if (state === 'pause') {
            startTime += clock() - pauseMark;   // 停止中の経過分だけ基準をずらす
            if (ctx) { audioStart += ctx.currentTime - audioPauseMark; }
            if (master) { master.gain.value = muted ? 0 : 0.9; }
            pauseOv.hidden = true;
            state = 'play';
        }
    }

    function backToTitle() {
        state = 'title';
        if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
        active.forEach(function (n) { if (n.el && n.el.parentNode) { n.el.parentNode.removeChild(n.el); } });
        active = [];
        setFever(false);
        if (master) { master.gain.value = muted ? 0 : 0.9; }
        pauseOv.hidden = true;
        resultOv.hidden = true;
        countEl.hidden = true;
        titleOv.hidden = false;
        showBestOnTitle();   // 直前のプレイで更新されたベストを反映する
    }

    // ---------- 初期化 ----------
    function buildStage() {
        for (var i = 0; i < LANES; i++) {
            var lane = document.createElement('div');
            lane.className = 'orb-lane';
            lanesEl.appendChild(lane);
            noteLayers.push(lane);

            var pad = document.createElement('div');
            pad.className = 'orb-pad';
            pad.innerHTML = '👋<span class="orb-pad-key">' + ['D', 'F', 'J', 'K'][i] + '</span>';
            pad.dataset.lane = i;
            padsEl.appendChild(pad);
        }
        // フィーバー時の光の雨
        for (var r = 0; r < 24; r++) {
            var sp = document.createElement('span');
            sp.style.left = (Math.random() * 100) + '%';
            sp.style.animationDuration = (0.7 + Math.random() * 0.8) + 's';
            sp.style.animationDelay = (-Math.random() * 1.5) + 's';
            rainEl.appendChild(sp);
        }
    }

    function bindInput() {
        // キーボード
        var held = {};
        document.addEventListener('keydown', function (e) {
            if (e.code === 'Escape' && (state === 'play' || state === 'pause')) {
                e.preventDefault(); togglePause(); return;
            }
            if (e.code === 'Space' && state === 'title') { e.preventDefault(); startCountdown(); return; }
            var lane = KEYMAP[e.code];
            if (lane === undefined || held[e.code]) { return; }
            held[e.code] = true;
            e.preventDefault();
            hitLane(lane);
        });
        document.addEventListener('keyup', function (e) { delete held[e.code]; });

        // タッチ / クリック（レーン全体をタップ可能にする）
        var down = function (e) {
            if (state !== 'play') { return; }
            var rect = stage.getBoundingClientRect();
            var pts = e.changedTouches ? e.changedTouches : [e];
            for (var i = 0; i < pts.length; i++) {
                var x = pts[i].clientX - rect.left;
                var lane = Math.max(0, Math.min(LANES - 1, Math.floor(x / (rect.width / LANES))));
                hitLane(lane);
            }
            e.preventDefault();
        };
        stage.addEventListener('touchstart', down, { passive: false });
        stage.addEventListener('mousedown', function (e) {
            if (e.target.closest('.orb-overlay, .orb-btn-icon, .orb-mute')) { return; }
            down(e);
        });
    }

    function init() {
        stage = $('orbStage');
        if (!stage) { return; }
        lanesEl = $('orbLanes');
        padsEl = $('orbPads');
        chara = $('orbChara');
        judgeEl = $('orbJudge');
        comboEl = $('orbCombo');
        comboNumEl = $('orbComboNum');
        feverEl = $('orbFever');
        hpFill = $('orbHpFill');
        scoreEl = $('orbScore');
        comboMaxEl = $('orbMaxCombo');
        titleOv = $('orbTitleOv');
        pauseOv = $('orbPauseOv');
        resultOv = $('orbResultOv');
        countEl = $('orbCount');
        muteBtn = $('orbMute');
        pauseBtn = $('orbPause');
        rainEl = $('orbRain');

        buildStage();
        bindInput();
        measure();
        window.addEventListener('resize', measure);

        // 難易度選択
        Array.prototype.forEach.call(document.querySelectorAll('.orb-diff'), function (b) {
            b.addEventListener('click', function () {
                diffKey = b.dataset.diff;
                document.querySelectorAll('.orb-diff').forEach(function (x) { x.classList.remove('orb-selected'); });
                b.classList.add('orb-selected');
                showBestOnTitle();
            });
        });

        $('orbStart').addEventListener('click', startCountdown);
        $('orbRetry').addEventListener('click', startCountdown);
        $('orbResultBack').addEventListener('click', backToTitle);
        $('orbResume').addEventListener('click', togglePause);
        $('orbQuit').addEventListener('click', backToTitle);
        pauseBtn.addEventListener('click', togglePause);
        muteBtn.addEventListener('click', function () {
            muted = !muted;
            if (master) { master.gain.value = muted ? 0 : 0.9; }
            muteBtn.textContent = muted ? '🔇' : '🔊';
        });

        showBestOnTitle();
    }

    function showBestOnTitle() {
        var best = loadBest()[diffKey] || 0;
        $('orbTitleBest').textContent = best ? ('ベストスコア: ' + best.toLocaleString('en-US')) : 'まだ記録なし';
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
