/* SpartaGen — single page UI (no build step, no dependencies). */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtT = (t) => { t = Math.max(0, +t || 0); const m = Math.floor(t / 60); return `${m}:${(t - m * 60).toFixed(2).padStart(5, "0")}`; };

const S = {
  status: null, project: null, bank: null, arr: null, catalog: null, variants: null,
  dirty: false, busy: false, variant: "unextended",
};

// ── API helpers ──────────────────────────────────────────────────────────────
async function api(path, opts = {}) {
  const init = { method: opts.method || (opts.body !== undefined ? "POST" : "GET"), headers: {} };
  if (opts.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, init);
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (!res.ok || (data && data.error)) throw new Error((data && data.error) || `${res.status} ${res.statusText}`);
  return data;
}

function toast(msg, ok = false) {
  const el = document.createElement("div");
  if (ok) el.className = "ok";
  el.textContent = msg;
  $("#toast").appendChild(el);
  setTimeout(() => el.remove(), ok ? 3500 : 7000);
}

function setBusy(on) {
  S.busy = on;
  $$("button[data-heavy]").forEach((b) => (b.disabled = on));
}

async function runJob(startPath, body, label) {
  if (S.busy) { toast("Another job is still running."); return null; }
  setBusy(true);
  const bar = $("#jobbar");
  bar.classList.remove("hidden");
  $("#job-kind").textContent = label;
  $("#job-msg").textContent = "starting…";
  $("#job-progress").style.width = "0%";
  try {
    let job = await api(startPath, { body: body || {} });
    while (job.status === "running") {
      await new Promise((r) => setTimeout(r, 450));
      job = await api(`/api/job/${job.id}`);
      $("#job-msg").textContent = `${job.message} · ${Math.round(job.progress * 100)}% · ${job.elapsed}s`;
      $("#job-progress").style.width = `${Math.round(job.progress * 100)}%`;
    }
    if (job.status === "error") throw new Error(job.error);
    toast(`${label} finished in ${job.elapsed}s`, true);
    return job.result;
  } catch (e) {
    toast(`${label} failed: ${e.message}`);
    return null;
  } finally {
    setBusy(false);
    setTimeout(() => bar.classList.add("hidden"), 600);
  }
}

// ── navigation ───────────────────────────────────────────────────────────────
function go(step) {
  $$("#steps button").forEach((b) => b.classList.toggle("active", b.dataset.step === step));
  $$(".step").forEach((s) => s.classList.toggle("active", s.id === `step-${step}`));
  if (step === "remix" && !S.arr) loadArrangement();
  window.scrollTo({ top: 0, behavior: "smooth" });
}
$$("#steps button").forEach((b) => b.addEventListener("click", () => go(b.dataset.step)));

// ── status / project ─────────────────────────────────────────────────────────
function renderStatus() {
  const st = S.status;
  if (!st) return;
  const pill = (ok, txt) => `<span class="pill ${ok ? "ok" : "bad"}">${txt}</span>`;
  $("#status").innerHTML = pill(st.ffmpeg, "ffmpeg") + pill(st.yt_dlp, "yt-dlp") + pill(st.scipy, "scipy") +
    `<span class="pill">v${esc(st.version)}</span>`;
  if (!st.ffmpeg) toast("ffmpeg was not found — install it (or pip install imageio-ffmpeg) and restart.");
}

function renderProject() {
  const p = S.project;
  if (!p) return;
  $("#proj-name").value = p.name || "";
  const box = $("#source-info");
  const vid = $("#source-video");
  if (p.source) {
    const s = p.source;
    box.innerHTML = `<b>${esc(s.name)}</b><br>${fmtT(s.duration)} · ${s.has_video ? `${s.width}×${s.height} @ ${(+s.fps).toFixed(2)} fps` : "audio only"}
      · ${s.audio_rate} Hz ${s.audio_channels === 1 ? "mono" : "stereo"}`;
    if (s.has_video && s.url && vid.dataset.src !== s.url) {
      vid.src = s.url; vid.dataset.src = s.url; vid.classList.remove("hidden");
    }
    if (!s.has_video) vid.classList.add("hidden");
    $("#btn-analyze").disabled = false;
    $("#btn-analyze").textContent = p.analyzed ? "Re-open samples" : "Detect samples (step by step)";
    $("#btn-auto").disabled = false;
  } else {
    box.textContent = "Nothing loaded yet.";
    vid.classList.add("hidden");
    $("#btn-analyze").disabled = true;
    $("#btn-auto").disabled = true;
  }
  S.variant = p.variant || "unextended";
  const o = p.options || {};
  $("#opt-title").value = o.title || "";
  // On a base, "minor" follows the base's own key chord unless the user set it.
  $("#opt-minor").checked = o.minor ?? !!(p.base && p.base.minor);
  $("#opt-chorus-pitch").checked = !!o.chorus_pitch;
  const cfg = p.samples_config || {};
  $("#cfg-key").value = cfg.key || "D";
  $("#cfg-oct").value = cfg.pitch_octave || "";
  $("#cfg-flat").value = cfg.flatten ?? 1;
  $("#cfg-flat-v").textContent = (+(cfg.flatten ?? 1)).toFixed(2);
  const mix = p.mix || {};
  $("#base-info").textContent = mix.base_path
    ? `Base: ${mix.base_path.split(/[\\/]/).pop()}` + (p.base ? ` — ${baseSummary(p.base)}` : " (not mapped)")
    : "No base — the remix uses its own source-made drums and bass.";
  $("#auto-base-info").textContent = mix.base_path
    ? `${mix.base_path.split(/[\\/]/).pop()}` + (p.base ? ` — ${p.base.bpm} BPM, ${p.base.bars} bars, the remix follows its sections` : "")
    : "No base: a classic Sparta structure with drums and bass cut from the video.";
  $("#base-offset").value = mix.base_offset ?? 0;
  $("#base-gain").value = mix.base_gain_db ?? -3;
  $("#base-mode").value = mix.base_mode || "replace";
  renderOutputs();
}

async function refreshProject() {
  S.project = await api("/api/project");
  renderProject();
}

// ── 1 · source ───────────────────────────────────────────────────────────────
function upload(url, file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.setRequestHeader("X-Filename", encodeURIComponent(file.name));
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch (e) { /* ignore */ }
      if (xhr.status >= 200 && xhr.status < 300 && data && !data.error) resolve(data);
      else reject(new Error((data && data.error) || `upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("network error"));
    xhr.send(file);
  });
}

async function useFile(file) {
  if (!file) return;
  $("#upbar").style.width = "0%";
  try {
    await upload("/api/source/upload", file, (p) => ($("#upbar").style.width = `${Math.round(p * 100)}%`));
    S.bank = null; S.arr = null;
    await refreshProject();
    toast(`Loaded ${file.name}`, true);
  } catch (e) { toast(e.message); }
}

$("#file").addEventListener("change", (e) => useFile(e.target.files[0]));
const drop = $("#drop");
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => useFile(e.dataTransfer.files[0]));

$("#btn-url").addEventListener("click", async () => {
  const url = $("#url").value.trim();
  if (!url) return toast("Paste a link first.");
  const res = await runJob("/api/source/url", { url }, "Download");
  if (res) { S.project = res; S.bank = null; S.arr = null; renderProject(); }
});
$("#btn-path").addEventListener("click", async () => {
  try {
    const r = await api("/api/source/path", { body: { path: $("#path").value.trim() } });
    S.project = r.project; S.bank = null; S.arr = null; renderProject();
  } catch (e) { toast(e.message); }
});
$("#proj-name").addEventListener("change", async () => {
  S.project = await api("/api/project/name", { body: { name: $("#proj-name").value } });
  S.arr = null;
});
$("#btn-new").addEventListener("click", async () => {
  if (!confirm("Start a new project? (the current one stays saved in its folder)")) return;
  S.project = await api("/api/project/new", { body: {} });
  S.bank = null; S.arr = null;
  $("#sample-groups").innerHTML = ""; renderProject(); go("source");
});
$("#btn-projects").addEventListener("click", async () => {
  const r = await api("/api/projects");
  const list = $("#project-list");
  list.innerHTML = r.projects.length ? "" : "<p class='muted'>No saved projects yet.</p>";
  r.projects.forEach((p) => {
    const b = document.createElement("button");
    b.innerHTML = `<b>${esc(p.name)}</b> <span class="muted">· ${esc(p.variant)} · ${new Date(p.modified * 1000).toLocaleString()}</span>`;
    b.onclick = async () => {
      try {
        S.project = await api("/api/project/open", { body: { path: p.path } });
        S.bank = null; S.arr = null; renderProject();
        if (S.project.analyzed) await loadSamples();
        $("#dlg-projects").close();
      } catch (e) { toast(e.message); }
    };
    list.appendChild(b);
  });
  $("#dlg-projects").showModal();
});
$("#btn-analyze").dataset.heavy = "1";
$("#btn-analyze").addEventListener("click", async () => {
  if (S.project && S.project.analyzed && S.bank) return go("samples");
  const res = await runJob("/api/analyze", {}, "Sample detection");
  if (res) { S.bank = res; renderSamples(); await refreshProject(); go("samples"); }
});

// ── 2 · samples ──────────────────────────────────────────────────────────────
const GROUPS = [
  ["Chorus, Epicness & DunDunDenDen — the main phrase cut in two, and a third word (play as they are)", ["chorus_a", "chorus_b", "chorus_c", "chorus_c_a", "chorus_c_b"]],
  ["Pitches (tuned) — several play the chord lines together", ["pitch1", "pitch2", "pitch3", "pitch4", "bass"]],
  ["Percussion", ["kick", "snare", "clap", "hat_closed", "hat_open", "hat2", "perc", "crash"]],
  ["Quotes & Madness words", ["quote1", "quote2", "quote3", "phrase", "word_a", "word_b"]],
  ["Main phrase syllables (DunDunDenDen chops)", null],
];
const ROLE_KIND = { chorus_a: "word", chorus_b: "word", chorus_c: "word", chorus_c_a: "word", chorus_c_b: "word", pitch1: "pitch", pitch2: "pitch", pitch3: "pitch", pitch4: "pitch", kick: "kick", snare: "snare", clap: "snare",
  hat_closed: "hat", hat_open: "hat", hat2: "hat", perc: "snare", crash: "crash", quote1: "quote", quote2: "quote", quote3: "quote",
  phrase: "quote", word_a: "word", word_b: "word" };
// Both chorus parts come from one pick: the main phrase.
const SELECT_KEY = { chorus_a: "chorus", chorus_b: "chorus", chorus_c_a: "chorus_c", chorus_c_b: "chorus_c" };
const ROLE_NAME = { chorus_a: "Chorus 1 — part 1", chorus_b: "Chorus 2 — part 2", chorus_c: "Epicness 3 — third word", chorus_c_a: "DunDunDenDen 3A", chorus_c_b: "DunDunDenDen 3B", pitch1: "Main pitch", pitch2: "Second pitch", pitch3: "Third pitch", pitch4: "Fourth pitch", bass: "Bass",
  kick: "Kick", snare: "Snare", clap: "Clap", hat_closed: "Closed hat", hat_open: "Open hat", hat2: "Second hi-hat", perc: "Extra hit", crash: "Crash",
  quote1: "Quote 1", quote2: "Quote 2", quote3: "Quote 3", phrase: "Main phrase", word_a: "Madness word 1",
  word_b: "Madness word 2" };

async function loadSamples() {
  try { S.bank = await api("/api/samples"); renderSamples(); } catch (e) { if (!/not analysed/.test(e.message)) toast(e.message); }
}

function sampleMeta(s) {
  const m = s.meta || {};
  if (s.role === "pitch" && m.source_note) return `${esc(m.source_note)} → ${esc(s.root_note)} (${m.shift_semitones > 0 ? "+" : ""}${m.shift_semitones} st)`;
  if (s.role === "bass") return `${esc(s.root_note)} from ${esc(m.from)}`;
  if (s.role === "kick") return m.shift_semitones ? `pitched ${m.shift_semitones} st for body` : "source kick";
  if (s.role === "syllable" || s.role === "word") return m.tuned_to ? `tuned copy on ${esc(m.tuned_to)}` : "";
  if (s.role === "chorus") return `main phrase, plays as is · cut at ${esc(m.split || "the middle")}`;
  return "";
}

function renderSamples() {
  const b = S.bank;
  const root = $("#sample-groups");
  if (!b) { root.innerHTML = ""; return; }
  const byId = Object.fromEntries(b.samples.map((s) => [s.id, s]));
  const syls = b.samples.filter((s) => s.role === "syllable").map((s) => s.id);
  root.innerHTML = "";
  GROUPS.forEach(([title, ids]) => {
    const list = (ids || syls).filter((id) => byId[id]);
    if (!list.length) return;
    const g = document.createElement("div");
    g.className = "group card";
    g.innerHTML = `<h3>${esc(title)}</h3><div class="sgrid"></div>`;
    const grid = $(".sgrid", g);
    list.forEach((id) => grid.appendChild(sampleCard(byId[id], b)));
    root.appendChild(g);
  });
}

function sampleCard(s, b) {
  const el = document.createElement("div");
  el.className = "sample";
  const kind = ROLE_KIND[s.id];
  const cands = kind ? (b.candidates[kind] || []) : [];
  const key = SELECT_KEY[s.id] || s.id;
  const sel = (b.config.selections || {})[key];
  const selIdx = typeof sel === "number" ? sel : null;
  const opts = cands.map((c, i) => {
    const extra = c.kind === "pitch" && c.info.note ? ` ${c.info.note}` : "";
    return `<option value="${i}" ${selIdx === i ? "selected" : ""}>#${i + 1} ${fmtT(c.start)} (${c.duration.toFixed(2)}s)${esc(extra)} · ${c.score.toFixed(2)}</option>`;
  }).join("");
  el.innerHTML = `
    <div class="thumb" style="background-image:url('${s.thumb_url}')" title="play the video clip">
      <span class="tag">${esc(ROLE_NAME[s.id] || s.label)}</span>${s.root_note && s.role !== "chorus" ? `<span class="note">${esc(s.root_note)}</span>` : ""}
    </div>
    <div class="body">
      <div><b>${fmtT(s.src_start)}</b> – ${fmtT(s.src_end)} <span class="muted">· ${s.duration.toFixed(2)}s</span></div>
      <div class="meta">${sampleMeta(s)}</div>
      <div class="btns"><button class="small" data-act="play">▶ Processed</button><button class="small ghost" data-act="orig">◇ Original</button></div>
      ${kind ? `<select data-act="cand"><option value="">auto (best)</option>${opts}</select>
      <div class="range"><input type="number" step="0.01" placeholder="start" value="${sel && sel.start !== undefined ? sel.start : ""}">
        <input type="number" step="0.01" placeholder="end" value="${sel && sel.end !== undefined ? sel.end : ""}">
        <button class="small ghost" data-act="range">Set</button></div>` : ""}
    </div>`;
  $("[data-act=play]", el).onclick = () => playAudio(s.audio_url, el);
  $("[data-act=orig]", el).onclick = () => playClip(el, s.src_start, s.src_end);
  $(".thumb", el).onclick = () => playClip(el, s.src_start, s.src_end, true);
  const cs = $("[data-act=cand]", el);
  if (cs) cs.onchange = async () => {
    const body = cs.value === "" ? { role: key, reset: true } : { role: key, index: +cs.value };
    try { S.bank = await api("/api/samples/select", { body }); renderSamples(); S.arr = null; } catch (e) { toast(e.message); }
  };
  const rb = $("[data-act=range]", el);
  if (rb) rb.onclick = async () => {
    const [a, z] = $$(".range input", el).map((i) => parseFloat(i.value));
    if (!(z > a)) return toast("End must be after start.");
    try { S.bank = await api("/api/samples/select", { body: { role: key, start: a, end: z } }); renderSamples(); } catch (e) { toast(e.message); }
  };
  return el;
}

const player = $("#player");
function playAudio(url, card) {
  $$(".playing").forEach((x) => x.classList.remove("playing"));
  player.src = url;
  player.play().catch(() => {});
  if (card) { card.classList.add("playing"); player.onended = () => card.classList.remove("playing"); }
}

let clipVideo = null;
function playClip(card, a, z, visible = false) {
  const src = S.project && S.project.source && S.project.source.url;
  if (!src) return;
  if (!clipVideo) { clipVideo = document.createElement("video"); clipVideo.playsInline = true; clipVideo.style.cssText = "width:100%;height:100%;object-fit:cover;margin:0;border-radius:0"; }
  const thumb = $(".thumb", card);
  const done = () => { clipVideo.pause(); clipVideo.remove(); card.classList.remove("playing"); };
  if (clipVideo.parentElement) clipVideo.parentElement.classList.remove("playing");
  thumb.appendChild(clipVideo);
  card.classList.add("playing");
  if (clipVideo.dataset.src !== src) { clipVideo.src = src; clipVideo.dataset.src = src; }
  clipVideo.currentTime = a;
  clipVideo.ontimeupdate = () => { if (clipVideo.currentTime >= z) done(); };
  clipVideo.play().catch(() => done());
}

async function saveSampleCfg() {
  const body = { key: $("#cfg-key").value, pitch_octave: $("#cfg-oct").value ? +$("#cfg-oct").value : null, flatten: +$("#cfg-flat").value };
  try { S.bank = await api("/api/samples/config", { body }); renderSamples(); } catch (e) { toast(e.message); }
}
["change"].forEach((ev) => { $("#cfg-key").addEventListener(ev, saveSampleCfg); $("#cfg-oct").addEventListener(ev, saveSampleCfg); $("#cfg-flat").addEventListener(ev, saveSampleCfg); });
$("#cfg-flat").addEventListener("input", () => ($("#cfg-flat-v").textContent = (+$("#cfg-flat").value).toFixed(2)));
$("#btn-reanalyze").dataset.heavy = "1";
$("#btn-reanalyze").addEventListener("click", async () => {
  const res = await runJob("/api/analyze", { force: true }, "Sample detection");
  if (res) { S.bank = res; renderSamples(); }
});

// ── 3 · remix ────────────────────────────────────────────────────────────────
function baseSummary(b) {
  const secs = (b.sections || []).map((s) => `${s.kind} ${s.bars}`).join(" · ");
  return `${b.bpm} BPM · bar 1 at ${(+b.offset).toFixed(3)} s · ${b.bars} bars · key ${b.key}${b.minor ? " minor" : ""} · chords ${b.progression}` + (secs ? ` — ${secs}` : "");
}

function renderVariants() {
  const root = $("#variants");
  root.innerHTML = "";
  const b = S.project && S.project.base;
  if (b) {
    const el = document.createElement("div");
    el.className = "variant" + (S.variant === "base" ? " active" : "");
    el.innerHTML = `<h4>Follow my base</h4><div class="v-meta">${esc(b.bpm)} BPM · ${esc(b.bars)} bars · ${fmtT(b.bars * 240 / b.bpm)}</div><p>Every section of your base gets its part: ${esc((b.sections || []).map((s) => s.kind).join(", "))}.</p>`;
    el.onclick = () => { S.variant = "base"; renderVariants(); $("#opt-bpm").value = b.bpm; };
    root.appendChild(el);
  }
  Object.entries(S.variants.variants).forEach(([k, v]) => {
    const bars = v.plan.reduce((a, p) => a + p[1], 0);
    const secs = bars * 4 * 60 / v.bpm;
    const el = document.createElement("div");
    el.className = "variant" + (k === S.variant ? " active" : "");
    el.innerHTML = `<h4>${esc(v.title)}</h4><div class="v-meta">${v.bpm} BPM · ${bars} bars · ${fmtT(secs)} · pitching ${esc(v.pitching)} · polish ${esc(v.polish)}</div><p>${esc(v.description)}</p>`;
    el.onclick = () => { S.variant = k; renderVariants(); $("#opt-bpm").value = v.bpm; $("#opt-pitching").value = v.pitching; $("#opt-polish").value = v.polish; };
    root.appendChild(el);
  });
}

function optionsFromForm() {
  const o = {};
  if ($("#opt-title").value.trim()) o.title = $("#opt-title").value.trim();
  if ($("#opt-bpm").value) o.bpm = +$("#opt-bpm").value;
  o.progression = $("#opt-prog").value;
  o.pitching = $("#opt-pitching").value;
  o.polish = $("#opt-polish").value;
  if (S.project && S.project.base) o.minor = $("#opt-minor").checked;
  else if ($("#opt-minor").checked) o.minor = true;
  if ($("#opt-chorus-pitch").checked) o.chorus_pitch = true;
  o.key = $("#cfg-key").value || "D";
  return o;
}

$("#btn-apply-variant").addEventListener("click", async () => {
  if (S.dirty && !confirm("Discard your section edits and rebuild?")) return;
  try {
    S.arr = await api("/api/arrangement/variant", { body: { variant: S.variant, options: optionsFromForm() } });
    S.dirty = false; renderArrangement(); await refreshProject();
    toast("Arrangement rebuilt", true);
  } catch (e) { toast(e.message); }
});

async function loadArrangement() {
  try {
    S.arr = await api("/api/arrangement");
    $("#opt-bpm").value = S.arr.bpm;
    $("#opt-pitching").value = S.arr.pitching;
    $("#opt-polish").value = S.arr.polish;
    setProgSelect(S.arr.progression);
    renderArrangement();
  } catch (e) { toast(e.message); }
}

function setProgSelect(value) {
  const sel = $("#opt-prog");
  if (![...sel.options].some((o) => o.value === value)) {
    const o = document.createElement("option"); o.value = value; o.textContent = `custom (${value})`; sel.appendChild(o);
  }
  sel.value = value;
}

const LAYOUTS = ["main", "full", "split2", "grid3", "grid4"];
const TRACK_SECTIONS = {
  pitch: ["chorus", "dundundenden", "epicness", "awesomeness", "execution", "madness", "intro", "chords", "freestyle"],
  chop: ["dundundenden", "intro", "chorus", "execution"],
  words: ["madness_words", "freestyle"],
  bass: ["dundundenden", "chorus", "intro", "execution"],
  drum: ["percussion", "hihat"], oneshot: [],
};

function patternOptions(track) {
  const cur = track.pattern || "";
  let html = "";
  if (track.kind === "drum") {
    html += `<optgroup label="Drum grooves">`;
    Object.entries(S.catalog.drums).forEach(([g, parts]) => Object.keys(parts).forEach((part) => {
      if (!parts[part]) return;
      const v = `drum:${g}:${part}`; html += `<option value="${v}" ${v === cur ? "selected" : ""}>${g} · ${part}</option>`;
    }));
    html += `</optgroup>`;
  }
  if (track.kind === "bass") {
    html += `<optgroup label="Bass grooves">` + Object.keys(S.catalog.bass).map((g) => {
      const v = `bass:${g}`; return `<option value="${v}" ${v === cur ? "selected" : ""}>${g}</option>`;
    }).join("") + `</optgroup>`;
  }
  (TRACK_SECTIONS[track.kind] || []).forEach((sec) => {
    const list = S.catalog.sections[sec] || [];
    if (!list.length) return;
    html += `<optgroup label="${esc(S.catalog.titles[sec] || sec)}">` + list.map((p) =>
      `<option value="${esc(p.id)}" ${p.id === cur ? "selected" : ""}>${esc(p.name)} · ${p.bars} bar${p.bars === 1 ? "" : "s"}</option>`).join("") + `</optgroup>`;
  });
  const custom = cur.startsWith("text:");
  html = (cur === "" ? `<option value="" selected>(follows another track)</option>` : "") + html +
    `<option value="text:" ${custom ? "selected" : ""}>Custom pattern…</option>`;
  return html;
}

function sampleOptions(cur) {
  const ids = S.bank ? S.bank.samples.map((s) => s.id) : ["pitch1", "pitch2", "pitch3", "pitch4", "bass", "kick", "snare", "clap", "hat_closed", "hat_open", "crash", "quote1", "phrase", "word_a", "word_b"];
  return ids.map((id) => `<option ${id === cur ? "selected" : ""}>${esc(id)}</option>`).join("");
}

function markDirty() { S.dirty = true; $("#arr-dirty").classList.remove("hidden"); renderTimeline(); }

function renderTimeline() {
  const a = S.arr;
  const total = a.sections.reduce((x, s) => x + s.bars, 0) || 1;
  const secs = total * 4 * 60 / a.bpm;
  $("#arr-summary").textContent = `${a.title} · ${a.bpm} BPM · ${total} bars · ${fmtT(secs)}`;
  $("#timeline").innerHTML = a.sections.map((s) =>
    `<div class="k-${esc(s.kind)}" style="flex:${s.bars}" title="${esc(s.name || s.kind)} (${s.bars} bars)">${esc(s.name || s.kind)}</div>`).join("");
}

function renderArrangement() {
  const a = S.arr;
  if (!a) return;
  renderTimeline();
  $("#arr-dirty").classList.toggle("hidden", !S.dirty);
  const root = $("#sections");
  const open = new Set($$(".section.open", root).map((e) => e.dataset.idx));
  root.innerHTML = "";
  a.sections.forEach((sec, i) => {
    const el = document.createElement("div");
    el.className = "section" + (open.has(String(i)) ? " open" : "");
    el.dataset.idx = i;
    el.innerHTML = `<header>
        <span class="swatch k-${esc(sec.kind)}"></span>
        <input class="sname" value="${esc(sec.name || sec.kind)}">
        <span class="muted">${esc(sec.kind)}</span>
        <input class="sbars" type="number" min="1" max="64" value="${sec.bars}"> bars
        <select class="slayout">${LAYOUTS.map((l) => `<option ${l === sec.layout ? "selected" : ""}>${l}</option>`).join("")}</select>
        <span class="spacer"></span>
        <button class="small ghost" data-a="up">↑</button><button class="small ghost" data-a="down">↓</button>
        <button class="small ghost" data-a="dup">⧉</button><button class="small ghost" data-a="del">✕</button>
        <button class="small" data-a="toggle">${el.classList.contains("open") ? "Hide" : "Tracks"} (${sec.tracks.length})</button>
      </header><div class="tracks"></div>`;
    $(".sname", el).onchange = (e) => { sec.name = e.target.value; markDirty(); };
    $(".sbars", el).onchange = (e) => { sec.bars = Math.max(1, +e.target.value || 1); markDirty(); };
    $(".slayout", el).onchange = (e) => { sec.layout = e.target.value; markDirty(); };
    $("[data-a=up]", el).onclick = () => { if (i > 0) { a.sections.splice(i - 1, 0, a.sections.splice(i, 1)[0]); markDirty(); renderArrangement(); } };
    $("[data-a=down]", el).onclick = () => { if (i < a.sections.length - 1) { a.sections.splice(i + 1, 0, a.sections.splice(i, 1)[0]); markDirty(); renderArrangement(); } };
    $("[data-a=dup]", el).onclick = () => { a.sections.splice(i + 1, 0, JSON.parse(JSON.stringify(sec))); markDirty(); renderArrangement(); };
    $("[data-a=del]", el).onclick = () => { if (confirm(`Remove ${sec.name || sec.kind}?`)) { a.sections.splice(i, 1); markDirty(); renderArrangement(); } };
    $("[data-a=toggle]", el).onclick = () => { el.classList.toggle("open"); renderTracks(sec, $(".tracks", el)); $("[data-a=toggle]", el).textContent = `${el.classList.contains("open") ? "Hide" : "Tracks"} (${sec.tracks.length})`; };
    if (el.classList.contains("open")) renderTracks(sec, $(".tracks", el));
    root.appendChild(el);
  });
}

function renderTracks(sec, box) {
  if (!box.closest(".section").classList.contains("open")) return;
  box.innerHTML = "";
  sec.tracks.forEach((t) => {
    const el = document.createElement("div");
    el.className = "track" + (t.muted ? " muted" : "");
    const isText = (t.pattern || "").startsWith("text:");
    const slotTxt = t.slots && Object.keys(t.slots).length ? Object.entries(t.slots).map(([k, v]) => `${k}→${typeof v === "string" ? v : v.sample}`).join(", ") : "";
    // Several pitches: one sample per line of the pattern (picking one sample plays every line with it).
    const voiceTxt = (t.voice_samples || []).length ? `<span class="pv voices" title="one pitch sample per line of the pattern">voices ${esc(t.voice_samples.join(" · "))}</span>` : "";
    el.innerHTML = `
      <div class="tline"><span class="tid">${esc(t.id)}</span><span class="tkind">${esc(t.kind)}${t.follow ? " · follows " + esc(t.follow) : ""}</span>
        ${t.pattern !== "" || t.kind !== "drum" ? `<select class="pat">${patternOptions(t)}</select>` : ""}
        ${t.slots && Object.keys(t.slots).length ? `<span class="pv">slots ${esc(slotTxt)}</span>` : `${voiceTxt}<label>sample <select class="smp">${sampleOptions(t.sample)}</select></label>`}
      </div>
      <textarea class="ptext ${isText ? "" : "hidden"}" rows="2" placeholder="pattern in wiki notation">${esc(isText ? t.pattern.slice(5) : "")}</textarea>
      <div class="tline">
        <label>gain <input class="gain" type="number" step="0.5" value="${t.gain_db}"> dB</label>
        <label>oct <input class="oct" type="number" min="-3" max="3" value="${t.octave}" style="width:4em"></label>
        <label>bars <input class="sb" type="number" step="1" min="0" value="${t.start_bar}" style="width:4em">–<input class="eb" type="number" step="1" min="0" value="${t.end_bar ?? ""}" placeholder="end" style="width:4em"></label>
        <label><input class="crisp" type="checkbox" ${t.crisp ? "checked" : ""}> crisp</label>
        <label><input class="mute" type="checkbox" ${t.muted ? "checked" : ""}> mute</label>
        <span class="pv"></span>
      </div>
      <div class="roll hidden"></div>`;
    const pat = $(".pat", el);
    const txt = $(".ptext", el);
    const preview = () => previewPattern(t, el);
    if (pat) pat.onchange = () => {
      if (pat.value === "text:") { txt.classList.remove("hidden"); t.pattern = "text:" + txt.value; }
      else { txt.classList.add("hidden"); t.pattern = pat.value; }
      if (t.pattern.startsWith("text:") || !t.pattern.startsWith("drum:") && !t.pattern.startsWith("bass:")) t.mode = "auto";
      markDirty(); preview();
    };
    txt.oninput = () => { t.pattern = "text:" + txt.value; markDirty(); clearTimeout(txt._t); txt._t = setTimeout(preview, 350); };
    const smp = $(".smp", el);
    if (smp) smp.onchange = () => {
      t.sample = smp.value;
      if ((t.voice_samples || []).length) { t.voice_samples = []; const v = $(".voices", el); if (v) v.remove(); }
      markDirty();
    };
    $(".gain", el).onchange = (e) => { t.gain_db = +e.target.value; markDirty(); };
    $(".oct", el).onchange = (e) => { t.octave = +e.target.value; markDirty(); };
    $(".sb", el).onchange = (e) => { t.start_bar = +e.target.value || 0; markDirty(); };
    $(".eb", el).onchange = (e) => { t.end_bar = e.target.value === "" ? null : +e.target.value; markDirty(); };
    $(".crisp", el).onchange = (e) => { t.crisp = e.target.checked; markDirty(); };
    $(".mute", el).onchange = (e) => { t.muted = e.target.checked; el.classList.toggle("muted", t.muted); markDirty(); };
    box.appendChild(el);
    preview();
  });
}

function patternText(t) {
  const p = t.pattern || "";
  if (p.startsWith("text:")) return { text: p.slice(5), mode: t.mode || "auto" };
  if (p.startsWith("drum:")) { const [, g, part] = p.split(":"); return { text: S.catalog.drums[g][part] || "", mode: "index" }; }
  if (p.startsWith("bass:")) return { text: S.catalog.bass[p.slice(5)], mode: "index" };
  for (const list of Object.values(S.catalog.sections)) {
    const d = list.find((x) => x.id === p);
    if (d) return { text: d.text, mode: t.mode !== "auto" ? t.mode : d.mode, lines: d.lines };
  }
  return null;
}

async function previewPattern(t, el) {
  const src = patternText(t);
  const pv = $$(".pv", el).pop();
  const roll = $(".roll", el);
  if (!src || !src.text) { roll.classList.add("hidden"); pv.textContent = ""; return; }
  try {
    const r = await api("/api/pattern/parse", { body: { text: src.text, mode: src.mode, lines: src.lines } });
    pv.textContent = `${r.mode} · ${r.bars.toFixed(2)} bars${r.warnings.length ? " · ⚠ " + r.warnings[0] : ""}`;
    drawRoll(roll, r);
  } catch (e) { pv.textContent = "⚠ " + e.message; }
}

function drawRoll(roll, r) {
  roll.classList.remove("hidden");
  const len = Math.max(r.loop || r.length, 16);
  const vals = r.notes.map((n) => n.value + (n.sharp || 0));
  const lo = Math.min(...vals, 0), hi = Math.max(...vals, 1);
  const H = 84;
  let html = "";
  for (let b = 0; b <= len; b += 16) html += `<b style="left:${(b / len) * 100}%"></b>`;
  r.notes.forEach((n) => {
    const y = hi === lo ? H / 2 : H - 6 - ((n.value + (n.sharp || 0) - lo) / (hi - lo)) * (H - 12);
    html += `<i class="v${n.voice % 4}" style="left:${(n.start / len) * 100}%;width:${Math.max(0.4, (n.dur / len) * 100 - 0.15)}%;top:${y}px" title="${n.value}"></i>`;
  });
  roll.innerHTML = html;
}

$("#btn-save-arr").addEventListener("click", async () => {
  try {
    S.arr = await api("/api/arrangement", { body: S.arr });
    S.dirty = false; renderArrangement(); toast("Arrangement saved", true);
  } catch (e) { toast(e.message); }
});
$("#btn-add-section").addEventListener("click", async () => {
  try {
    const sec = await api("/api/arrangement/section", { body: { kind: $("#add-kind").value, bars: +$("#add-bars").value } });
    S.arr.sections.splice(Math.max(0, S.arr.sections.length - 1), 0, sec);
    markDirty(); renderArrangement();
  } catch (e) { toast(e.message); }
});

// pattern lab
async function labParse() {
  const text = $("#lab-text").value;
  const out = $("#lab-out");
  if (!text.trim()) { out.innerHTML = ""; return; }
  try {
    const r = await api("/api/pattern/parse", { body: { text, mode: $("#lab-mode").value } });
    out.innerHTML = `<div>${esc(r.mode)} · ${r.length} steps = ${r.bars.toFixed(2)} bars (loops every ${r.loop / 16} bar${r.loop === 16 ? "" : "s"}) · ${r.notes.length} notes · ${r.voices} voice${r.voices > 1 ? "s" : ""}${r.warnings.length ? "<br>⚠ " + r.warnings.map(esc).join("<br>⚠ ") : ""}</div><div class="roll"></div>`;
    drawRoll($(".roll", out), r);
  } catch (e) { out.textContent = "⚠ " + e.message; }
}
$("#lab-text").addEventListener("input", () => { clearTimeout(labParse._t); labParse._t = setTimeout(labParse, 300); });
$("#lab-mode").addEventListener("change", labParse);
$("#btn-lab-add").addEventListener("click", async () => {
  const text = $("#lab-text").value.trim();
  if (!text) return toast("Type a pattern first.");
  try {
    await api("/api/pattern/add", { body: { text, mode: $("#lab-mode").value, name: $("#lab-name").value || "My pattern", section: $("#lab-section").value } });
    S.catalog = await api("/api/patterns");
    toast("Added — pick it in any track's pattern list", true);
  } catch (e) { toast(e.message); }
});

// base
async function useBase(f) {
  if (!f) return;
  try {
    toast("Mapping the base…", true);
    $("#auto-base-info").textContent = "Mapping the base (tempo, bars, chords, sections)…";
    S.project = (await upload("/api/base/upload", f, () => {}));
    renderProject(); renderVariants();
    if (S.project.base) {
      S.variant = "base";
      await loadArrangement(); renderVariants();
      toast("Base mapped — the remix now follows its sections", true);
    } else toast("Base loaded" + (S.project.base_error ? ` (could not map it: ${S.project.base_error})` : ""), true);
  } catch (err) { toast(err.message); renderProject(); }
}
$("#base-file").addEventListener("change", (e) => useBase(e.target.files[0]));
$("#auto-base").addEventListener("change", (e) => useBase(e.target.files[0]));
["base-offset", "base-gain", "base-mode"].forEach((id) => $("#" + id).addEventListener("change", async () => {
  S.project = await api("/api/mix", { body: { base_offset: +$("#base-offset").value, base_gain_db: +$("#base-gain").value, base_mode: $("#base-mode").value } });
  renderProject();
}));
$("#btn-base-clear").addEventListener("click", async () => { S.project = await api("/api/mix", { body: { clear_base: true } }); renderProject(); });

// ── 4 · render ───────────────────────────────────────────────────────────────
function dl(url, name) {
  if (!url) return url;
  return url + (url.includes("?") ? "&" : "?") + "download=" + encodeURIComponent(name);
}

function renderOutputs() {
  const outs = (S.project && S.project.outputs) || {};
  const box = $("#final-out");
  box.innerHTML = "";
  ["1080p", "720p"].forEach((q) => {
    const o = outs[q];
    if (!o) return;
    const base = (o.title || "Sparta Remix").replace(/[\\/:*?"<>|]/g, "_");
    box.innerHTML += `<a href="${dl(o.file_url, base + ".mp4")}">⬇ ${esc(q)} video (${fmtT(o.duration)}, ${o.lufs} LUFS)</a>
                      <a href="${dl(o.audio_url, base + ".wav")}">⬇ ${esc(q)} audio (WAV)</a>`;
  });
}

async function ensureSaved() {
  if (S.dirty) {
    try { S.arr = await api("/api/arrangement", { body: S.arr }); S.dirty = false; renderArrangement(); } catch (e) { toast(e.message); return false; }
  }
  if (!S.project || !S.project.source) { toast("Load a source video first."); go("source"); return false; }
  return true;
}

["btn-preview", "btn-preview-audio", "btn-final", "btn-pack"].forEach((id) => ($("#" + id).dataset.heavy = "1"));
function showPreview(r) {
  const v = $("#preview-video");
  $("#preview-audio").classList.add("hidden");
  v.classList.remove("hidden");
  v.src = r.file_url + (r.file_url.includes("?") ? "&" : "?") + "t=" + Date.now();
  v.play().catch(() => {});
  $("#preview-info").textContent = `${r.title} · ${fmtT(r.duration)} · ${r.events} notes · ${r.lufs} LUFS · peak ${r.peak_db} dBFS`;
}
$("#btn-preview").addEventListener("click", async () => {
  if (!(await ensureSaved())) return;
  const r = await runJob("/api/render", { quality: "preview" }, "Preview render");
  if (!r) return;
  showPreview(r);
  await refreshProject();
});
$("#btn-auto").dataset.heavy = "1";
$("#btn-auto").addEventListener("click", async () => {
  if (!(await ensureSaved())) return;
  const r = await runJob("/api/auto", { quality: "preview" }, "Making your Sparta Remix");
  if (!r) return;
  await refreshProject();
  S.arr = null;
  await loadSamples();
  go("render");
  showPreview(r);
});
$("#btn-preview-audio").addEventListener("click", async () => {
  if (!(await ensureSaved())) return;
  const r = await runJob("/api/render", { quality: "audio" }, "Audio preview");
  if (!r) return;
  const a = $("#preview-audio");
  $("#preview-video").classList.add("hidden");
  a.classList.remove("hidden");
  a.src = r.file_url + "?t=" + Date.now();
  a.play().catch(() => {});
  $("#preview-info").textContent = `${r.title} · ${fmtT(r.duration)} · ${r.lufs} LUFS`;
});
$("#btn-final").addEventListener("click", async () => {
  if (!(await ensureSaved())) return;
  const q = $("#final-quality").value;
  const r = await runJob("/api/render", { quality: q }, `Final ${q} render`);
  if (r) { await refreshProject(); }
});
$("#btn-pack").addEventListener("click", async () => {
  const r = await runJob("/api/pack", { video: true }, "Sample pack");
  if (r) $("#pack-out").innerHTML = `<a href="${dl(r.zip_url, r.zip.split(/[\\/]/).pop())}">⬇ Sample pack (${r.count} files)</a>`;
});
$("#btn-save-proj").addEventListener("click", async () => {
  try { const r = await api("/api/project/save", { body: {} }); toast(`Saved ${r.saved}`, true); } catch (e) { toast(e.message); }
});
$("#btn-saveas").addEventListener("click", async () => {
  const outs = (S.project && S.project.outputs) || {};
  const o = outs["1080p"] || outs["720p"] || outs.preview;
  if (!o) return toast("Render something first.");
  const dest = $("#saveas-path").value.trim() || $("#saveas-path").placeholder;
  try { const r = await api("/api/save_as", { body: { file: o.file, dest } }); toast(`Copied to ${r.saved}`, true); } catch (e) { toast(e.message); }
});

// Some browsers (e.g. Chromium builds without proprietary codecs) cannot decode H.264:
// offer the file for download instead of a silent black player.
$("#preview-video").addEventListener("error", () => {
  const v = $("#preview-video");
  if (!v.src) return;
  $("#preview-info").innerHTML += `<br>This browser cannot play H.264 video — <a href="${v.src}" download>download the preview</a> and open it in a player.`;
});

$("#btn-quit").addEventListener("click", async () => {
  if (!confirm("Stop SpartaGen? Your project is saved in its workspace folder.")) return;
  try { await api("/api/project/save", { body: {} }); } catch (e) { /* nothing loaded */ }
  try { await api("/api/quit", { body: {} }); } catch (e) { /* server already gone */ }
  document.body.innerHTML = "<main><div class='card'><h2>SpartaGen stopped</h2><p class='hint'>You can close this tab.</p></div></main>";
});

// ── boot ─────────────────────────────────────────────────────────────────────
(async function boot() {
  try {
    const [st, variants, catalog] = await Promise.all([api("/api/status"), api("/api/variants"), api("/api/patterns")]);
    S.status = st; S.variants = variants; S.catalog = catalog; S.project = st.project;
    renderStatus();
    ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"].forEach((k) => $("#cfg-key").insertAdjacentHTML("beforeend", `<option ${k === "D" ? "selected" : ""}>${k}</option>`));
    catalog.sections.progression.forEach((p) => $("#opt-prog").insertAdjacentHTML("beforeend", `<option value="${esc(p.text)}">${esc(p.name)} (${esc(p.text)})</option>`));
    variants.section_kinds.forEach((k) => $("#add-kind").insertAdjacentHTML("beforeend", `<option>${esc(k)}</option>`));
    Object.entries(catalog.titles).forEach(([k, t]) => { if (k !== "progression") $("#lab-section").insertAdjacentHTML("beforeend", `<option value="${esc(k)}">${esc(t)}</option>`); });
    renderProject();
    renderVariants();
    const v = variants.variants[S.variant];
    if (v) { $("#opt-bpm").value = v.bpm; $("#opt-pitching").value = v.pitching; $("#opt-polish").value = v.polish; }
    else if (S.project.base) $("#opt-bpm").value = S.project.base.bpm;
    if (S.project.analyzed) await loadSamples();
  } catch (e) { toast("Could not reach the SpartaGen engine: " + e.message); }
})();
