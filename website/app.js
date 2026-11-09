// AERO Player — web: idiomas, capturas por idioma, burbujas, parallax, animaciones y descargas desde GitHub.
(function () {
  "use strict";
  var cfg = window.AERO_SITE || {};
  var I18N = window.AERO_I18N || {};
  var LANGS = window.AERO_LANGS || { es: "Español" };
  var NAMES = window.AERO_SHOT_NAMES || {};
  var repoUrl = "https://github.com/" + cfg.owner + "/" + cfg.repo;
  var configured = cfg.owner && cfg.owner.indexOf("TU_USUARIO") !== 0;
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  // ------------------------------------------------------------ idioma
  var ES = {};
  $$("[data-i18n]").forEach(function (el) { ES[el.dataset.i18n] = el.textContent; });
  function pickLang() {
    var saved = "";
    try { saved = localStorage.getItem("aero-lang") || ""; } catch (e) { saved = ""; }
    if (LANGS[saved]) return saved;
    var nav = (navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || "es"]);
    for (var i = 0; i < nav.length; i++) {
      var c = String(nav[i]).toLowerCase().slice(0, 2);
      if (LANGS[c]) return c;
    }
    return "en";
  }
  var lang = pickLang();
  var sel = $("#lang");
  Object.keys(LANGS).forEach(function (k) {
    var o = document.createElement("option");
    o.value = k; o.textContent = LANGS[k];
    sel.appendChild(o);
  });
  function t(key) { return lang === "es" ? ES[key] : ((I18N[lang] || {})[key] || (I18N.en || {})[key] || ES[key]); }

  // ------------------------------------------------------------ capturas (en el idioma de la página)
  var SHOTS = ["inicio", "reproductor", "letra", "biblioteca", "archivos", "visor", "editor_video", "paint", "conversor", "tema_naturaleza"];
  var tabs = $("#shot-tabs"), img = $("#shot-img"), img2 = $("#shot-img2"), title = $("#shot-title"), dots = $("#shot-dots");
  var current = 0, timer = null, paused = false;
  function shotSrc(name) { return "assets/capturas/" + lang + "/" + name + ".webp"; }
  function shotName(name) { return (NAMES[name] || {})[lang] || (NAMES[name] || {}).en || name; }
  function showShot(i, animate) {
    current = (i + SHOTS.length) % SHOTS.length;
    var name = SHOTS[current], src = shotSrc(name);
    title.textContent = "AERO Player — " + shotName(name);
    img.alt = "AERO Player — " + shotName(name);
    if (animate && !reduce) {
      img2.src = src;
      img2.onload = function () {
        img2.classList.add("show");
        setTimeout(function () { img.src = src; img2.classList.remove("show"); }, 520);
      };
    } else {
      img.src = src;
      img2.onload = null;
      img2.src = src;          // la capa del fundido siempre en el idioma actual
    }
    $$(".tab", tabs).forEach(function (b, k) { b.setAttribute("aria-selected", k === current ? "true" : "false"); });
    $$("i", dots).forEach(function (d, k) { d.classList.toggle("on", k === current); });
  }
  function buildTabs() {
    tabs.innerHTML = ""; dots.innerHTML = "";
    SHOTS.forEach(function (s, i) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "tab"; b.setAttribute("role", "tab");
      b.textContent = shotName(s);
      b.addEventListener("click", function () { showShot(i, true); restart(); });
      tabs.appendChild(b);
      dots.appendChild(document.createElement("i"));
    });
    showShot(current, false);
  }
  function restart() {
    if (reduce) return;
    clearInterval(timer);
    timer = setInterval(function () { if (!paused && !document.hidden) showShot(current + 1, true); }, 5200);
  }
  var frame = $("#shot-frame");
  frame.addEventListener("mouseenter", function () { paused = true; });
  frame.addEventListener("mouseleave", function () { paused = false; });
  document.addEventListener("keydown", function (e) {
    var r = frame.getBoundingClientRect();
    if (r.top > window.innerHeight || r.bottom < 0) return;
    if (e.key === "ArrowRight") { showShot(current + 1, true); restart(); }
    if (e.key === "ArrowLeft") { showShot(current - 1, true); restart(); }
  });

  function applyLang() {
    document.documentElement.lang = lang;
    sel.value = lang;
    $$("[data-i18n]").forEach(function (el) { el.textContent = t(el.dataset.i18n); });
    $$("[data-shot]").forEach(function (el) { el.src = shotSrc(el.dataset.shot); });
    var bubbleTip = t("bubble.tip");
    if (bubbleTip) $("#bubbles").title = bubbleTip;
    buildTabs();
    renderRelease();
  }
  sel.addEventListener("change", function () {
    lang = sel.value;
    try { localStorage.setItem("aero-lang", lang); } catch (e) { /* sin almacenamiento: solo esta visita */ }
    applyLang();
  });

  // ------------------------------------------------------------ burbujas que suben y se pueden explotar
  var box = $("#bubbles");
  function makeBubble(initial) {
    var b = document.createElement("span");
    var size = 16 + Math.random() * 64;
    b.className = "bubble";
    b.style.width = b.style.height = size + "px";
    b.style.left = Math.random() * 100 + "%";
    b.style.animationDuration = 16 + Math.random() * 22 + "s";
    b.style.animationDelay = (initial ? -Math.random() * 30 : 0) + "s";
    b.style.setProperty("--sway", (Math.random() * 80 - 40).toFixed(0) + "px");
    b.addEventListener("click", function (e) { pop(b, e); });
    b.addEventListener("animationiteration", function () { b.style.left = Math.random() * 100 + "%"; });
    box.appendChild(b);
  }
  function pop(b, e) {
    var r = b.getBoundingClientRect();
    for (var i = 0; i < 10; i++) {
      var p = document.createElement("span");
      p.className = "droplet";
      p.style.left = r.left + r.width / 2 + "px";
      p.style.top = r.top + r.height / 2 + "px";
      var a = (Math.PI * 2 * i) / 10, d = 24 + Math.random() * r.width * 0.6;
      p.style.setProperty("--dx", Math.cos(a) * d + "px");
      p.style.setProperty("--dy", Math.sin(a) * d + "px");
      document.body.appendChild(p);
      setTimeout(function (n) { return function () { n.remove(); }; }(p), 700);
    }
    b.remove();
    setTimeout(function () { makeBubble(false); }, 1500 + Math.random() * 2500);
    if (e) e.stopPropagation();
  }
  if (!reduce) {
    var n = window.innerWidth < 700 ? 10 : 20;
    for (var i = 0; i < n; i++) makeBubble(true);
  }

  // ------------------------------------------------------------ césped que se mece
  var grass = $("#grass");
  if (grass) {
    var blades = window.innerWidth < 700 ? 40 : 90;
    for (var g = 0; g < blades; g++) {
      var s = document.createElement("i");
      s.style.left = (g / blades) * 100 + Math.random() * 1.2 + "%";
      s.style.height = 10 + Math.random() * 22 + "px";
      s.style.animationDelay = -Math.random() * 4 + "s";
      s.style.animationDuration = 3 + Math.random() * 2.5 + "s";
      grass.appendChild(s);
    }
  }

  // ------------------------------------------------------------ parallax (scroll y ratón)
  var layers = $$("[data-depth]");
  var mx = 0, my = 0, ticking = false;
  function parallax() {
    ticking = false;
    var y = window.scrollY;
    layers.forEach(function (el) {
      var d = parseFloat(el.dataset.depth);
      el.style.transform = "translate3d(" + (mx * d * 60).toFixed(1) + "px," + (-y * d + my * d * 30).toFixed(1) + "px,0)";
    });
  }
  if (!reduce) {
    window.addEventListener("scroll", function () { if (!ticking) { ticking = true; requestAnimationFrame(parallax); } }, { passive: true });
    window.addEventListener("mousemove", function (e) {
      mx = e.clientX / window.innerWidth - 0.5; my = e.clientY / window.innerHeight - 0.5;
      if (!ticking) { ticking = true; requestAnimationFrame(parallax); }
    }, { passive: true });
  }

  // ------------------------------------------------------------ aparecer al hacer scroll + contadores
  function countUp(el) {
    var to = parseFloat(el.dataset.to), suffix = el.dataset.suffix || "", start = null;
    if (reduce || !to) { el.textContent = to + suffix; return; }
    function step(ts) {
      if (start === null) start = ts;
      var k = Math.min(1, (ts - start) / 1100);
      var v = Math.round(to * (1 - Math.pow(1 - k, 3)));
      el.textContent = v + suffix;
      if (k < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }
  if ("IntersectionObserver" in window && !reduce) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        var el = en.target;
        el.classList.add("in");
        $$(".count", el).forEach(countUp);
        io.unobserve(el);
      });
    }, { threshold: 0.12 });
    $$(".reveal").forEach(function (el, k) {
      var parent = el.parentElement;
      var sibs = parent ? $$(":scope > .reveal", parent) : [el];
      el.style.setProperty("--d", (sibs.indexOf(el) * 70) + "ms");
      io.observe(el);
    });
  } else {
    $$(".reveal").forEach(function (el) { el.classList.add("in"); });
  }

  // ------------------------------------------------------------ tarjetas con inclinación 3D y brillo
  if (!reduce && window.matchMedia("(hover: hover)").matches) {
    $$(".tilt").forEach(function (c) {
      c.addEventListener("mousemove", function (e) {
        var r = c.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
        c.style.transform = "perspective(800px) rotateX(" + ((0.5 - y) * 8).toFixed(2) + "deg) rotateY(" + ((x - 0.5) * 10).toFixed(2) + "deg) translateY(-4px)";
        c.style.setProperty("--gx", (x * 100).toFixed(1) + "%");
        c.style.setProperty("--gy", (y * 100).toFixed(1) + "%");
      });
      c.addEventListener("mouseleave", function () { c.style.transform = ""; });
    });
  }

  // ------------------------------------------------------------ capturas a pantalla completa
  var lb = $("#lightbox");
  $$(".win7 img").forEach(function (im) {
    im.addEventListener("click", function () { lb.querySelector("img").src = im.src; lb.hidden = false; });
  });
  lb.addEventListener("click", function () { lb.hidden = true; });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") lb.hidden = true; });

  // ------------------------------------------------------------ enlaces de GitHub y de descarga
  $$("[data-gh-link]").forEach(function (a) { a.href = configured ? repoUrl : "#"; });
  $$("[data-gh-releases]").forEach(function (a) { a.href = configured ? repoUrl + "/releases" : "#"; });
  var release = null;
  function mb(bytes) { return (bytes / 1048576).toFixed(0) + " MB"; }
  var VERSION_WORD = { es: "Versión", en: "Version", de: "Version", it: "Versione", pt: "Versão", ru: "Версия", zh: "版本" };
  var SOON = { es: "Próximamente en GitHub Releases", en: "Coming soon on GitHub Releases", de: "Bald auf GitHub Releases",
               it: "Presto su GitHub Releases", pt: "Em breve no GitHub Releases", ru: "Скоро на GitHub Releases", zh: "即将在 GitHub Releases 发布" };
  // Botón principal: «Descargar para <tu sistema>»
  var HERO = {
    win:   { es: "Descargar para Windows", en: "Download for Windows", de: "Für Windows herunterladen", it: "Scarica per Windows", pt: "Baixar para Windows", ru: "Скачать для Windows", zh: "下载 Windows 版" },
    linux: { es: "Descargar para Linux", en: "Download for Linux", de: "Für Linux herunterladen", it: "Scarica per Linux", pt: "Baixar para Linux", ru: "Скачать для Linux", zh: "下载 Linux 版" },
    mac:   { es: "Descargar para macOS", en: "Download for macOS", de: "Für macOS herunterladen", it: "Scarica per macOS", pt: "Baixar para macOS", ru: "Скачать для macOS", zh: "下载 macOS 版" }
  };
  var OS_LINE = { win: "Windows 10 · 11", linux: "Linux · 64 bits", mac: "macOS 14+ · Apple Silicon" };
  var PATTERNS = { setup: /setup\.exe$/i, portable: /portable\.zip$/i, linux: /linux.*\.tar\.gz$/i, mac: /macos.*\.dmg$/i };
  var OS_MAIN = { win: "setup", linux: "linux", mac: "mac" };

  // ------------------------------------------------------------ pestañas Windows / Linux / macOS
  function detectOS() {
    var ua = navigator.userAgent || "", plat = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
    if (/iPhone|iPad|Android/i.test(ua)) return "win";
    if (/Mac/i.test(plat) || /Mac OS X/i.test(ua)) return "mac";
    if (/Linux|X11/i.test(plat + " " + ua)) return "linux";
    return "win";
  }
  var os = detectOS();
  function selectOS(name, focus) {
    os = name;
    $$(".os-tab").forEach(function (b) {
      var on = b.dataset.os === name;
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
      if (on && focus) b.focus();
    });
    $$("[data-os-pane]").forEach(function (p) {
      var on = p.dataset.osPane === name;
      p.hidden = !on;
      if (on) { p.classList.remove("pane-in"); void p.offsetWidth; p.classList.add("pane-in"); }
    });
    renderRelease();                 // el botón principal sigue al sistema elegido
  }
  $$(".os-tab").forEach(function (b, i, all) {
    b.addEventListener("click", function () { selectOS(b.dataset.os); });
    b.addEventListener("keydown", function (e) {
      var d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (d) { e.preventDefault(); selectOS(all[(i + d + all.length) % all.length].dataset.os, true); }
    });
  });
  selectOS(os);

  function renderRelease() {
    var v = release ? release.tag_name.replace(/^v/, "") : cfg.version;
    $$("[data-version-line]").forEach(function (el) { el.textContent = (VERSION_WORD[lang] || "Version") + " " + v + " · " + OS_LINE[os]; });
    $$('[data-i18n="hero.download"]').forEach(function (el) { el.textContent = HERO[os][lang] || HERO[os].en; });
    var assets = {};
    if (release) {
      release.assets.forEach(function (a) {
        Object.keys(PATTERNS).forEach(function (k) { if (PATTERNS[k].test(a.name)) assets[k] = a; });
      });
    }
    var fallback = configured ? repoUrl + "/releases/latest" : "#descargar";
    Object.keys(PATTERNS).forEach(function (k) {
      var a = assets[k];
      $$('[data-download="' + k + '"]').forEach(function (el) { el.href = a ? a.browser_download_url : fallback; });
      $$('[data-size="' + k + '"]').forEach(function (el) { el.textContent = a ? a.name + " · " + mb(a.size) : (SOON[lang] || SOON.en); });
    });
    // el botón principal lleva a la descarga de tu sistema (o a la sección si aún no está publicada)
    var main = assets[OS_MAIN[os]];
    $$('[data-download="hero"]').forEach(function (el) { el.href = main ? main.browser_download_url : "#descargar"; });
  }
  if (configured && window.fetch) {
    fetch("https://api.github.com/repos/" + cfg.owner + "/" + cfg.repo + "/releases/latest", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { if (j && j.assets) { release = j; renderRelease(); } })
      .catch(function () { /* sin conexión con la API: quedan los enlaces a /releases/latest */ });
  }
  applyLang();
  restart();
})();
