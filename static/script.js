"use strict";

/** Replay Hub Pro - logika antarmuka. */
(() => {
  const $ = (id) => document.getElementById(id);
  const TEST_STREAM = "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8";
  const VIDEOPASS = "https://www.motogp.com/en/videopass";
  const LABELS = { RAC: "RACE", SPR: "SPRINT", WUP: "WARM UP" };
  const ICONS = {
    play: '<svg viewBox="0 0 24 24"><path d="M7 4v16l13-8z"/></svg>',
    pause: '<svg viewBox="0 0 24 24"><path d="M8 5v14M16 5v14"/></svg>',
    sound: '<svg viewBox="0 0 24 24"><path d="M4 9h4l5-4v14l-5-4H4zM17 8.500a5 5 0 0 1 0 7"/></svg>',
    muted: '<svg viewBox="0 0 24 24"><path d="M4 9h4l5-4v14l-5-4H4zM17 9l5 6M22 9l-5 6"/></svg>'
  };

  // Palet kategorikal untuk latar gelap; urutan tetap, maksimal 5 seri.
  const SERIES_COLORS = ["#338ced", "#e76624", "#00a888", "#d28e05", "#e24d8b"];

  const state = { year: null, events: [], event: null, category: "motogp", view: "home", request: 0 };
  const standings = { year: null, type: "riders", mode: "table", request: 0 };
  const video = $("video");
  const stage = $("stage");
  let hls = null;
  let idleTimer = null;
  let resumeKey = null;
  let playerToken = 0;

  /* ---------- Utilitas ---------- */

  /** Escape teks dari API/nama file sebelum dimasukkan ke HTML. */
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const label = (code) => LABELS[code] || code;

  const formatDate = (iso) => {
    const date = new Date(iso);
    return iso && !isNaN(date)
      ? date.toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" })
      : "";
  };

  const store = {
    get(key) { try { return localStorage.getItem(key); } catch { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch { /* penyimpanan penuh/diblokir */ } }
  };

  /** Fetch JSON ke server lokal dengan pesan error yang jelas. */
  async function api(path) {
    let response;
    try {
      response = await fetch(path);
    } catch {
      throw new Error("Server lokal tidak merespons. Pastikan app.py berjalan di Termux.");
    }
    const data = await response.json().catch(() => null);
    if (!response.ok || data === null) {
      throw new Error((data && data.error) || `Permintaan gagal (${response.status})`);
    }
    return data;
  }

  function notice(message) {
    $("homeNotice").textContent = message || "";
    $("homeNotice").hidden = !message;
  }

  /* ---------- Data & halaman utama ---------- */

  async function loadSeasons() {
    try {
      const seasons = await api("/api/seasons");
      if (!seasons.length) throw new Error("Daftar musim kosong.");
      $("season").innerHTML = seasons.map((s) => `<option value="${s.year}">${s.year}</option>`).join("");
      const current = seasons.find((s) => s.current) || seasons[0];
      $("season").value = current.year;
      $("standingsSeason").innerHTML = $("season").innerHTML;
      $("standingsSeason").value = current.year;
      standings.year = current.year;
      if (state.view === "standings") loadStandings();
      await loadEvents(current.year);
    } catch (error) {
      $("heroTitle").textContent = "Data belum tersedia";
      notice(error.message);
      await loadLibrary();
    }
  }

  async function loadEvents(year) {
    state.year = Number(year);
    state.request += 1;
    const token = state.request;
    notice("");
    $("sessions").innerHTML = "";
    try {
      const events = await api(`/api/events?year=${state.year}`);
      if (token !== state.request) return;
      state.events = events;
      $("eventSelect").innerHTML = events
        .map((e) => `<option value="${esc(e.id)}">${esc(e.short)} · ${esc(e.circuit.name || e.name)}</option>`)
        .join("");
      renderCalendar();
      if (!events.length) {
        state.event = null;
        $("heroTitle").textContent = "Belum ada GP";
        $("heroSub").textContent = "";
        $("dots").innerHTML = "";
        return;
      }
      const past = events.filter((e) => new Date(e.date_start) <= new Date());
      selectEvent((past[past.length - 1] || events[0]).id);
    } catch (error) {
      if (token !== state.request) return;
      state.events = [];
      state.event = null;
      renderCalendar();
      notice(error.message);
    }
  }

  function selectEvent(id) {
    const event = state.events.find((e) => e.id === id);
    if (!event) return;
    state.event = event;
    $("eventSelect").value = id;
    $("heroTitle").textContent = event.circuit.name || event.name;
    $("heroSub").textContent = `${event.name} · ${formatDate(event.date_end)}`;
    $("hero").style.backgroundImage = event.image ? `url("${event.image}")` : "";

    const index = state.events.indexOf(event);
    const start = Math.max(0, Math.min(index - 1, state.events.length - 3));
    $("dots").innerHTML = state.events.slice(start, start + 3)
      .map((e) => `<button data-event="${esc(e.id)}" class="${e.id === id ? "active" : ""}" aria-label="${esc(e.name)}"></button>`)
      .join("");
    loadSessions();
  }

  async function loadSessions() {
    if (!state.event) return;
    state.request += 1;
    const token = state.request;
    const grid = $("sessions");
    grid.innerHTML = '<p class="muted">Memuat sesi…</p>';
    notice("");
    try {
      const query = new URLSearchParams({ year: state.year, event: state.event.id, class: state.category });
      const data = await api(`/api/sessions?${query}`);
      if (token !== state.request) return;
      notice(data.warning);
      if (!data.sessions.length) {
        grid.innerHTML = '<p class="muted">Belum ada sesi untuk kelas ini.</p>';
        return;
      }
      const image = state.event.image ? `<img src="${esc(state.event.image)}" alt="">` : "";
      grid.innerHTML = data.sessions.map((s, i) => `
        <button class="session ${s.video ? "has-video" : ""}" data-index="${i}" style="animation-delay:${i * 40}ms">
          ${image}<strong>${esc(label(s.code))}</strong>
          <small>${s.video ? "Video tersedia" : "Hasil & info"}</small><em>›</em>
        </button>`).join("");
      grid.querySelectorAll(".session").forEach((button) => {
        button.onclick = () => {
          const session = data.sessions[Number(button.dataset.index)];
          openPlayer({
            title: `${state.event.short} · ${label(session.code)}`,
            url: session.video,
            sessionId: session.id,
            year: state.year,
            event: state.event,
            hint: `${data.folder}/${session.code}.mp4`
          });
        };
      });
    } catch (error) {
      if (token !== state.request) return;
      grid.innerHTML = "";
      notice(error.message);
    }
  }

  function renderCalendar() {
    const term = $("search").value.trim().toLowerCase();
    const matches = state.events.filter((e) =>
      `${e.name} ${e.short} ${e.circuit.name} ${e.circuit.country}`.toLowerCase().includes(term));
    $("calendar").innerHTML = matches.length ? matches.map((e) => `
      <button class="glass row" data-event="${esc(e.id)}">
        ${e.flag ? `<img src="${esc(e.flag)}" alt="">` : ""}
        <span>${esc(e.name)}<small>${esc(e.circuit.name)} · ${esc(formatDate(e.date_end))}</small></span><b>›</b>
      </button>`).join("") : '<p class="muted">Tidak ada event yang cocok.</p>';
  }

  async function loadLibrary() {
    const list = $("library");
    try {
      const items = await api("/api/library");
      if (!items.length) {
        list.innerHTML = '<p class="muted">Belum ada video. Contoh lokasi file:<br><code>media/2026/INA/motogp/RAC.mp4</code></p>';
        return;
      }
      list.innerHTML = items.map((item, i) => `
        <button class="glass row" data-index="${i}">
          <span>${esc(item.event)} · ${esc(label(item.code))}<small>${item.year} · ${esc(item.class.toUpperCase())}</small></span><b>›</b>
        </button>`).join("");
      list.querySelectorAll("button").forEach((button) => {
        button.onclick = () => {
          const item = items[Number(button.dataset.index)];
          const event = state.year === item.year ? state.events.find((e) => e.short === item.event) : null;
          openPlayer({ title: `${item.event} · ${label(item.code)}`, url: item.url, event });
        };
      });
    } catch (error) {
      list.innerHTML = `<p class="muted">${esc(error.message)}</p>`;
    }
  }

  function showView(name) {
    state.view = name;
    document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
    document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
    document.querySelector(".topbar").hidden = name !== "home" && name !== "calendar";
    if (name === "library") loadLibrary();
    if (name === "standings") loadStandings();
    window.scrollTo(0, 0);
  }

  /* ---------- Klasemen ---------- */

  const num = (value) => value ?? "–";

  async function loadStandings(refresh = false) {
    const box = $("standings");
    standings.request += 1;
    const token = standings.request;
    $("standingsNote").textContent = "";
    if (!standings.year) {
      box.innerHTML = '<p class="muted">Daftar musim belum termuat. Muat ulang aplikasi dari menu More.</p>';
      return;
    }
    box.classList.remove("wide");
    box.innerHTML = '<p class="muted">Memuat klasemen… hitungan pertama kali bisa agak lama.</p>';
    try {
      const query = new URLSearchParams({ year: standings.year, class: state.category, type: standings.type });
      if (standings.mode === "chart") query.set("chart", "1");
      if (refresh) query.set("refresh", "1");
      const data = await api(`/api/standings?${query}`);
      if (token !== standings.request) return;
      $("standingsNote").textContent = data.note;
      if (!data.rows.length) {
        box.innerHTML = '<p class="muted">Klasemen belum tersedia.</p>';
      } else if (standings.mode === "chart") {
        box.classList.remove("wide");
        renderChart(box, data);
      } else {
        renderTable(box, data.rows);
      }
    } catch (error) {
      if (token === standings.request) box.innerHTML = `<p class="muted">${esc(error.message)}</p>`;
    }
  }

  /** Tabel klasemen: foto pembalap, atau foto motor untuk team/constructor. */
  function renderTable(box, rows) {
    const riders = standings.type === "riders";
    const heading = { riders: "RIDER", teams: "TEAM", constructors: "CONSTRUCTOR" }[standings.type];
    const head = `<div class="st-row st-head"><span>POS</span><span></span>
      <span class="st-name">${heading}</span><span>W</span><span>POD</span><span>SW</span><span>PTS</span><span>DIFF</span></div>`;
    box.classList.toggle("wide", !riders);
    box.innerHTML = head + rows.map((r) => {
      const color = /^#[0-9a-f]{6}$/i.test(r.color) ? r.color : "#52525B";
      const fallback = esc(r.number ?? "");
      const image = r.image
        ? `<img src="${esc(r.image)}" alt="${esc(r.name)}" loading="lazy" data-fallback="${fallback}">`
        : fallback;
      return `<div class="st-row">
        <span class="st-pos">${esc(num(r.position))}</span>
        <span class="${riders ? "st-photo" : "st-bike"}" style="--team:${color}">${image}</span>
        <span class="st-name"><strong>${esc(r.name)}</strong><small>${esc(r.sub)}</small></span>
        <span>${esc(num(r.w))}</span><span>${esc(num(r.pod))}</span><span>${esc(num(r.sw))}</span>
        <span class="st-pts">${esc(r.points)}</span>
        <span class="st-diff">${r.diff ? esc(r.diff) : "—"}</span>
      </div>`;
    }).join("");
    // Foto gagal dimuat: tampilkan nomor pembalap sebagai gantinya.
    box.querySelectorAll("img").forEach((img) => {
      img.onerror = () => img.replaceWith(img.dataset.fallback);
    });
  }

  /** Grafik garis poin kumulatif 5 besar; ketuk/geser untuk melihat per seri. */
  function renderChart(box, data) {
    const { rounds, series } = data;
    if (!rounds.length) {
      box.innerHTML = '<p class="muted">Belum ada hasil untuk digambar.</p>';
      return;
    }
    const W = 340, H = 250, left = 30, right = 34, top = 10, bottom = 22;
    const peak = Math.max(1, ...series.flatMap((s) => s.values));
    const magnitude = 10 ** Math.floor(Math.log10(peak / 4 || 1));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((v) => v * 4 >= peak);
    const x = (i) => left + (rounds.length === 1 ? 0.5 : i / (rounds.length - 1)) * (W - left - right);
    const y = (v) => H - bottom - (v / (step * 4)) * (H - top - bottom);

    let svg = "";
    for (let k = 0; k <= 4; k++) {
      svg += `<line class="grid-line" x1="${left}" x2="${W - right}" y1="${y(k * step)}" y2="${y(k * step)}"/>
        <text x="${left - 5}" y="${y(k * step) + 3}" text-anchor="end">${k * step}</text>`;
    }
    const every = Math.ceil(rounds.length / 7);
    rounds.forEach((code, i) => {
      if (i % every === 0) svg += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${esc(code)}</text>`;
    });
    svg += `<line class="cursor" id="cursor" y1="${top}" y2="${H - bottom}"/>`;
    series.forEach((s, n) => {
      const points = s.values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
      const last = s.values.length - 1;
      svg += `<polyline class="series" points="${points}" stroke="${SERIES_COLORS[n]}"/>
        <circle cx="${x(last)}" cy="${y(s.values[last])}" r="4" fill="${SERIES_COLORS[n]}" stroke="#111114" stroke-width="2"/>`;
    });
    // Label ujung garis, digeser agar tidak saling menimpa.
    let previous = -Infinity;
    series.map((s, n) => ({ color: SERIES_COLORS[n], text: s.number ?? s.name.slice(0, 3).toUpperCase(), y: y(s.values[s.values.length - 1]) }))
      .sort((a, b) => a.y - b.y)
      .forEach((label) => {
        previous = Math.max(label.y, previous + 11);
        svg += `<rect x="${W - right + 7}" y="${previous - 4}" width="3" height="8" rx="1.5" fill="${label.color}"/>
          <text class="end-label" x="${W - right + 13}" y="${previous + 3}">${esc(label.text)}</text>`;
      });

    box.innerHTML = `<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Poin kumulatif 5 besar">${svg}</svg></div>
      <div class="legend" id="legend"></div>`;

    const show = (index) => {
      const cursor = box.querySelector("#cursor");
      cursor.setAttribute("x1", x(index));
      cursor.setAttribute("x2", x(index));
      box.querySelector("#legend").innerHTML = `<h4>Setelah seri ${esc(rounds[index])}</h4>` +
        series.map((s, n) => ({ s, n })).sort((a, b) => b.s.values[index] - a.s.values[index])
          .map(({ s, n }) => `<div><i style="background:${SERIES_COLORS[n]}"></i>
            <span>${esc(s.name)}</span><strong>${esc(s.values[index])}</strong></div>`).join("");
    };
    const element = box.querySelector("svg");
    const track = (e) => {
      const bounds = element.getBoundingClientRect();
      const px = ((e.clientX - bounds.left) / bounds.width) * W;
      const ratio = (px - left) / (W - left - right);
      show(Math.max(0, Math.min(rounds.length - 1, Math.round(ratio * (rounds.length - 1)))));
    };
    element.addEventListener("pointerdown", track);
    element.addEventListener("pointermove", track);
    show(rounds.length - 1);
  }

  /** Kelas aktif dipakai bersama oleh Home dan Standings. */
  function setCategory(category) {
    state.category = category;
    document.body.dataset.class = category;
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.class === category));
    loadSessions();
    if (state.view === "standings") loadStandings();
  }

  /** Tombol pilihan (Riders/Teams/Constr. dan Table/Chart). */
  function bindChips(id, key) {
    $(id).addEventListener("click", (e) => {
      const chip = e.target.closest("button[data-value]");
      if (!chip) return;
      standings[key] = chip.dataset.value;
      $(id).querySelectorAll(".chip").forEach((c) => c.classList.toggle("active", c === chip));
      loadStandings();
    });
  }

  /* ---------- Widget sirkuit & hasil ---------- */

  function renderCircuit(event) {
    const box = $("circuit");
    box.hidden = !event;
    if (!event) return;
    const c = event.circuit;
    const layout = c.layout_svg || c.layout_png;
    const stat = (title, value, unit = "") =>
      `<div><span>${title}</span><strong>${value == null ? "–" : esc(value) + unit}</strong></div>`;
    box.innerHTML = `
      <h3>Circuit Info</h3>
      <div class="circuit-top">
        <div class="layout">${layout ? `<img id="layoutImg" src="${esc(layout)}" alt="Layout sirkuit">` : "–"}</div>
        <div class="circuit-name">
          ${event.flag ? `<img src="${esc(event.flag)}" alt="Bendera">` : ""}
          <strong>${esc(c.name)}</strong><small>${esc(c.address || c.country)}</small>
        </div>
      </div>
      <div class="stats">
        ${stat("Panjang", c.length_km, " km")}
        ${stat("Kapasitas", c.capacity == null ? null : c.capacity.toLocaleString("en-US"))}
        ${stat("Tikungan", c.corners)}
        ${stat("Kiri / Kanan", c.left == null || c.right == null ? null : `${c.left} / ${c.right}`)}
        ${stat("Trek lurus", c.straight_m, " m")}
        ${stat("Dibangun", c.built)}
      </div>
      ${c.about ? `<details><summary>Tentang sirkuit</summary><p>${esc(c.about.replace(/<[^>]*>/g, " "))}</p></details>` : ""}`;

    const img = $("layoutImg");
    if (img && c.layout_svg && c.layout_png) {
      // Ketuk untuk berganti antara layout beranotasi (SVG) dan polos (PNG).
      img.onclick = () => { img.src = img.getAttribute("src") === c.layout_svg ? c.layout_png : c.layout_svg; };
      img.onerror = () => { img.onerror = null; img.src = c.layout_png; };
    }
  }

  async function renderResults(sessionId, year, token) {
    const box = $("results");
    box.hidden = !sessionId;
    if (!sessionId) return;
    // Hasil disembunyikan dulu agar tidak jadi spoiler sebelum menonton.
    box.innerHTML = '<h3>Hasil Sesi</h3><button class="glass row"><span>Tampilkan hasil (spoiler)</span><b>›</b></button>';
    box.querySelector("button").onclick = async () => {
      box.innerHTML = '<h3>Hasil Sesi</h3><p class="muted">Memuat…</p>';
      try {
        const rows = await api(`/api/classification?session=${encodeURIComponent(sessionId)}&year=${year}`);
        if (token !== playerToken) return;
        box.innerHTML = "<h3>Hasil Sesi</h3>" + (rows.length ? rows.map((r) => `
          <div class="result"><b>${esc(r.position ?? "–")}</b>
            <div>${esc(r.rider)}<small>${esc(r.team)}</small></div>
            <i>${esc(r.position === 1 || !r.gap ? r.time : "+" + r.gap)}</i></div>`).join("")
          : '<p class="muted">Hasil belum tersedia.</p>');
      } catch (error) {
        if (token === playerToken) box.innerHTML = `<h3>Hasil Sesi</h3><p class="muted">${esc(error.message)}</p>`;
      }
    };
  }

  /* ---------- Video player ---------- */

  function stageMessage(html) {
    $("stageMessage").innerHTML = html || "";
    $("stageMessage").hidden = !html;
    $("controls").hidden = Boolean(html);
  }

  function destroyVideo() {
    saveProgress();
    resumeKey = null;
    if (hls) { hls.destroy(); hls = null; }
    video.pause();
    video.removeAttribute("src");
    video.load();
    $("qualityMenu").hidden = true;
    $("seek").value = 0;
    $("seek").style.setProperty("--pos", "0%");
    $("time").textContent = "00:00 / 00:00";
  }

  function playVideo() {
    const promise = video.play();
    if (promise) promise.catch(() => updateButtons());
  }

  function loadSource(url) {
    const isHls = url.split("?")[0].toLowerCase().endsWith(".m3u8");
    if (isHls && window.Hls && Hls.isSupported()) {
      let networkRetries = 0;
      let mediaRetries = 0;
      hls = new Hls({ capLevelToPlayerSize: false });
      hls.on(Hls.Events.MANIFEST_PARSED, () => { renderQuality(); playVideo(); });
      hls.on(Hls.Events.LEVEL_SWITCHED, renderQuality);
      hls.on(Hls.Events.ERROR, (_, data) => {
        if (!data.fatal) return;
        const manifestFailed = String(data.details).startsWith("manifest");
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR && !manifestFailed && networkRetries++ < 3) {
          hls.startLoad();
        } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR && mediaRetries++ < 2) {
          hls.recoverMediaError();
        } else {
          hls.destroy();
          hls = null;
          stageMessage("Video gagal diputar. Periksa file atau koneksi Anda.");
        }
      });
      hls.loadSource(url);
      hls.attachMedia(video);
    } else if (isHls && !video.canPlayType("application/vnd.apple.mpegurl")) {
      stageMessage("Pemutar HLS belum termuat. Sambungkan internet lalu muat ulang aplikasi.");
    } else {
      video.src = url;
      renderQuality();
      playVideo();
    }
  }

  /** Mengisi menu kualitas dari level yang ada di manifest m3u8. */
  function renderQuality() {
    const menu = $("qualityMenu");
    let options = [{ level: -1, text: "Auto" }];
    if (hls && hls.levels.length) {
      const active = hls.levels[hls.currentLevel];
      if (hls.autoLevelEnabled && active && active.height) options[0].text = `Auto (${active.height}p)`;
      options = options.concat(hls.levels
        .map((l, i) => ({ level: i, height: l.height || 0,
          text: l.height ? `${l.height}p` : `${Math.round(l.bitrate / 1000)} kbps` }))
        .sort((a, b) => b.height - a.height));
    } else {
      options = [{ level: -1, text: "Asli (1 resolusi)" }];
    }
    const selected = hls && !hls.autoLevelEnabled ? hls.manualLevel : -1;
    menu.innerHTML = options.map((o) =>
      `<button data-level="${o.level}" class="${o.level === selected ? "active" : ""}">${esc(o.text)}</button>`).join("");
  }

  function openPlayer({ title, url, sessionId, year, event, hint }) {
    destroyVideo();
    playerToken += 1;
    $("playerTitle").textContent = title;
    document.querySelector(".player-body").scrollTop = 0;
    $("player").classList.add("open");
    $("player").setAttribute("aria-hidden", "false");
    renderCircuit(event);
    renderResults(sessionId, year, playerToken);
    updateButtons();
    if (url) {
      stageMessage("");
      resumeKey = url === TEST_STREAM ? null : `pos:${url}`;
      loadSource(url);
      showControls();
    } else {
      stage.classList.remove("idle");
      stageMessage(`Belum ada file video untuk sesi ini.<br><code>${esc(hint)}</code><br><a href="${VIDEOPASS}">Tonton di VideoPass resmi</a>`);
    }
  }

  function closePlayer() {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    destroyVideo();
    playerToken += 1;
    $("player").classList.remove("open");
    $("player").setAttribute("aria-hidden", "true");
  }

  const clock = (seconds) => {
    if (!isFinite(seconds)) return "00:00";
    const total = Math.floor(seconds);
    const h = Math.floor(total / 3600);
    const m = String(Math.floor(total / 60) % 60).padStart(2, "0");
    const s = String(total % 60).padStart(2, "0");
    return h ? `${h}:${m}:${s}` : `${m}:${s}`;
  };

  function updateButtons() {
    $("playBtn").innerHTML = video.paused ? ICONS.play : ICONS.pause;
    $("muteBtn").innerHTML = video.muted ? ICONS.muted : ICONS.sound;
  }

  function saveProgress() {
    if (resumeKey && video.currentTime > 5 && isFinite(video.duration)) {
      store.set(resumeKey, video.currentTime < video.duration - 15 ? video.currentTime : 0);
    }
  }

  function showControls() {
    stage.classList.remove("idle");
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      if (!video.paused && $("qualityMenu").hidden) stage.classList.add("idle");
    }, 3000);
  }

  function toggleFullscreen() {
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    } else if (stage.requestFullscreen) {
      stage.requestFullscreen().catch(() => {});
    }
  }

  /* ---------- Event ---------- */

  const actions = {
    search() { showView("calendar"); $("search").focus(); },
    reload() { location.reload(); },
    "refresh-standings"() { loadStandings(true); },
    close: closePlayer,
    fullscreen: toggleFullscreen,
    play() { if (video.paused) playVideo(); else video.pause(); },
    mute() { video.muted = !video.muted; updateButtons(); },
    quality() { renderQuality(); $("qualityMenu").hidden = !$("qualityMenu").hidden; },
    "test-player"() { openPlayer({ title: "UJI PLAYER", url: TEST_STREAM }); }
  };

  document.addEventListener("click", (e) => {
    const action = e.target.closest("[data-action]");
    if (action) actions[action.dataset.action]();
  });

  $("qualityMenu").addEventListener("click", (e) => {
    const button = e.target.closest("[data-level]");
    if (!button) return;
    if (hls) hls.currentLevel = Number(button.dataset.level);
    $("qualityMenu").hidden = true;
    showControls();
  });

  let lastTap = 0;
  video.addEventListener("click", (e) => {
    $("qualityMenu").hidden = true;
    const now = Date.now();
    if (now - lastTap < 300) {
      // Ketuk dua kali: mundur/maju 10 detik.
      const direction = e.offsetX < video.clientWidth / 2 ? -10 : 10;
      video.currentTime = Math.max(0, video.currentTime + direction);
    }
    lastTap = now;
    showControls();
  });
  stage.addEventListener("pointerdown", () => showControls());

  video.addEventListener("play", () => { updateButtons(); showControls(); });
  video.addEventListener("pause", () => { updateButtons(); showControls(); saveProgress(); });
  video.addEventListener("loadedmetadata", () => {
    const saved = Number(resumeKey && store.get(resumeKey));
    if (saved > 0 && saved < video.duration) video.currentTime = saved;
  });
  video.addEventListener("error", () => {
    if (video.getAttribute("src") && !hls) stageMessage("Format video tidak didukung. Gunakan MP4 (H.264/AAC) atau HLS.");
  });
  video.addEventListener("timeupdate", () => {
    const ratio = video.duration ? video.currentTime / video.duration : 0;
    $("seek").value = Math.round(ratio * 1000) || 0;
    $("seek").style.setProperty("--pos", `${(ratio || 0) * 100}%`);
    $("time").textContent = `${clock(video.currentTime)} / ${clock(video.duration)}`;
  });
  $("seek").addEventListener("input", () => {
    if (isFinite(video.duration)) video.currentTime = ($("seek").value / 1000) * video.duration;
    showControls();
  });

  $("season").addEventListener("change", (e) => loadEvents(e.target.value));
  $("eventSelect").addEventListener("change", (e) => selectEvent(e.target.value));
  $("search").addEventListener("input", renderCalendar);
  $("dots").addEventListener("click", (e) => {
    const dot = e.target.closest("[data-event]");
    if (dot) selectEvent(dot.dataset.event);
  });
  $("calendar").addEventListener("click", (e) => {
    const row = e.target.closest("[data-event]");
    if (row) { selectEvent(row.dataset.event); showView("home"); }
  });
  ["tabs", "standingsTabs"].forEach((id) => $(id).addEventListener("click", (e) => {
    const tab = e.target.closest("button[data-class]");
    if (tab) setCategory(tab.dataset.class);
  }));
  $("standingsSeason").addEventListener("change", (e) => {
    standings.year = Number(e.target.value);
    loadStandings();
  });
  bindChips("standingsType", "type");
  bindChips("standingsMode", "mode");
  $("nav").addEventListener("click", (e) => {
    const button = e.target.closest("[data-view]");
    if (button) showView(button.dataset.view);
  });
  document.addEventListener("visibilitychange", () => { if (document.hidden) video.pause(); });

  /** Dipanggil tombol Back Android. true = sudah ditangani di web. */
  window.appBack = () => {
    if (!$("qualityMenu").hidden) { $("qualityMenu").hidden = true; return true; }
    if ($("player").classList.contains("open")) { closePlayer(); return true; }
    if (state.view !== "home") { showView("home"); return true; }
    return false;
  };

  updateButtons();
  loadSeasons();
})();
