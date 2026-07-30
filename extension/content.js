/* HealthLens content script
 * Detects a YouTube watch page, asks the backend to analyze it, and shows supporting and
 * opposing evidence side by side in a right-hand panel. Shadow DOM keeps YouTube's CSS out.
 *
 * Design rules (stick to them): ink plus a single accent, three font sizes (15/12.5/11),
 * no emoji (line icons only), no pastel boxes — hierarchy comes from spacing and hairlines,
 * color only when it carries meaning. Supporting vs. opposing is signalled by label and
 * position, never by color, and both get equal visual weight.
 */
(() => {
  "use strict";
  const BACKEND = "http://localhost:8000";
  const HOST_ID = "healthlens-host";
  let lastVideoId = null;
  let REF = null;          // Taxonomy from the backend (evidence hierarchy, journal tiers). Used by the tooltip.
  let tipEl = null;        // Hover tooltip popover, mounted fixed on the shadow root outside .wrap
  let hideTimer = null;

  // Monochrome line icons that inherit currentColor. Used instead of emoji.
  const IC = {
    lens: `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="6.8" cy="6.8" r="4.1"/><path d="M9.9 9.9 14 14"/></svg>`,
    x:    `<svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8"/></svg>`,
    up:   `<svg viewBox="0 0 14 14" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M7 11V3M3.5 6.5 7 3l3.5 3.5"/></svg>`,
    down: `<svg viewBox="0 0 14 14" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M7 3v8M3.5 7.5 7 11l3.5-3.5"/></svg>`,
    chev: `<svg class="cv" viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6l4 4 4-4"/></svg>`,
  };

  const CSS = `
  :host { all: initial; }
  :host {
    --ink:#17181c; --muted:#63666d; --faint:#9a9da4; --line:#ececed; --line2:#f4f4f5;
    --accent:#2f6bff; --accent-wash:#f2f6ff; --accent-line:#d4e0fb;
    --caution:#a65a12; --caution-line:#e7cfa6;
    --bg:#ffffff; --fs-title:15px; --fs-body:12.5px; --fs-cap:11px;
    font-family:-apple-system, BlinkMacSystemFont, "Pretendard", "Noto Sans KR", system-ui, sans-serif;
  }
  .wrap { position: fixed; top: 72px; right: 20px; width: 344px; max-height: 82vh;
    overflow-y: auto; z-index: 2147483000; color: var(--ink); background: var(--bg);
    border: 1px solid var(--line); border-radius: 16px;
    box-shadow: 0 12px 40px rgba(20,22,28,.12), 0 2px 6px rgba(20,22,28,.05);
    font-size: var(--fs-body); line-height: 1.55; -webkit-font-smoothing: antialiased; }
  .wrap::-webkit-scrollbar { width: 10px; }
  .wrap::-webkit-scrollbar-thumb { background: #e2e2e4; border: 3px solid var(--bg); border-radius: 8px; }

  .hd { display:flex; align-items:center; justify-content:space-between;
    padding: 15px 16px 13px; position: sticky; top: 0; background: var(--bg);
    border-bottom: 1px solid var(--line); border-radius: 16px 16px 0 0; z-index: 3; }
  .brand { display:flex; align-items:center; gap: 7px; font-size: var(--fs-title);
    font-weight: 650; letter-spacing: -.3px; }
  .brand svg { color: var(--accent); }
  .x { border:0; background:transparent; color: var(--faint); cursor:pointer;
    width:26px; height:26px; border-radius:8px; display:grid; place-items:center; padding:0; }
  .x:hover { background: var(--line2); color: var(--ink); }

  .body { padding: 2px 16px 16px; }

  .claim { padding: 15px 0 4px; }
  .claim + .claim { border-top: 1px solid var(--line); margin-top: 4px; }
  .meta { display:flex; align-items:center; gap: 7px; font-size: var(--fs-cap);
    color: var(--faint); letter-spacing:.1px; margin-bottom: 9px; }
  .meta .dot { width:2.5px; height:2.5px; border-radius:50%; background: currentColor; }
  .klabel { font-size: var(--fs-cap); font-weight: 650; color: var(--accent);
    letter-spacing:.2px; margin-bottom: 5px; }
  .statement { font-size: var(--fs-title); font-weight: 620; line-height: 1.5;
    letter-spacing: -.2px; color: var(--ink); }
  .snote { margin-top: 6px; font-size: var(--fs-cap); color: var(--faint); line-height: 1.5; }
  .snote.cau { color: var(--caution); }

  .vlogic { margin-top: 14px; }
  .vlogic p { margin: 0; color: var(--ink); }
  .vsrc { margin-top: 7px; font-size: var(--fs-cap); color: var(--muted); line-height: 1.55; }
  .vnote { color: var(--faint); margin-top: 3px; }

  .ev { margin-top: 22px; }
  .ev-h { display:flex; align-items:center; gap: 8px; padding-bottom: 9px; margin-bottom: 2px;
    border-bottom: 1px solid var(--line); }
  .ev-h .ic { flex:0 0 auto; width: 20px; height: 20px; display:grid; place-items:center;
    border: 1px solid var(--accent-line); border-radius: 6px; color: var(--accent); }
  .ev-h .k { font-size: var(--fs-body); font-weight: 680; letter-spacing: -.1px; color: var(--accent); }
  .ev-h .n { margin-left: auto; font-size: var(--fs-cap); color: var(--faint);
    font-variant-numeric: tabular-nums; }

  .item { padding: 12px 0; border-top: 1px solid var(--line); }
  .ev-h + .item, .ev-h + .none { border-top: 0; }
  .item .sum { color: var(--ink); }
  .item .tags { margin-top: 6px; display:flex; flex-wrap:wrap; gap: 4px 12px; }
  .item .cite { margin-top: 4px; font-size: var(--fs-cap); color: var(--faint); }
  .item .cite a { color: var(--muted); text-decoration: none;
    border-bottom: 1px solid var(--line); }
  .item .cite a:hover { border-bottom-color: var(--muted); }
  .none { padding: 9px 0 2px; font-size: var(--fs-body); color: var(--faint); line-height: 1.6; }

  /* Evidence-level and journal-tier badges: quiet dotted-underline text, not filled pills. Anchors the hover tooltip. */
  .badge { font-size: var(--fs-cap); color: var(--accent); cursor: help;
    border-bottom: 1px dotted #a9c4f5; padding-bottom: 1px; }
  .badge.warn { color: var(--caution); border-bottom-color: var(--caution-line); }

  .more { margin-top: 14px; border-top: 1px solid var(--line); }
  .more-btn { width:100%; display:flex; align-items:center; justify-content:space-between;
    gap: 8px; background:transparent; border:0; cursor:pointer; padding: 11px 0 3px;
    font-size: var(--fs-cap); font-weight: 650; letter-spacing:.2px; color: var(--muted); }
  .more-btn:hover { color: var(--ink); }
  .more-btn .cv { color: var(--faint); transition: transform .18s ease; }
  .more.open .more-btn .cv { transform: rotate(180deg); }
  .more-body { display:none; padding-bottom: 4px; }
  .more.open .more-body { display:block; }
  .qlist { margin: 6px 0 0; padding: 0; list-style: none; }
  .qlist li { position: relative; padding-left: 14px; margin-bottom: 7px; color: var(--muted); }
  .qlist li::before { content:""; position:absolute; left:2px; top:8px; width:4px; height:4px;
    border-radius:50%; background: var(--faint); }
  .guide { margin: 10px 0 0; font-size: var(--fs-cap); color: var(--faint); line-height: 1.55; }

  .disc { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--line);
    font-size: var(--fs-cap); color: var(--faint); line-height: 1.5; }
  .state { padding: 26px 18px; text-align:center; color: var(--muted); line-height: 1.65; }
  .state .sub { display:block; margin-top: 5px; font-size: var(--fs-cap); color: var(--faint); }
  .pulse { display:inline-block; width:6px; height:6px; border-radius:50%; background: var(--accent);
    margin-right: 8px; vertical-align: 1px; animation: hlp 1.1s ease-in-out infinite; }
  @keyframes hlp { 0%,100% { opacity:.3; transform:scale(.8);} 50% { opacity:1; transform:scale(1);} }

  /* ── Badge hover tooltip: shows the whole strong→weak hierarchy with the current item highlighted ── */
  .hl-tip { position: fixed; z-index: 2147483001; width: 286px; max-height: 78vh; overflow-y: auto;
    background: var(--bg); color: var(--ink); border: 1px solid var(--line); border-radius: 12px;
    box-shadow: 0 14px 44px rgba(20,22,28,.16); padding: 13px 14px 11px; display: none;
    font-family: inherit; font-size: var(--fs-cap); line-height: 1.5; }
  .hl-tip::-webkit-scrollbar { width: 9px; }
  .hl-tip::-webkit-scrollbar-thumb { background: #e2e2e4; border: 3px solid var(--bg); border-radius: 8px; }
  .hl-tip .tip-hd { font-size: var(--fs-body); font-weight: 650; letter-spacing: -.2px; }
  .hl-tip .tip-sub { font-size: var(--fs-cap); color: var(--muted); margin: 4px 0 9px; line-height: 1.45; }
  .hl-tip .tip-row { display:flex; gap: 9px; padding: 7px 4px 7px 9px; border-radius: 0 7px 7px 0;
    border-left: 2px solid rgba(23,24,28, calc(.82 - var(--i) * .70)); }
  .hl-tip .tip-row.cur { border-left-color: var(--accent); background: var(--accent-wash); }
  .hl-tip .tip-rank { flex: 0 0 auto; width: 13px; text-align: right; color: var(--faint);
    font-weight: 650; font-variant-numeric: tabular-nums; padding-top: 1px; }
  .hl-tip .tip-row.cur .tip-rank { color: var(--accent); }
  .hl-tip .tip-lb { font-size: var(--fs-body); font-weight: 620; color: var(--ink); }
  .hl-tip .tip-row.cur .tip-lb { color: var(--accent); }
  .hl-tip .tip-why { color: var(--muted); margin-top: 2px; }
  `;

  function getVideoId() {
    if (location.pathname !== "/watch") return null;
    return new URLSearchParams(location.search).get("v");
  }

  function getTitle() {
    const h1 = document.querySelector("h1.ytd-watch-metadata, h1.title");
    return (h1 && h1.textContent.trim()) || document.title.replace(" - YouTube", "").trim();
  }

  function ensureHost() {
    let host = document.getElementById(HOST_ID);
    if (host) return host.shadowRoot;
    host = document.createElement("div");
    host.id = HOST_ID;
    document.body.appendChild(host);
    const root = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = CSS;
    root.appendChild(style);
    const wrap = document.createElement("div");
    wrap.className = "wrap";
    wrap.innerHTML = `
      <div class="hd">
        <div class="brand">${IC.lens}<span>HealthLens</span></div>
        <button class="x" title="닫기">${IC.x}</button>
      </div>
      <div class="body"><div class="state"><span class="pulse"></span>건강 주장을 살펴보는 중…</div></div>`;
    root.appendChild(wrap);
    wrap.querySelector(".x").addEventListener("click", () => host.remove());
    // Badge tooltips and the collapse toggle are delegated to wrap, since .body is redrawn every time.
    wrap.addEventListener("mouseover", onWrapOver);
    wrap.addEventListener("mouseout", onWrapOut);
    wrap.addEventListener("click", onWrapClick);
    return root;
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  function badge(kind, code, label) {
    const warn = kind === "tier" && ["T4", "NA"].includes(code) ? " warn" : "";
    return `<span class="badge${warn}" data-kind="${kind}" data-code="${esc(code)}">${esc(label)}</span>`;
  }

  function itemHTML(c) {
    const cite = c.cite || c.citation || "";
    const citeHtml = c.url
      ? `<div class="cite"><a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(cite || "출처 보기")}</a></div>`
      : (cite ? `<div class="cite">${esc(cite)}</div>` : "");
    return `<div class="item">
      <div class="sum">${esc(c.summary)}</div>
      <div class="tags">
        ${badge("ev", c.evidenceLevel.code, c.evidenceLevel.label)}
        ${badge("tier", c.journalTier.code, "학술지 " + c.journalTier.label)}
      </div>
      ${citeHtml}
    </div>`;
  }

  function evSection(icon, title, items, emptyMsg) {
    const body = items.length
      ? items.map(itemHTML).join("")
      : `<div class="none">${esc(emptyMsg)}</div>`;
    const count = items.length ? `<span class="n">${items.length}</span>` : "";
    return `<section class="ev">
      <div class="ev-h"><span class="ic">${icon}</span><span class="k">${esc(title)}</span>${count}</div>
      ${body}
    </section>`;
  }

  function claimHTML(cl) {
    // The curated seed DB has not been reviewed by an expert yet (curated_db.json _meta.reviewed_by=null).
    // Never put a "reviewed" label on unreviewed medical content, so no badge.
    const srcTag = cl.source === "curated" ? "" : "실시간 검색";
    const ve = cl.videoEvidence;
    const veHtml = ve
      ? `<div class="vsrc">영상이 든 근거 · ${badge("ev", ve.level.code, ve.level.label)}${
          ve.journalTier ? " · " + badge("tier", ve.journalTier.code, "학술지 " + ve.journalTier.label) : ""}${
          ve.note ? `<div class="vnote">${esc(ve.note)}${ve.citedSource ? " · 인용 " + esc(ve.citedSource) : ""}</div>` : ""}</div>`
      : "";
    const vlogic = (cl.rationale || ve)
      ? `<div class="vlogic"><div class="klabel">영상의 논리</div>${
          cl.rationale ? `<p>${esc(cl.rationale)}</p>` : ""}${veHtml}</div>`
      : "";

    const sup = evSection(IC.up, "뒷받침하는 근거", cl.supporting,
      "정리된 지지 근거 없음.");
    const opp = evSection(IC.down, "반박·상충하는 근거", cl.opposing,
      "이 주장에 반하는 근거가 두드러지지 않았습니다. 자금 출처와 독립 재현 여부를 함께 보세요.");

    const prompts = (cl.thinkingPrompts || []).map((p) => `<li>${esc(p)}</li>`).join("");
    const guide = cl.evidenceGuide ? `<p class="guide">${esc(cl.evidenceGuide)}</p>` : "";
    const more = prompts
      ? `<div class="more">
           <button class="more-btn">함께 따져볼 질문 ${cl.thinkingPrompts.length}${IC.chev}</button>
           <div class="more-body"><ul class="qlist">${prompts}</ul>${guide}</div>
         </div>`
      : "";

    const noTx = cl.transcriptMissing;
    const mixed = cl.videoStance === "MIXED";
    const claimLabel = noTx ? "제목이 시사하는 주제"
      : (mixed ? "이 영상이 다루는 쟁점" : "이 영상의 주장");
    const stanceNote = noTx
      ? `<div class="snote cau">자막을 가져오지 못해 영상 내용은 확인하지 못했습니다. 아래는 이 주제에 대한 학술 근거입니다.</div>`
      : (mixed ? `<div class="snote">영상은 이 쟁점을 한쪽으로 단정하지 않고 양면적으로 다룹니다.</div>` : "");
    return `<div class="claim">
      <div class="meta">${esc(cl.categoryLabel)}${srcTag ? `<span class="dot"></span>${srcTag}` : ""}</div>
      <div class="klabel">${claimLabel}</div>
      <div class="statement">${esc(cl.statement)}</div>
      ${stanceNote}
      ${vlogic}
      ${sup}
      ${opp}
      ${more}
    </div>`;
  }

  function render(root, data) {
    if (data.reference) REF = data.reference;   // Keep the taxonomy the tooltip renders
    const body = root.querySelector(".body");
    if (!data.hasHealthClaim) {
      body.innerHTML = `<div class="state">검증할 건강 주장을 찾지 못했습니다.</div>`;
      return;
    }
    if (!data.claims || !data.claims.length) {
      body.innerHTML = `<div class="state">${esc(data.note || "건강 관련 내용은 있으나 주장을 정리하지 못했습니다.")}</div>`;
      return;
    }
    body.innerHTML = data.claims.map(claimHTML).join("") +
      (data.disclaimer ? `<div class="disc">${esc(data.disclaimer)}</div>` : "");
  }

  // ── Badge hover tooltip ─────────────────────────────────────────────
  function ensureTip(root) {
    if (tipEl && tipEl.isConnected) return tipEl;
    tipEl = document.createElement("div");
    tipEl.className = "hl-tip";
    tipEl.addEventListener("mouseenter", cancelHide);   // Stay open so a long tooltip can be scrolled
    tipEl.addEventListener("mouseleave", scheduleHide);
    root.appendChild(tipEl);   // Outside .wrap, on the shadow root, to avoid overflow clipping
    return tipEl;
  }

  function hideTip() { if (tipEl) tipEl.style.display = "none"; }
  function cancelHide() { clearTimeout(hideTimer); }
  function scheduleHide() { clearTimeout(hideTimer); hideTimer = setTimeout(hideTip, 120); }

  function onWrapOver(e) {
    const b = e.target.closest && e.target.closest("[data-kind]");
    if (!b) return;
    cancelHide();
    showTip(b);
  }
  function onWrapOut(e) {
    const b = e.target.closest && e.target.closest("[data-kind]");
    if (!b || b.contains(e.relatedTarget)) return;
    scheduleHide();
  }
  function onWrapClick(e) {
    const btn = e.target.closest && e.target.closest(".more-btn");
    if (!btn) return;
    const more = btn.closest(".more");
    if (more) more.classList.toggle("open");
  }

  function showTip(b) {
    if (!REF) return;
    const kind = b.dataset.kind; // "ev" | "tier"
    const list = kind === "ev" ? REF.evidenceLevels : REF.journalTiers;
    if (!list || !list.length) return;
    const tip = ensureTip(b.getRootNode());
    tip.innerHTML = tipHTML(kind, b.dataset.code, list);
    tip.style.display = "block";
    positionTip(tip, b);
  }

  function tipHTML(kind, code, list) {
    const head = kind === "ev"
      ? { t: "근거의 위계 · 강함 → 약함",
          s: "위로 갈수록 인과를 강하게 뒷받침합니다. 단 '유형이 강하다'가 '이 주장이 옳다'는 뜻은 아닙니다." }
      : { t: "학술지 tier · 심사 엄격도",
          s: "tier는 '논문이 옳다'가 아니라 '출판 심사가 얼마나 엄격했나'를 뜻합니다." };
    const n = list.length;
    const rows = list.map((it, i) => {
      const cur = it.code === code ? " cur" : "";
      const rank = kind === "ev" ? (it.rank || i + 1) : i + 1;
      const weak = n > 1 ? i / (n - 1) : 0;   // 0 (strong) → 1 (weak): fades the left rule
      return `<div class="tip-row${cur}" style="--i:${weak.toFixed(3)}">
        <div class="tip-rank">${rank}</div>
        <div class="tip-main">
          <div class="tip-lb">${esc(it.label)}</div>
          <div class="tip-why">${esc(it.why || it.desc || "")}</div>
        </div>
      </div>`;
    }).join("");
    return `<div class="tip-hd">${esc(head.t)}</div><div class="tip-sub">${esc(head.s)}</div>${rows}`;
  }

  function positionTip(tip, b) {
    const r = b.getBoundingClientRect();
    const gap = 10, margin = 8;
    tip.style.left = "0px"; tip.style.top = "0px";   // Settle the measurement
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let left = r.left - gap - tw;   // Panel sits on the right, so show the tip left of the badge
    let top;
    if (left < margin) {            // No room on the left, drop it below the badge
      left = Math.max(margin, Math.min(r.left, window.innerWidth - tw - margin));
      top = r.bottom + gap;
    } else {
      top = r.top - 4;
    }
    top = Math.max(margin, Math.min(top, window.innerHeight - th - margin)); // Clamp vertically
    tip.style.left = Math.round(left) + "px";
    tip.style.top = Math.round(top) + "px";
  }

  // ── Transcript fetching. Runs only in the user's own browser session; the server never touches YouTube ──
  // Pull JSON out of an inline script by matching braces
  function extractJsonAfter(text, marker) {
    const i = text.indexOf(marker);
    if (i < 0) return null;
    const s = text.indexOf("{", i);
    if (s < 0) return null;
    let depth = 0, inStr = false, esc = false;
    for (let j = s; j < text.length; j++) {
      const ch = text[j];
      if (inStr) {
        if (esc) esc = false;
        else if (ch === "\\") esc = true;
        else if (ch === '"') inStr = false;
      } else if (ch === '"') inStr = true;
      else if (ch === "{") depth++;
      else if (ch === "}") { depth--; if (depth === 0) return text.slice(s, j + 1); }
    }
    return null;
  }

  function tracksFromPR(pr) {
    const r = pr && pr.captions && pr.captions.playerCaptionsTracklistRenderer;
    return (r && r.captionTracks) || null;
  }

  function playerResponseFromDOM() {
    for (const sc of document.querySelectorAll("script")) {
      const t = sc.textContent;
      if (t && t.includes("ytInitialPlayerResponse")) {
        const j = extractJsonAfter(t, "ytInitialPlayerResponse");
        if (j) { try { return JSON.parse(j); } catch (_) {} }
      }
    }
    return null;
  }

  async function playerResponseByFetch(videoId) {
    try {
      const html = await (await fetch(`/watch?v=${videoId}`, { credentials: "include" })).text();
      const j = extractJsonAfter(html, "ytInitialPlayerResponse");
      return j ? JSON.parse(j) : null;
    } catch (_) { return null; }
  }

  // Dig the InnerTube API key and client version out of the page scripts
  function ytCfg() {
    let key, ver;
    for (const sc of document.querySelectorAll("script")) {
      const t = sc.textContent;
      if (!t || t.indexOf("INNERTUBE_API_KEY") < 0) continue;
      key = (t.match(/"INNERTUBE_API_KEY":"([^"]+)"/) || [])[1];
      ver = (t.match(/"INNERTUBE_CLIENT_VERSION":"([^"]+)"/) || [])[1];
      if (key) break;
    }
    return { key, ver: ver || "2.20240101.00.00" };
  }

  // InnerTube player API — reliably returns auto-generated (ASR) captions too, on the user's session
  async function tracksFromInnerTube(videoId) {
    try {
      const { key, ver } = ytCfg();
      if (!key) return null;
      const res = await fetch(`/youtubei/v1/player?key=${key}`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          videoId,
          context: { client: { clientName: "WEB", clientVersion: ver, hl: "ko", gl: "KR" } },
        }),
      });
      return tracksFromPR(await res.json());
    } catch (_) { return null; }
  }

  function pickTrack(tracks) {
    const find = (code, asr) => tracks.find(
      (t) => t.languageCode === code && (t.kind === "asr") === asr);
    // Manual ko > auto ko > manual en > auto en > whatever comes first
    return find("ko", false) || find("ko", true)
        || find("en", false) || find("en", true) || tracks[0];
  }

  async function fetchTrackText(track) {
    let url = track.baseUrl + "&fmt=json3";
    // If the source language isn't Korean or English, ask for a Korean translation
    if (track.languageCode !== "ko" && track.languageCode !== "en") url += "&tlang=ko";
    const data = await (await fetch(url, { credentials: "include" })).json();
    return (data.events || [])
      .flatMap((e) => (e.segs || []).map((s) => s.utf8 || ""))
      .join("").replace(/\s+/g, " ").trim();
  }

  function segmentsFromPanel() {
    const segs = document.querySelectorAll("ytd-transcript-segment-renderer .segment-text");
    if (!segs.length) return null;
    return Array.from(segs).map((s) => s.textContent.trim()).join(" ").trim() || null;
  }

  async function getTranscript(videoId) {
    // Track list: DOM first, then InnerTube (includes ASR), then /watch
    const tracks = tracksFromPR(playerResponseFromDOM())
      || (await tracksFromInnerTube(videoId))
      || tracksFromPR(await playerResponseByFetch(videoId));
    if (tracks && tracks.length) {
      try {
        const text = await fetchTrackText(pickTrack(tracks));
        if (text.length > 40) return text;
      } catch (_) {}
    }
    return segmentsFromPanel(); // Last resort: scrape the open transcript panel
  }

  async function analyze(videoId) {
    const root = ensureHost();
    root.querySelector(".body").innerHTML =
      `<div class="state"><span class="pulse"></span>건강 주장을 살펴보는 중…</div>`;
    try {
      const transcript = await getTranscript(videoId).catch(() => null);
      const res = await fetch(`${BACKEND}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ videoId, title: getTitle(), transcript }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      render(root, await res.json());
    } catch (e) {
      root.querySelector(".body").innerHTML =
        `<div class="state">백엔드에 연결하지 못했습니다.<span class="sub">로컬 서버를 실행한 뒤 다시 시도하세요. (${esc(e.message)})</span></div>`;
    }
  }

  function onNav() {
    const id = getVideoId();
    if (!id || id === lastVideoId) return;
    lastVideoId = id;
    // Give the title and DOM a moment to settle after a new video loads
    setTimeout(() => analyze(id), 1200);
  }

  // Initial load plus SPA navigation
  window.addEventListener("yt-navigate-finish", onNav);
  window.addEventListener("popstate", onNav);
  setInterval(onNav, 2000); // Safety net in case the yt events are missed
  onNav();
})();
