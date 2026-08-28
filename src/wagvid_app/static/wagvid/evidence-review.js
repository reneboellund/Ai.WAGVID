(() => {
  const root = document.querySelector("[data-evidence-workspace]");
  if (!root) return;

  const video = root.querySelector("[data-evidence-video]");
  const placeholder = root.querySelector("[data-evidence-placeholder]");
  const loadButton = root.querySelector("[data-load-media]");
  const status = root.querySelector("[data-evidence-status]");
  const timeLabel = root.querySelector("[data-evidence-time]");
  const frameLabel = root.querySelector("[data-evidence-frame]");
  const csrf = root.querySelector("[data-media-grant-form] input[name='csrfmiddlewaretoken']");
  const timelineUrl = root.dataset.timelineUrl || "";
  let loadPromise = null;
  let timelinePromise = null;
  let frames = null;

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

  const loadTimeline = async () => {
    if (frames) return frames;
    if (!timelineUrl) throw new Error("Canonical timeline is unavailable");
    if (timelinePromise) return timelinePromise;
    timelinePromise = (async () => {
      const response = await fetch(timelineUrl, { credentials: "same-origin" });
      if (response.status === 404) {
        setStatus("Canonical timeline ikke klar", "warning");
        throw new Error("Canonical timeline is not ready");
      }
      if (!response.ok) {
        setStatus("Canonical timeline kunne ikke valideres", "danger");
        throw new Error(`Timeline failed (${response.status})`);
      }
      const payload = await response.json();
      if (!Array.isArray(payload.frames) || payload.frames.length === 0) {
        throw new Error("Timeline contains no frames");
      }
      frames = payload.frames;
      setStatus(`${frames.length} canonical frames`, "info");
      return frames;
    })().catch((error) => {
      timelinePromise = null;
      throw error;
    });
    return timelinePromise;
  };

  const frameAtOrBefore = (time) => {
    if (!frames?.length) return null;
    let low = 0;
    let high = frames.length - 1;
    let answer = 0;
    while (low <= high) {
      const middle = Math.floor((low + high) / 2);
      if (frames[middle].timestamp_s <= time + 0.000001) {
        answer = middle;
        low = middle + 1;
      } else {
        high = middle - 1;
      }
    }
    return answer;
  };

  const updateFrameLabel = () => {
    if (!frameLabel || !frames?.length || !video) return;
    const index = frameAtOrBefore(video.currentTime);
    if (index === null) return;
    frameLabel.textContent = `${frames[index].frame_index + 1}/${frames.length}`;
  };

  const stepFrame = async (delta) => {
    const player = await loadMedia();
    await loadTimeline();
    const current = frameAtOrBefore(player.currentTime);
    if (current === null) return;
    const targetIndex = Math.min(frames.length - 1, Math.max(0, current + delta));
    const target = frames[targetIndex];
    player.pause();
    player.currentTime = target.timestamp_s;
    player.focus();
    if (frameLabel) frameLabel.textContent = `${target.frame_index + 1}/${frames.length}`;
    setStatus(`Frame ${target.frame_index + 1} @ ${formatTime(target.timestamp_s)}`, "info");
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

  root.querySelector("[data-frame-prev]")?.addEventListener("click", () => {
    stepFrame(-1).catch(() => {});
  });
  root.querySelector("[data-frame-next]")?.addEventListener("click", () => {
    stepFrame(1).catch(() => {});
  });

  video?.addEventListener("timeupdate", () => {
    if (timeLabel) timeLabel.textContent = formatTime(video.currentTime);
    updateFrameLabel();
  });
})();
