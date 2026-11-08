// AERO Player — web: burbujas, idioma, capturas, enlaces de descarga desde GitHub Releases.
(function () {
  "use strict";
  var cfg = window.AERO_SITE || {};
  var repoUrl = "https://github.com/" + cfg.owner + "/" + cfg.repo;
  var configured = cfg.owner && cfg.owner.indexOf("TU_USUARIO") !== 0;

  // ------------------------------------------------------------ burbujas (respetan «reducir movimiento»)
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var box = document.getElementById("bubbles");
  if (box && !reduce) {
    var n = window.innerWidth < 700 ? 10 : 22;
    for (var i = 0; i < n; i++) {
      var b = document.createElement("span");
      var size = 18 + Math.random() * 70;
      b.className = "bubble";
      b.style.width = b.style.height = size + "px";
      b.style.left = Math.random() * 100 + "%";
      b.style.animationDuration = 14 + Math.random() * 22 + "s";
      b.style.animationDelay = -Math.random() * 30 + "s";
      b.style.setProperty("--sway", (Math.random() * 80 - 40).toFixed(0) + "px");
      box.appendChild(b);
    }
  }

  // ------------------------------------------------------------ idioma (español / inglés)
  var EN = {
    "nav.features": "Features", "nav.shots": "Screenshots", "nav.download": "Download", "nav.faq": "FAQ",
    "hero.tagline": "Your music, videos and files, with the glass, sky and bubbles of Windows 7.",
    "hero.sub": "Player, universal viewer, editors, converter and much more. Free, open source and no telemetry.",
    "hero.download": "Download for Windows", "hero.source": "View the code on GitHub",
    "feat.title": "Everything in one app",
    "feat.player.t": "Player", "feat.player.d": "Music and video with a queue, subtitles, audio tracks, series with next episode and 11 visualizers that follow the real sound.",
    "feat.viewer.t": "Universal viewer", "feat.viewer.d": "Photos (HEIC and AVIF too), PDF, documents, spreadsheets, presentations, archives and disc images. Quick Look with Space from File Explorer.",
    "feat.editors.t": "Editors", "feat.editors.d": "Video editor with a timeline and effects, image editor with layers, AERO Paint, documents, spreadsheets, presentations and PDF to editable with OCR.",
    "feat.files.t": "Files", "feat.files.d": "File browser with the AERO icon family, lightning-fast global search, and nothing runs without your confirmation.",
    "feat.archive.t": "Compress and extract", "feat.archive.d": "ZIP, 7Z, RAR, TAR and ISO with AES-256 passwords, protection against dangerous paths and clean cancellation.",
    "feat.disc.t": "Disc images", "feat.disc.d": "Browse and extract ISO, IMG, BIN/CUE, NRG and MDF without mounting, or mount them with Windows whenever you want.",
    "feat.torrent.t": "BitTorrent downloads", "feat.torrent.d": "See the contents, pick files and download. Nothing starts on its own, nothing runs and no ports are opened. Can be turned off.",
    "feat.convert.t": "Batch converter", "feat.convert.d": "Images, audio, video and documents with profiles, pause and retry, never touching your originals.",
    "feat.windows.t": "Built into Windows", "feat.windows.d": "“Open with”, AERO icons in File Explorer, right-click menu and default apps, always with your permission.",
    "shots.title": "Screenshots",
    "perf.title": "Light and fast", "perf.d": "The parts that work hardest with thousands of files are written in Rust and use every CPU core without freezing the window.",
    "perf.n3": "2.9×", "perf.tags": "faster reading your music tags", "perf.scan": "faster scanning your library", "perf.search": "faster searching your whole disk", "perf.idle": "CPU when idle",
    "priv.title": "Truly yours", "priv.1": "No telemetry, no ads, no accounts.", "priv.2": "Open source (GPL-3.0): you can read and improve the code.",
    "priv.3": "It never moves, copies or changes your files without asking.", "priv.4": "The installer doesn't need administrator rights.",
    "priv.5": "In 7 languages: English, Spanish, German, Italian, Portuguese, Russian and Chinese.",
    "dl.title": "Download AERO Player", "dl.sub": "For 64-bit Windows 10 and Windows 11.",
    "dl.setup": "Installer", "dl.setup.d": "Recommended. Creates shortcuts and updates keeping your data.",
    "dl.portable": "Portable (ZIP)", "dl.portable.d": "Unzip and run AeroPlayer.exe. Installs nothing.",
    "dl.smartscreen": "The first time, Windows SmartScreen may warn you because the app isn't digitally signed yet: click “More info” › “Run anyway”. You can verify the file with the SHA-256 checksums on the release page.",
    "dl.all": "All releases and release notes", "dl.ffmpeg": "Converting video and audio requires FFmpeg (playback works without it).",
    "faq.title": "Frequently asked questions",
    "faq.q1": "Is it free?", "faq.a1": "Yes, completely. It's open source under the GPL-3.0 license: no ads, no subscriptions and no data collection.",
    "faq.q2": "Does it change my default apps?", "faq.a2": "Not on its own. AERO Player adds itself to “Open with” and you choose in Windows Settings whether to use it by default.",
    "faq.q3": "Why does SmartScreen warn me?", "faq.a3": "Because the executable isn't signed with a paid certificate yet. The code is public and every release publishes its SHA-256 checksums so you can verify it.",
    "faq.q4": "How do I uninstall it?", "faq.a4": "From Windows Settings › Apps › AERO Player. Your files are not touched.",
    "faq.q5": "Can I help or report a bug?", "faq.a5": "Of course! Open an issue on GitHub or suggest changes with a pull request.",
    "foot.1": "AERO Player is free software under the GPL-3.0-or-later license.",
    "foot.2": "Inspired by the Frutiger Aero aesthetic. Not affiliated with Microsoft. Windows is a trademark of Microsoft Corporation."
  };
  var ES = {};
  document.querySelectorAll("[data-i18n]").forEach(function (el) { ES[el.dataset.i18n] = el.textContent; });
  var lang = "es";
  try { lang = localStorage.getItem("aero-lang") || ""; } catch (e) { lang = ""; }
  if (!lang) lang = (navigator.language || "es").toLowerCase().indexOf("es") === 0 ? "es" : "en";

  var SHOTS = [
    ["inicio", "Inicio", "Home"], ["reproductor", "Reproductor", "Player"], ["biblioteca", "Biblioteca", "Library"],
    ["archivos", "Archivos", "Files"], ["visor", "Visor", "Viewer"], ["editor_video", "Editor de vídeo", "Video editor"],
    ["paint", "AERO Paint", "AERO Paint"], ["conversor", "Conversor", "Converter"], ["tema_naturaleza", "Temas", "Themes"]
  ];
  var tabs = document.getElementById("shot-tabs"), img = document.getElementById("shot-img"), title = document.getElementById("shot-title");
  var current = 0;
  function showShot(i) {
    current = i;
    img.src = "assets/capturas/" + SHOTS[i][0] + ".png";
    img.alt = "AERO Player — " + SHOTS[i][lang === "es" ? 1 : 2];
    title.textContent = "AERO Player — " + SHOTS[i][lang === "es" ? 1 : 2];
    tabs.querySelectorAll(".tab").forEach(function (t, k) { t.setAttribute("aria-selected", k === i ? "true" : "false"); });
  }
  function buildTabs() {
    tabs.innerHTML = "";
    SHOTS.forEach(function (s, i) {
      var t = document.createElement("button");
      t.type = "button"; t.className = "tab"; t.setAttribute("role", "tab");
      t.textContent = s[lang === "es" ? 1 : 2];
      t.addEventListener("click", function () { showShot(i); });
      tabs.appendChild(t);
    });
    showShot(current);
  }

  function applyLang() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      var k = el.dataset.i18n;
      el.textContent = lang === "en" ? (EN[k] || ES[k]) : ES[k];
    });
    document.getElementById("lang").textContent = lang === "es" ? "EN" : "ES";
    buildTabs();
    renderRelease();
  }
  document.getElementById("lang").addEventListener("click", function () {
    lang = lang === "es" ? "en" : "es";
    try { localStorage.setItem("aero-lang", lang); } catch (e) { /* sin almacenamiento: solo esta visita */ }
    applyLang();
  });

  // ------------------------------------------------------------ capturas a pantalla completa
  var lb = document.getElementById("lightbox");
  document.querySelectorAll(".win7 img").forEach(function (im) {
    im.addEventListener("click", function () { lb.querySelector("img").src = im.src; lb.hidden = false; });
  });
  lb.addEventListener("click", function () { lb.hidden = true; });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") lb.hidden = true; });

  // ------------------------------------------------------------ enlaces de GitHub y de descarga
  document.querySelectorAll("[data-gh-link]").forEach(function (a) { a.href = configured ? repoUrl : "#"; });
  document.querySelectorAll("[data-gh-releases]").forEach(function (a) { a.href = configured ? repoUrl + "/releases" : "#"; });
  var release = null;
  function mb(bytes) { return (bytes / 1048576).toFixed(0) + " MB"; }
  function renderRelease() {
    var v = release ? release.tag_name.replace(/^v/, "") : cfg.version;
    var line = (lang === "es" ? "Versión " : "Version ") + v + (lang === "es" ? " · Windows 10 y 11 · 64 bits" : " · Windows 10 and 11 · 64-bit");
    document.querySelectorAll("[data-version-line]").forEach(function (el) { el.textContent = line; });
    var assets = { setup: null, portable: null };
    if (release) {
      release.assets.forEach(function (a) {
        if (/setup\.exe$/i.test(a.name)) assets.setup = a;
        else if (/portable\.zip$/i.test(a.name)) assets.portable = a;
      });
    }
    ["setup", "portable"].forEach(function (k) {
      var a = assets[k];
      var fallback = configured ? repoUrl + "/releases/latest" : "#descargar";
      document.querySelectorAll('[data-download="' + k + '"]').forEach(function (el) {
        if (el.classList.contains("btn-aero") && !a) { el.href = configured ? fallback : "#descargar"; return; }
        el.href = a ? a.browser_download_url : fallback;
      });
      document.querySelectorAll('[data-size="' + k + '"]').forEach(function (el) {
        el.textContent = a ? a.name + " · " + mb(a.size) : (lang === "es" ? "Próximamente en GitHub Releases" : "Coming soon on GitHub Releases");
      });
    });
  }
  if (configured && window.fetch) {
    fetch("https://api.github.com/repos/" + cfg.owner + "/" + cfg.repo + "/releases/latest")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { if (j && j.assets) { release = j; renderRelease(); } })
      .catch(function () { /* sin conexión con la API: quedan los enlaces a /releases/latest */ });
  }
  applyLang();
})();
