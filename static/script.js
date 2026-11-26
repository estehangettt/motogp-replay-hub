"use strict";

(() => {
  const $ = (selector) => document.querySelector(selector);
  const state = {
    season: new Date().getFullYear(),
    selectedClass: "MotoGP",
    events: [],
    selectedEvent: null,
    catalog: [],
    hls: null,
    levels: [],
    activeQuality: -1,
    toastTimer: null,
  };

  const video = $("#videoPlayer");
  const overlay = $("#playerOverlay");

  function showToast(message) {
    const toast = $("#toast");
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => toast.classList.remove("show"), 2800);
  }

  async function fetchJson(url) {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[char]);
  }

  function formatDate(value) {
    if (!value) return "DATE TBA";
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? "DATE TBA"
      : date.toLocaleDateString("en-GB", { day: "2-digit", month: "short" }).toUpperCase();
  }

  function eventName(event) {
    return event?.sponsored_name || event?.name || event?.circuit?.name || "Grand Prix";
  }

  async function loadSeasons() {
    try {
      const seasons = await fetchJson("/api/motogp/seasons");
      const list = Array.isArray(seasons) ? seasons : [];
      const select = $("#seasonSelect");
      select.innerHTML = "";
      list.sort((a, b) => Number(b.year || 0) - Number(a.year || 0));
      list.forEach((season) => {
        if (!season.year) return;
        const option = document.createElement("option");
        option.value = String(season.year);
        option.textContent = String(season.year);
        if (season.current || Number(season.year) === state.season) option.selected = true;
        select.append(option);
      });
      if (select.value) state.season = Number(select.value);
      await loadEvents();
    } catch (error) {
      showToast(`Season API: ${error.message}`);
      await loadEvents();
    }
  }

  async function loadEvents() {
    const strip = $("#eventStrip");
    strip.innerHTML = '<div class="loading-line">Memuat kalender…</div>';
    try {
      const events = await fetchJson(`/api/motogp/events?seasonYear=${encodeURIComponent(state.season)}`);
      state.events = Array.isArray(events) ? events : [];
      strip.innerHTML = "";
      if (!state.events.length) {
        strip.innerHTML = '<div class="loading-line">Belum ada event GP untuk musim ini.</div>';
        return;
      }
      state.events.forEach((event, index) => {
        const button = document.createElement("button");
        button.className = `event-chip${index === 0 ? " active" : ""}`;
        button.innerHTML = `<b>${escapeHtml(eventName(event))}</b><small>${escapeHtml(formatDate(event.date_start))} · ${escapeHtml(event.circuit?.country || "")}</small>`;
        button.addEventListener("click", () => {
          document.querySelectorAll(".event-chip").forEach((item) => item.classList.remove("active"));
          button.classList.add("active");
          selectEvent(event);
        });
        strip.append(button);
      });
      selectEvent(state.events[0]);
    } catch (error) {
      strip.innerHTML = `<div class="loading-line">${escapeHtml(error.message)}</div>`;
    }
  }

  function selectEvent(event) {
    state.selectedEvent = event;
    const circuit = event?.circuit || {};
    $("#heroTitle").innerHTML = `${escapeHtml(eventName(event)).toUpperCase()}<br><em>RACE WEEKEND</em>`;
    $("#heroSubtitle").textContent = `${circuit.name || "MotoGP"} · ${circuit.country || "World Championship"}`;
    renderCircuit(event);
  }

  function renderCircuit(event) {
    const circuit = event?.circuit || {};
    const track = circuit.track || {};
    const assets = track.assets || {};
    const simplePath = assets.simple?.path || assets.info?.path || "";
    const flag = (event?.assets || []).find((item) => item.type === "FLAG")?.path || "";
    $("#circuitName").textContent = circuit.name || "Circuit data unavailable";
    $("#circuitLocation").textContent = [circuit.address, circuit.city, circuit.country].filter(Boolean).join(" · ") || "Location not supplied";
    $("#trackLength").textContent = track.lenght_units?.kiloMeters
      ? `${Number(track.lenght_units.kiloMeters).toFixed(2)} km`
      : (track.lenght ? `${(Number(track.lenght) / 1000).toFixed(2)} km` : "—");
    $("#capacity").textContent = circuit.capacity ? Number(circuit.capacity).toLocaleString("en-US") : "—";
    const left = Number.parseInt(track.left_corners, 10);
    const right = Number.parseInt(track.right_corners, 10);
    $("#corners").textContent = Number.isFinite(left) && Number.isFinite(right) ? `${left + right} (${left}L / ${right}R)` : "—";
    $("#opened").textContent = circuit.constructed || "—";
    const image = $("#trackImage");
    image.hidden = !simplePath;
    image.src = simplePath;
    $("#trackFallback").hidden = Boolean(simplePath);
    const flagImage = $("#countryFlag");
    flagImage.hidden = !flag;
    flagImage.src = flag;
    const descriptions = Array.isArray(circuit.circuit_descriptions) ? circuit.circuit_descriptions : [];
    const description = descriptions.find((item) => item.language === "en") || descriptions[0];
    $("#circuitDescription").textContent = description?.description || "";
  }

  async function loadCatalog() {
    const url = $("#categoryUrl").value.trim();
    if (!url) return showToast("Masukkan URL kategori replay.");
    $("#catalogStatus").textContent = "Mengambil katalog…";
    $("#loadCatalog").disabled = true;
    try {
      const data = await fetchJson(`/api/katalog?url=${encodeURIComponent(url)}`);
      state.catalog = Array.isArray(data) ? data : [];
      renderSessions();
      $("#catalogStatus").textContent = `${state.catalog.length} sesi ditemukan.`;
    } catch (error) {
      $("#catalogStatus").textContent = error.message;
      showToast(error.message);
    } finally {
      $("#loadCatalog").disabled = false;
    }
  }

  function classMatches(item) {
    const category = String(item.kelas || "").toLowerCase();
    const selected = state.selectedClass.toLowerCase();
    return category.includes(selected) || category === "lainnya" || category === "";
  }

  function renderSessions() {
    const grid = $("#sessionGrid");
    const sessions = state.catalog.filter(classMatches);
    $("#sessionCount").textContent = `${sessions.length} sessions`;
    grid.innerHTML = "";
    if (!sessions.length) {
      grid.innerHTML = '<div class="empty-state glass"><span class="empty-icon">▶</span><b>No sessions loaded</b><p>Muat URL kategori replay untuk melihat sesi kelas ini.</p></div>';
      return;
    }
    sessions.forEach((item) => {
      const button = document.createElement("button");
      button.className = "session-card";
      button.innerHTML = `<b>${escapeHtml(item.sesi || "Replay")}</b><small>${escapeHtml(item.kelas || state.selectedClass)} · TAP TO WATCH</small><span class="play-circle">›</span>`;
      button.addEventListener("click", () => openPlayer(item));
      grid.append(button);
    });
  }

  function setPlayerMessage(message) {
    $("#videoMessage").textContent = message;
    $("#videoMessage").hidden = !message;
  }

  function resetVideo() {
    if (state.hls) {
      state.hls.destroy();
      state.hls = null;
    }
    video.pause();
    video.removeAttribute("src");
    video.load();
    state.levels = [];
    state.activeQuality = -1;
    $("#qualityButton").textContent = "AUTO⌄";
    $("#qualityMenu").hidden = true;
    $("#seekBar").value = "0";
  }

  async function openPlayer(item) {
    resetVideo();
    overlay.classList.add("open");
    overlay.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    $("#playingTitle").textContent = item.judul_lengkap || item.sesi || "MotoGP Replay";
    $("#playingSubtitle").textContent = `${item.kelas || state.selectedClass} · ${state.selectedEvent ? eventName(state.selectedEvent) : "Replay"}`;
    setPlayerMessage("RESOLVING STREAM…");
    try {
      const data = await fetchJson(`/get_stream?url=${encodeURIComponent(item.url)}`);
      if (!data.m3u8) throw new Error(data.error || "Stream tidak tersedia.");
      const source = `/proxy?url=${encodeURIComponent(data.m3u8)}`;
      if (window.Hls && Hls.isSupported()) {
        state.hls = new Hls({ enableWorker: true, capLevelToPlayerSize: true, maxBufferLength: 30 });
        state.hls.on(Hls.Events.MANIFEST_PARSED, (_event, payload) => {
          state.levels = payload.levels || [];
          buildQualityMenu();
          setPlayerMessage("");
          video.play().catch(() => setPlayerMessage("TAP PLAY TO START"));
        });
        state.hls.on(Hls.Events.ERROR, (_event, dataError) => {
          if (dataError.fatal) {
            setPlayerMessage("STREAM ERROR");
            showToast(`HLS: ${dataError.details || dataError.type}`);
          }
        });
        state.hls.loadSource(source);
        state.hls.attachMedia(video);
      } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
        video.src = source;
        setPlayerMessage("");
        video.play().catch(() => setPlayerMessage("TAP PLAY TO START"));
      } else {
        throw new Error("Browser ini tidak mendukung HLS.");
      }
    } catch (error) {
      setPlayerMessage("UNABLE TO PLAY");
      showToast(error.message);
    }
  }

  function buildQualityMenu() {
    const menu = $("#qualityMenu");
    menu.querySelectorAll("button[data-dynamic]").forEach((button) => button.remove());
    const standard = [1080, 720, 480, 360];
    const available = [...new Set(state.levels.map((level) => Number(level.height || 0)))]
      .filter((height) => standard.includes(height)).sort((a, b) => b - a);
    menu.querySelectorAll("button[data-quality]").forEach((button) => {
      const quality = Number(button.dataset.quality);
      if (quality === -1) {
        button.hidden = false;
        button.onclick = () => chooseQuality(-1);
        return;
      }
      button.hidden = !available.includes(quality);
      if (!button.hidden) button.onclick = () => chooseQuality(quality);
    });
    available.filter((height) => !menu.querySelector(`button[data-quality="${height}"]`)).forEach((height) => {
      const button = document.createElement("button");
      button.dataset.quality = String(height);
      button.dataset.dynamic = "true";
      button.textContent = `${height}p`;
      button.addEventListener("click", () => chooseQuality(height));
      menu.append(button);
    });
    menu.querySelectorAll("button[data-quality]").forEach((button) => {
      button.classList.toggle("selected", Number(button.dataset.quality) === -1);
    });
  }

  function chooseQuality(height) {
    if (!state.hls) {
      showToast("Quality selector tersedia setelah manifest HLS terbaca.");
      return;
    }
    if (height === -1) {
      state.hls.currentLevel = -1;
      state.activeQuality = -1;
      $("#qualityButton").textContent = "AUTO⌄";
    } else {
      const index = state.levels.findIndex((level) => Math.round(level.height || 0) === height);
      if (index < 0) return showToast(`${height}p tidak tersedia di manifest.`);
      state.hls.currentLevel = index;
      state.activeQuality = height;
      $("#qualityButton").textContent = `${height}P⌄`;
    }
    $("#qualityMenu").hidden = true;
    $("#qualityMenu").querySelectorAll("button[data-quality]").forEach((button) => {
      button.classList.toggle("selected", Number(button.dataset.quality) === height);
    });
  }

  function closePlayer() {
    resetVideo();
    overlay.classList.remove("open");
    overlay.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }

  function formatTime(seconds) {
    if (!Number.isFinite(seconds)) return "00:00";
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }

  function bindPlayerControls() {
    $("#playButton").addEventListener("click", () => {
      if (video.paused) video.play().catch(() => showToast("Video belum bisa diputar."));
      else video.pause();
    });
    video.addEventListener("play", () => { $("#playButton").textContent = "Ⅱ"; });
    video.addEventListener("pause", () => { $("#playButton").textContent = "▶"; });
    video.addEventListener("timeupdate", () => {
      $("#currentTime").textContent = formatTime(video.currentTime);
      $("#duration").textContent = formatTime(video.duration);
      if (Number.isFinite(video.duration) && video.duration > 0) {
        $("#seekBar").value = String(Math.round((video.currentTime / video.duration) * 1000));
      }
    });
    $("#seekBar").addEventListener("input", (event) => {
      if (Number.isFinite(video.duration) && video.duration > 0) {
        video.currentTime = (Number(event.target.value) / 1000) * video.duration;
      }
    });
    $("#muteButton").addEventListener("click", () => {
      video.muted = !video.muted;
      $("#muteButton").textContent = video.muted ? "×" : "◖";
    });
    $("#qualityButton").addEventListener("click", () => {
      $("#qualityMenu").hidden = !$("#qualityMenu").hidden;
    });
    $("#closePlayer").addEventListener("click", closePlayer);
    $("#fullscreenButton").addEventListener("click", () => {
      const target = $(".video-stage");
      if (document.fullscreenElement) document.exitFullscreen?.();
      else target.requestFullscreen?.().catch(() => showToast("Fullscreen tidak tersedia."));
    });
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) closePlayer();
    });
  }

  function bindUI() {
    $("#seasonSelect").addEventListener("change", (event) => {
      state.season = Number(event.target.value);
      loadEvents();
    });
    $("#refreshEvents").addEventListener("click", loadEvents);
    $("#loadCatalog").addEventListener("click", loadCatalog);
    $("#categoryUrl").addEventListener("keydown", (event) => {
      if (event.key === "Enter") loadCatalog();
    });
    document.querySelectorAll(".class-tab").forEach((button) => {
      button.addEventListener("click", () => {
        document.querySelectorAll(".class-tab").forEach((tab) => tab.classList.remove("active"));
        button.classList.add("active");
        state.selectedClass = button.dataset.class;
        renderSessions();
      });
    });
    $("#searchToggle").addEventListener("click", () => $("#categoryUrl").focus());
    bindPlayerControls();
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindUI();
    loadSeasons();
  });
})();
