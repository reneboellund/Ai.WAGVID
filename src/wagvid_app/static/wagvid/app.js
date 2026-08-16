(() => {
  "use strict";
  const qs = (selector, scope = document) => scope.querySelector(selector);
  const qsa = (selector, scope = document) => [...scope.querySelectorAll(selector)];
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const icons = {
    check: '<svg viewBox="0 0 24 24"><path d="m5 12 4 4L19 6"/></svg>',
    info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>'
  };

  function toast(message, tone = "info", timeout = 3800) {
    const region = qs("[data-toast-region]");
    if (!region) return;
    const item = document.createElement("div");
    item.className = `toast toast-${tone}`;
    item.innerHTML = `${icons[tone === "success" ? "check" : "info"]}<span>${message}</span><button type="button" aria-label="Luk">×</button>`;
    qs("button", item).addEventListener("click", () => item.remove());
    region.append(item);
    window.setTimeout(() => item.remove(), timeout);
  }

  function setupNavigation() {
    qsa("[data-nav-open]").forEach(button => button.addEventListener("click", () => document.body.classList.add("nav-open")));
    qsa("[data-nav-close]").forEach(button => button.addEventListener("click", () => document.body.classList.remove("nav-open")));
    window.addEventListener("keydown", event => {
      if (event.key === "Escape") document.body.classList.remove("nav-open");
    });
  }

  function setupClock() {
    const target = qs("[data-live-clock]");
    if (!target) return;
    const update = () => target.textContent = new Intl.DateTimeFormat("da-DK", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date());
    update();
    window.setInterval(update, 1000);
  }

  function setupCounters() {
    const targets = qsa("[data-counter]");
    if (reducedMotion) {
      targets.forEach(node => node.textContent = node.dataset.counter);
      return;
    }
    const formatter = new Intl.NumberFormat("da-DK");
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      const node = entry.target;
      const end = Number(node.dataset.counter || 0);
      const suffix = node.dataset.suffix || "";
      const started = performance.now();
      const duration = 850;
      const frame = now => {
        const progress = Math.min(1, (now - started) / duration);
        const eased = 1 - Math.pow(1 - progress, 3);
        node.textContent = `${formatter.format(Math.round(end * eased))}${suffix}`;
        if (progress < 1) requestAnimationFrame(frame);
      };
      requestAnimationFrame(frame);
      observer.unobserve(node);
    }), { threshold: .3 });
    targets.forEach(target => observer.observe(target));
  }

  function setupProgress() {
    qsa("[data-progress]").forEach(node => {
      const value = Math.max(0, Math.min(100, Number(node.dataset.progress || 0)));
      node.style.setProperty("--progress", `${value}%`);
    });
  }

  function setupTableSearch() {
    qsa("[data-table-search]").forEach(input => {
      const table = document.getElementById(input.dataset.tableSearch);
      if (!table) return;
      const rows = qsa("tbody tr[data-searchable]", table);
      const count = qs("[data-result-count]");
      input.addEventListener("input", () => {
        const value = input.value.trim().toLocaleLowerCase("da");
        let visible = 0;
        rows.forEach(row => {
          const show = row.textContent.toLocaleLowerCase("da").includes(value);
          row.hidden = !show;
          if (show) visible += 1;
        });
        if (count) count.textContent = `${visible} vist`;
      });
    });
  }

  function setupCommandPalette() {
    const palette = qs("[data-command-palette]");
    const input = qs("[data-command-input]");
    if (!palette || !input) return;
    let selected = 0;
    const items = () => qsa("[data-command-item]", palette).filter(item => !item.hidden);
    const renderSelected = () => items().forEach((item, index) => item.classList.toggle("selected", index === selected));
    const open = () => {
      palette.hidden = false;
      document.body.style.overflow = "hidden";
      window.setTimeout(() => input.focus(), 20);
      selected = 0;
      renderSelected();
    };
    const close = () => {
      palette.hidden = true;
      document.body.style.overflow = "";
      input.value = "";
      qsa("[data-command-item]", palette).forEach(item => item.hidden = false);
    };
    qsa("[data-command-open]").forEach(button => button.addEventListener("click", open));
    qsa("[data-command-close]").forEach(button => button.addEventListener("click", close));
    input.addEventListener("input", () => {
      const value = input.value.trim().toLocaleLowerCase("da");
      qsa("[data-command-item]", palette).forEach(item => item.hidden = !item.textContent.toLocaleLowerCase("da").includes(value));
      selected = 0;
      renderSelected();
    });
    window.addEventListener("keydown", event => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        palette.hidden ? open() : close();
      }
      if (palette.hidden) return;
      if (event.key === "Escape") close();
      if (event.key === "ArrowDown") { event.preventDefault(); selected = Math.min(items().length - 1, selected + 1); renderSelected(); }
      if (event.key === "ArrowUp") { event.preventDefault(); selected = Math.max(0, selected - 1); renderSelected(); }
      if (event.key === "Enter" && items()[selected]) items()[selected].click();
    });
  }

  function setupWaveform() {
    const wave = qs("[data-waveform]");
    if (!wave || wave.children.length) return;
    const pattern = [10,18,26,14,30,36,21,12,29,38,31,17,24,34,19,12,28,35,20,14,31,25,15,10,22,34,27,16,29,20,12,25,33,18,11,21,30,16,9,18,27,14,8,19,24,13,8,15];
    pattern.forEach((height, index) => {
      const bar = document.createElement("i");
      bar.style.setProperty("--h", `${height}px`);
      bar.style.setProperty("--n", index);
      wave.append(bar);
    });
  }

  function setupStudio() {
    const studio = qs("[data-studio]");
    if (!studio) return;
    const gymnast = qs("[data-gymnast-select]", studio);
    const device = qs("[data-device-select]", studio);
    const record = qs("[data-record]", studio);
    const arm = qs("[data-arm]", studio);
    const stop = qs("[data-stop]", studio);
    const timer = qs("[data-record-time]", studio);
    const mode = qs("[data-live-mode]", studio);
    let startedAt = 0;
    let interval = null;
    const ready = () => Boolean(gymnast?.value && device?.value);
    const sync = () => {
      if (record) record.disabled = !ready();
      if (arm) arm.disabled = !ready();
    };
    [gymnast, device].forEach(select => select?.addEventListener("change", sync));
    sync();

    arm?.addEventListener("click", () => {
      arm.classList.toggle("is-active");
      const active = arm.classList.contains("is-active");
      arm.innerHTML = active ? '<svg><use href="#i-check"/></svg> Auto armeret' : '<svg><use href="#i-spark"/></svg> Armér auto';
      toast(active ? "Auto-capture er armeret og følger bevægelsen." : "Auto-capture er deaktiveret.", active ? "success" : "info");
    });

    record?.addEventListener("click", () => {
      startedAt = Date.now();
      studio.classList.add("is-recording");
      record.disabled = true;
      stop.disabled = false;
      if (mode) mode.innerHTML = "<i></i> OPTAGER";
      interval = window.setInterval(() => {
        const seconds = Math.floor((Date.now() - startedAt) / 1000);
        const minutes = String(Math.floor(seconds / 60)).padStart(2, "0");
        const rest = String(seconds % 60).padStart(2, "0");
        if (timer) timer.textContent = `${minutes}:${rest}`;
      }, 250);
      toast("Optagelse startet. Sporingsdata registreres live.", "success");
    });

    stop?.addEventListener("click", () => {
      window.clearInterval(interval);
      studio.classList.remove("is-recording");
      record.disabled = !ready();
      stop.disabled = true;
      if (mode) mode.innerHTML = "<i></i> LIVE PREVIEW";
      toast("Optagelsen er stoppet og klargøres til upload.", "success");
    });
  }

  function setupUtilityActions() {
    qs("[data-notify]")?.addEventListener("click", () => toast("Ingen nye kritiske hændelser. Systemet overvåges live."));
    qsa("[data-refresh]").forEach(button => button.addEventListener("click", () => {
      button.classList.add("is-loading");
      window.setTimeout(() => {
        button.classList.remove("is-loading");
        toast("Live-data er opdateret.", "success");
      }, 650);
    }));
    qsa("[data-demo-action]").forEach(button => button.addEventListener("click", () => toast(button.dataset.demoAction || "Handlingen er klar til backend-tilkobling.")));
  }

  setupNavigation();
  setupClock();
  setupCounters();
  setupProgress();
  setupTableSearch();
  setupCommandPalette();
  setupWaveform();
  setupStudio();
  setupUtilityActions();
})();
