(function () {
  const LS_KEY_BACKEND = "ocr.backend.url";
  const LS_KEY_FRONTEND_BASE = "ocr.frontend.baseUrl";
  const LS_KEY_RENDER_BACKEND = "ocr.render.backend.url";

  const DEFAULT_FRONTEND_BASE = "https://watsoncsulahack.github.io/ocr-docscan-mvp-wireframes/";
  const LOCAL_BACKEND_DEFAULT = "http://127.0.0.1:8010";
  const REPO_DIR = "/storage/emulated/0/OpenClawHub/ocr-docscan-mvp-wireframes";

  function normalizeUrl(value) {
    return String(value || "").trim().replace(/\/$/, "");
  }

  function tryParseUrl(value) {
    try {
      const u = new URL(value);
      if (!["http:", "https:"].includes(u.protocol)) return null;
      return u;
    } catch {
      return null;
    }
  }

  function backendUrl() {
    const params = new URLSearchParams(window.location.search);
    const fromQuery = normalizeUrl(params.get("backend"));
    if (fromQuery) {
      localStorage.setItem(LS_KEY_BACKEND, fromQuery);
      return fromQuery;
    }
    return normalizeUrl(localStorage.getItem(LS_KEY_BACKEND) || window.OCR_BACKEND_URL || LOCAL_BACKEND_DEFAULT);
  }

  function frontendBaseUrl() {
    return normalizeUrl(localStorage.getItem(LS_KEY_FRONTEND_BASE) || window.OCR_FRONTEND_BASE_URL || DEFAULT_FRONTEND_BASE);
  }

  function githubPagesUrlFor(frontendBase, backend) {
    const f = normalizeUrl(frontendBase);
    const b = normalizeUrl(backend);
    if (!f || !b) return "";
    const frontend = tryParseUrl(f);
    if (!frontend) return "";
    frontend.searchParams.set("backend", b);
    return frontend.toString();
  }

  function setStatus(text, ok) {
    const el = document.getElementById("backendStatus");
    if (!el) return;
    el.textContent = text;
    el.className = ok ? "status-chip ok" : "status-chip bad";
  }

  function setHealthMeta(data) {
    const el = document.getElementById("backendHealthMeta");
    if (!el) return;
    if (!data || typeof data !== "object") {
      el.textContent = "";
      return;
    }
    const parts = [];
    if (data.ocrProvider) parts.push(`OCR: ${data.ocrProvider}`);
    if (data.llmProvider) parts.push(`LLM: ${data.llmProvider}`);
    if (typeof data.geminiApiKeySet === "boolean") parts.push(`Gemini key: ${data.geminiApiKeySet ? "set" : "missing"}`);
    if (typeof data.localControlApi === "boolean") parts.push(`Local control API: ${data.localControlApi ? "on" : "off"}`);
    el.textContent = parts.join(" | ");
  }

  async function api(path, options = {}) {
    const res = await fetch(`${backendUrl()}${path}`, options);
    const json = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(json?.detail || json?.message || `HTTP ${res.status}`);
    return json;
  }

  async function localApi(path, options = {}) {
    const base = normalizeUrl(localStorage.getItem("ocr.local.backend.url") || LOCAL_BACKEND_DEFAULT);
    const res = await fetch(`${base}${path}`, options);
    const json = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(json?.detail || json?.message || `HTTP ${res.status}`);
    return json;
  }

  async function healthCheck() {
    try {
      const data = await api("/health");
      setStatus("Backend: online", true);
      setHealthMeta(data);
      return true;
    } catch {
      setStatus("Backend: offline", false);
      setHealthMeta(null);
      return false;
    }
  }

  function supervisorBases() {
    const out = [];
    if (window.location.origin && /^https?:/i.test(window.location.origin)) {
      out.push(`${window.location.origin.replace(/\/$/, "")}/v0`);
    }
    out.push("http://127.0.0.1:8099/v0");
    out.push("http://localhost:8099/v0");

    return Array.from(new Set(out));
  }

  async function supervisorRequest(path, method = "GET", body = null) {
    const payload = body ? JSON.stringify(body) : null;
    let lastErr = null;

    for (const base of supervisorBases()) {
      try {
        const res = await fetch(`${base}${path}`, {
          method,
          headers: payload ? { "Content-Type": "application/json" } : undefined,
          body: payload,
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok && data?.ok) return data;
        throw new Error(data?.error?.message || data?.detail || `HTTP ${res.status}`);
      } catch (err) {
        lastErr = err;
      }
    }

    throw lastErr || new Error("Supervisor unavailable");
  }

  async function readTextFile(path) {
    const res = await fetch(path, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.text()).trim();
  }

  function shellEscapeSingle(value) {
    return `'${String(value || "").replace(/'/g, `'"'"'`)}'`;
  }

  async function copyById(id) {
    const el = document.getElementById(id);
    if (!el) return false;
    const value = ("value" in el ? el.value : el.textContent || "").trim();
    if (!value) return false;

    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      if ("select" in el && typeof el.select === "function") {
        el.select();
        document.execCommand("copy");
        return true;
      }
      return false;
    }
  }

  function wireCopyButtons() {
    document.querySelectorAll("[data-copy-target]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const target = btn.getAttribute("data-copy-target");
        if (!target) return;
        const ok = await copyById(target);
        const prev = btn.textContent;
        btn.textContent = ok ? "Copied" : "Copy failed";
        setTimeout(() => {
          btn.textContent = prev;
        }, 1200);
      });
    });
  }

  function wireRenderLinkHelper() {
    const renderInput = document.getElementById("renderBackendUrlInput");
    const generateBtn = document.getElementById("generateRenderLinkBtn");
    const output = document.getElementById("githubPagesRenderUrlOutput");
    const backendOut = document.getElementById("renderBackendOnlyOutput");
    const msg = document.getElementById("renderLinkMsg");
    if (!renderInput || !generateBtn || !output || !backendOut) return;

    renderInput.value = normalizeUrl(
      localStorage.getItem(LS_KEY_RENDER_BACKEND) || localStorage.getItem(LS_KEY_BACKEND) || window.OCR_BACKEND_URL || ""
    );

    generateBtn.addEventListener("click", async () => {
      const backend = normalizeUrl(renderInput.value);
      if (!tryParseUrl(backend)) {
        if (msg) msg.textContent = "Backend URL must be an absolute http(s) URL.";
        return;
      }

      localStorage.setItem(LS_KEY_RENDER_BACKEND, backend);
      localStorage.setItem(LS_KEY_BACKEND, backend);

      output.value = githubPagesUrlFor(frontendBaseUrl(), backend);
      backendOut.value = backend;

      try {
        const res = await fetch(`${backend}/health`);
        if (!res.ok) throw new Error();
        const data = await res.json();
        if (msg) msg.textContent = `Link generated. Backend online (OCR=${data.ocrProvider || "?"}, LLM=${data.llmProvider || "?"}).`;
      } catch {
        if (msg) msg.textContent = "Link generated, but backend health check failed on this backend URL.";
      }
    });
  }

  function wireLocalOpsPanel() {
    const startBackendBtn = document.getElementById("startLocalBackendBtn");
    const startTunnelBtn = document.getElementById("startTunnelBtn");
    const stopTunnelBtn = document.getElementById("stopTunnelBtn");
    const refreshBtn = document.getElementById("refreshGeneratedBackendBtn");
    const useBtn = document.getElementById("useGeneratedBackendBtn");
    const generatedOut = document.getElementById("generatedBackendUrlOutput");
    const localOut = document.getElementById("localBackendUrlOutput");
    const msg = document.getElementById("localOpsMsg");

    if (!startBackendBtn || !startTunnelBtn || !stopTunnelBtn || !refreshBtn || !useBtn || !generatedOut || !localOut) return;

    async function refreshUrls() {
      try {
        localOut.value = await readTextFile("./data/runtime/local_backend_url.txt");
        localStorage.setItem("ocr.local.backend.url", localOut.value);
      } catch {
        localOut.value = LOCAL_BACKEND_DEFAULT;
      }

      try {
        generatedOut.value = await readTextFile("./data/runtime/public_backend_url.txt");
      } catch {
        generatedOut.value = "";
      }
    }

    startBackendBtn.addEventListener("click", async () => {
      if (msg) msg.textContent = "Starting local backend...";
      try {
        await supervisorRequest("/activate", "POST", { id: "ocr-mvp-backend" });
        await refreshUrls();
        if (msg) msg.textContent = "Local backend started.";
      } catch (err) {
        if (msg) msg.textContent = `Failed to start backend: ${err.message}`;
      }
    });

    startTunnelBtn.addEventListener("click", async () => {
      if (msg) msg.textContent = "Starting tunnel and generating backend URL...";
      try {
        await supervisorRequest("/activate", "POST", { id: "ocr-mvp-share" });
        setTimeout(refreshUrls, 1200);
        setTimeout(refreshUrls, 3000);
        if (msg) msg.textContent = "Tunnel start requested. Refresh in a moment if URL is still blank.";
      } catch (err) {
        if (msg) msg.textContent = `Failed to start tunnel: ${err.message}`;
      }
    });

    stopTunnelBtn.addEventListener("click", async () => {
      if (msg) msg.textContent = "Stopping tunnel...";
      try {
        await supervisorRequest("/stop", "POST", { id: "ocr-mvp-share" });
        if (msg) msg.textContent = "Tunnel stopped.";
      } catch (err) {
        if (msg) msg.textContent = `Failed to stop tunnel: ${err.message}`;
      }
    });

    refreshBtn.addEventListener("click", async () => {
      await refreshUrls();
      if (msg) msg.textContent = generatedOut.value ? "Generated backend URL refreshed." : "No generated backend URL yet.";
    });

    useBtn.addEventListener("click", () => {
      const v = normalizeUrl(generatedOut.value);
      if (!v) {
        if (msg) msg.textContent = "No generated backend URL available yet.";
        return;
      }
      localStorage.setItem(LS_KEY_BACKEND, v);
      const renderInput = document.getElementById("renderBackendUrlInput");
      if (renderInput) renderInput.value = v;
      if (msg) msg.textContent = "Generated backend URL set as active backend.";
      healthCheck();
    });

    refreshUrls();
  }

  function wireGeminiSetupPanel() {
    const keyInput = document.getElementById("geminiKeyInput");
    const buildBtn = document.getElementById("buildGeminiCommandBtn");
    const applyBtn = document.getElementById("applyGeminiKeyBtn");
    const output = document.getElementById("geminiSetupCommandOutput");
    const note = document.getElementById("geminiSetupNote");

    if (!buildBtn || !output) return;

    buildBtn.addEventListener("click", () => {
      const key = String(keyInput?.value || "").trim();
      const base = `cd ${shellEscapeSingle(REPO_DIR)} && `;

      if (key) {
        output.value = `${base}bash ./scripts/set_gemini_key.sh ${shellEscapeSingle(key)} && bash ./scripts/start_backend_local.sh`;
        if (note) note.textContent = "Command includes the key. Clear shell history if needed.";
      } else {
        output.value = `${base}bash ./scripts/set_gemini_key.sh && bash ./scripts/start_backend_local.sh`;
        if (note) note.textContent = "No key inserted. Script will prompt for key securely.";
      }
    });

    applyBtn?.addEventListener("click", async () => {
      const key = String(keyInput?.value || "").trim();
      if (!key) {
        if (note) note.textContent = "Enter Gemini key first.";
        return;
      }
      if (note) note.textContent = "Applying key to local backend...";

      try {
        const out = await localApi("/control/local/gemini-key", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ apiKey: key }),
        });
        if (note) note.textContent = out?.message || "Gemini key applied locally.";
      } catch (err) {
        if (note) note.textContent = `Apply failed. Start local backend first. (${err.message})`;
      }
    });
  }

  function wireUploadPage() {
    const fileInput = document.getElementById("fileInput");
    const scanBtn = document.getElementById("scanBtn");
    const msg = document.getElementById("scanMsg");
    if (!fileInput || !scanBtn) return;

    scanBtn.addEventListener("click", async () => {
      const file = fileInput.files?.[0];
      if (!file) {
        if (msg) msg.textContent = "Pick an image first.";
        return;
      }
      if (msg) msg.textContent = "Processing...";
      const form = new FormData();
      form.append("file", file);
      try {
        const data = await api("/scan", { method: "POST", body: form });
        sessionStorage.setItem("ocr.scan", JSON.stringify(data));
        window.location.href = "./review.html";
      } catch (err) {
        if (msg) msg.textContent = `Scan failed: ${err.message}`;
      }
    });
  }

  function wireReviewPage() {
    const containerInput = document.getElementById("containerNo");
    const dateInput = document.getElementById("eventDate");
    const confirmBtn = document.getElementById("confirmBtn");
    const msg = document.getElementById("reviewMsg");
    const dbg = document.getElementById("scanDebug");
    if (!containerInput || !dateInput || !confirmBtn) return;

    const scan = JSON.parse(sessionStorage.getItem("ocr.scan") || "{}");
    containerInput.value = scan?.extracted?.containerNo || "";
    dateInput.value = scan?.extracted?.date || "";

    if (dbg) {
      const lines = [];
      lines.push(`Pipeline: ${(scan?.pipeline || []).join(" -> ") || "n/a"}`);
      lines.push(`Issues: ${(scan?.issues || []).join(", ") || "none"}`);
      lines.push(`OCR mode: ${scan?.ocrMode || "n/a"}`);
      if (scan?.rawTextPreview) {
        lines.push("Raw text preview:");
        lines.push(scan.rawTextPreview);
      }
      dbg.textContent = lines.join("\n");
    }

    confirmBtn.addEventListener("click", async () => {
      const payload = {
        containerNo: String(containerInput.value || "").trim(),
        date: String(dateInput.value || "").trim(),
        sourceFileName: scan?.sourceFileName || null,
        corrected:
          String(containerInput.value || "").trim() !== String(scan?.extracted?.containerNo || "").trim() ||
          String(dateInput.value || "").trim() !== String(scan?.extracted?.date || "").trim(),
      };
      try {
        const out = await api("/records", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        sessionStorage.setItem("ocr.saved", JSON.stringify(out.record || {}));
        window.location.href = "./confirmation.html";
      } catch (err) {
        if (msg) msg.textContent = `Save failed: ${err.message}`;
      }
    });
  }

  function wireConfirmationPage() {
    const rec = JSON.parse(sessionStorage.getItem("ocr.saved") || "{}");
    const c = document.getElementById("cValue");
    const d = document.getElementById("dValue");
    if (c) c.textContent = rec.containerNo || "-";
    if (d) d.textContent = rec.date || "-";
  }

  async function wireRecordsPage() {
    const body = document.getElementById("recordsBody");
    if (!body) return;
    try {
      const data = await api("/records");
      const rows = data.records || [];
      body.innerHTML = rows
        .map((r) => `<tr><td>${r.containerNo || ""}</td><td>${r.date || ""}</td><td>${r.corrected ? "Yes" : "No"}</td></tr>`)
        .join("");
      if (!rows.length) body.innerHTML = `<tr><td colspan="3">No records yet.</td></tr>`;
    } catch (err) {
      body.innerHTML = `<tr><td colspan="3">Failed to load records: ${err.message}</td></tr>`;
    }

    const resetBtn = document.getElementById("resetDemoBtn");
    if (resetBtn) {
      resetBtn.addEventListener("click", async () => {
        try {
          await api("/reset-demo", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ confirm: "RESET_DEMO" }),
          });
          await wireRecordsPage();
        } catch (err) {
          alert(`Reset failed: ${err.message}`);
        }
      });
    }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    wireRenderLinkHelper();
    wireLocalOpsPanel();
    wireGeminiSetupPanel();
    wireCopyButtons();
    await healthCheck();

    const page = document.body.dataset.page;
    if (page === "upload") wireUploadPage();
    if (page === "review") wireReviewPage();
    if (page === "confirmation") wireConfirmationPage();
    if (page === "records") wireRecordsPage();
  });
})();
