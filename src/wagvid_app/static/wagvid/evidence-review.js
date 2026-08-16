(() => {
  const root = document.querySelector("[data-evidence-workspace]");
  if (!root) return;

  const video = root.querySelector("[data-evidence-video]");
  const placeholder = root.querySelector("[data-evidence-placeholder]");
  const loadButton = root.querySelector("[data-load-media]");
  const status = root.querySelector("[data-evidence-status]");
  const timeLabel = root.querySelector("[data-evidence-time]");
  const csrf = root.querySelector("[data-media-grant-form] input[name='csrfmiddlewaretoken']");
  let loadPromise = null;

  const formatTime = (seconds) => {
    const safe = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
    const minutes = Math.floor(safe / 60);
    const remainder = safe - minutes * 60;
    return `${String(minutes).padStart(2, "0")}:${remainder.toFixed(3).padStart(6, "0")}`;
  };

  const setStatus = (text, kind = "neutral") => {
    if (!status) return;
    status.textContent = text;
    status.classList.remove("info", "warning", "danger", "neutral");
    status.classList.add(kind);
  };

  const loadMedia = async () => {
    if (!video || !loadButton || !csrf) throw new Error("Evidence player is unavailable");
    if (video.src) return video;
    if (loadPromise) return loadPromise;
    loadPromise = (async () => {
      setStatus("Autoriserer…", "info");
      loadButton.disabled = true;
      try {
        const response = await fetch(loadButton.dataset.grantUrl, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "X-CSRFToken": csrf.value,
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
          },
          body: new URLSearchParams({ disposition: "inline" }),
        });
        if (!response.ok) throw new Error(`Grant failed (${response.status})`);
        const grant = await response.json();
        if (!grant.url) throw new Error("Grant response did not contain a media URL");
        video.src = grant.url;
        video.hidden = false;
        if (placeholder) placeholder.hidden = true;
        video.load();
        setStatus("Source klar", "info");
        return video;
      } catch (error) {
        setStatus("Kunne ikke åbne source", "danger");
        loadButton.disabled = false;
        loadPromise = null;
        throw error;
      }
    })();
    return loadPromise;
  };

  loadButton?.addEventListener("click", () => {
    loadMedia().catch(() => {});
  });

  document.querySelectorAll("[data-seek-ms]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        const player = await loadMedia();
        const target = Number(button.dataset.seekMs) / 1000;
        if (Number.isFinite(target)) {
          player.currentTime = Math.max(0, target);
          player.focus();
          setStatus(`Evidens @ ${formatTime(target)}`, "info");
        }
      } catch (_) {
        // Status is already surfaced in the evidence workspace.
      }
    });
  });

  root.querySelectorAll("[data-nudge-ms]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        const player = await loadMedia();
        const delta = Number(button.dataset.nudgeMs) / 1000;
        if (Number.isFinite(delta)) player.currentTime = Math.max(0, player.currentTime + delta);
      } catch (_) {
        // Status is already surfaced in the evidence workspace.
      }
    });
  });

  video?.addEventListener("timeupdate", () => {
    if (timeLabel) timeLabel.textContent = formatTime(video.currentTime);
  });
})();
