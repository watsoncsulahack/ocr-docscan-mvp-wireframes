(function () {
  const LS_KEY_BACKEND = "ocr.backend.url";
  const LS_KEY_FRONTEND_BASE = "ocr.frontend.baseUrl";
  const LS_KEY_RENDER_BACKEND = "ocr.render.backend.url";
  const LS_KEY_LOCAL_BACKEND = "ocr.local.backend.url";

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

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function frontendBaseUrl() {
    return normalizeUrl(localStorage.getItem(LS_KEY_FRONTEND_BASE) || window.OCR_FRONTEND_BASE_URL || DEFAULT_FRONTEND_BASE);
  }

  function activeBackendUrl() {
    return normalizeUrl(localStorage.getItem(LS_KEY_BACKEND) || window.OCR_BACKEND_URL || "");
  }

  function localBackendUrl() {
    return normalizeUrl(localStorage.getItem(LS_KEY_LOCAL_BACKEND) || LOCAL_BACKEND_DEFAULT);
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

  function setRevisionBadge() {
    const el = document.getElementById("controlPanelRevision");
    if (!el) return;
    const rev = String(window.OCR_CONTROL_REV || "local-dev").trim();
    const source = String(window.OCR_CONTROL_SOURCE || "working-tree").trim();
    el.textContent = `Control panel rev: ${rev} (${source})`;
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
    if (typeof data.llmApiKeySet === "boolean") parts.push(`LLM key: ${data.llmApiKeySet ? "set" : "missing"}`);
    if (typeof data.localControlApi === "boolean") parts.push(`Local control API: ${data.localControlApi ? "on" : "off"}`);
    el.textContent = parts.join(" | ");
  }

  async function apiWithBase(base, path, options = {}) {
    const timeoutMs = Number(options.timeoutMs || 10000);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const reqOptions = { ...options, signal: controller.signal };
      delete reqOptions.timeoutMs;
      const res = await fetch(`${base}${path}`, reqOptions);
      const json = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(json?.detail || json?.message || `HTTP ${res.status}`);
      return json;
    } catch (err) {
      if (err?.name === "AbortError") throw new Error(`Request timeout after ${Math.round(timeoutMs / 1000)}s`);
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }

  async function localApi(path, options = {}) {
    return apiWithBase(localBackendUrl(), path, options);
  }

  async function healthCheck() {
    const backend = activeBackendUrl();
    if (!backend) {
      setStatus("Backend: not set", false);
      setHealthMeta(null);
      return false;
    }

    try {
      const data = await apiWithBase(backend, "/health");
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

  function setGeneratedBackend(backendUrl) {
    const backend = normalizeUrl(backendUrl);
    const generatedOut = document.getElementById("generatedBackendUrlOutput");
    const linkOut = document.getElementById("githubPagesRenderUrlOutput");
    const renderInput = document.getElementById("renderBackendUrlInput");
    const openBtn = document.getElementById("openMvpLinkBtn");

    const mvpUrl = githubPagesUrlFor(frontendBaseUrl(), backend);

    if (generatedOut) generatedOut.value = backend;
    if (renderInput) renderInput.value = backend;
    if (linkOut) linkOut.value = mvpUrl;
    if (openBtn) openBtn.setAttribute("href", mvpUrl || "#");

    if (backend) {
      localStorage.setItem(LS_KEY_RENDER_BACKEND, backend);
      localStorage.setItem(LS_KEY_BACKEND, backend);
    }
  }

  async function fetchRuntimeInfo() {
    try {
      const out = await localApi("/control/local/runtime-info", { method: "GET" });
      const runtime = out?.runtime || {};
      const localUrl = normalizeUrl(runtime.localBackendUrl || "");
      if (localUrl) localStorage.setItem(LS_KEY_LOCAL_BACKEND, localUrl);
      return runtime;
    } catch {
      return {};
    }
  }

  async function waitForPublicBackendUrl(maxWaitMs = 45000) {
    const startedAt = Date.now();
    let latest = {};

    while (Date.now() - startedAt < maxWaitMs) {
      latest = await fetchRuntimeInfo();
      const url = normalizeUrl(latest.publicBackendUrl || "");
      if (url) return { url, runtime: latest };
      await sleep(1200);
    }

    return { url: "", runtime: latest };
  }

  function wireOneTapShare() {
    const runBtn = document.getElementById("runShareScriptBtn");
    const msg = document.getElementById("localOpsMsg");
    if (!runBtn) return;

    runBtn.addEventListener("click", async () => {
      runBtn.disabled = true;
      if (msg) msg.textContent = "Running share script...";

      try {
        await supervisorRequest("/activate", "POST", { id: "ocr-mvp-share" });
        if (msg) msg.textContent = "Share script started. Waiting for public URL...";

        const result = await waitForPublicBackendUrl(50000);
        if (result.url) {
          setGeneratedBackend(result.url);
          if (msg) msg.textContent = `Success. Public backend URL is ready: ${result.url}`;
          await healthCheck();
        } else {
          const tail = Array.isArray(result.runtime?.tunnelLogTail) ? result.runtime.tunnelLogTail : [];
          if (msg) {
            msg.textContent = tail.length
              ? `Share script ran, but URL not detected yet. Tunnel log tail: ${tail[tail.length - 1]}`
              : "Share script ran, but URL not detected yet. Tap again in a few seconds.";
          }
        }
      } catch (err) {
        if (msg) msg.textContent = `Failed to run share script: ${err.message}`;
      } finally {
        runBtn.disabled = false;
      }
    });
  }

  function wireRenderLinkHelper() {
    const renderInput = document.getElementById("renderBackendUrlInput");
    const generateBtn = document.getElementById("generateRenderLinkBtn");
    const output = document.getElementById("githubPagesRenderUrlOutput");
    const generatedOut = document.getElementById("generatedBackendUrlOutput");
    const msg = document.getElementById("renderLinkMsg");
    if (!renderInput || !generateBtn || !output || !generatedOut) return;

    renderInput.value = normalizeUrl(
      localStorage.getItem(LS_KEY_RENDER_BACKEND) || localStorage.getItem(LS_KEY_BACKEND) || window.OCR_BACKEND_URL || ""
    );

    generateBtn.addEventListener("click", async () => {
      const backend = normalizeUrl(renderInput.value);
      if (!tryParseUrl(backend)) {
        if (msg) msg.textContent = "Backend URL must be an absolute http(s) URL.";
        return;
      }

      setGeneratedBackend(backend);
      if (generatedOut) generatedOut.value = backend;

      try {
        const data = await apiWithBase(backend, "/health");
        if (msg) msg.textContent = `Link generated. Backend online (OCR=${data.ocrProvider || "?"}, LLM=${data.llmProvider || "?"}).`;
      } catch {
        if (msg) msg.textContent = "Link generated, but backend health check failed on this backend URL.";
      }
    });
  }

  function wireGroqSetupPanel() {
    const keyInput = document.getElementById("groqKeyInput");
    const buildBtn = document.getElementById("buildGroqCommandBtn");
    const applyBtn = document.getElementById("applyGroqKeyBtn");
    const output = document.getElementById("groqSetupCommandOutput");
    const note = document.getElementById("groqSetupNote");

    if (!buildBtn || !output) return;

    buildBtn.addEventListener("click", () => {
      const key = String(keyInput?.value || "").trim();
      const base = `cd ${shellEscapeSingle(REPO_DIR)} && `;

      if (key) {
        output.value = `${base}LLM_PROVIDER=openai LLM_BASE_URL=https://api.groq.com/openai LLM_MODEL=llama-3.1-8b-instant LLM_API_KEY=${shellEscapeSingle(key)} OCR_PROVIDER=ocrspace ENABLE_LLM_POSTPROCESS=1 bash ./scripts/share_demo_no_account.sh`;
        if (note) note.textContent = "Command includes the key. Clear shell history if needed.";
      } else {
        output.value = `${base}LLM_PROVIDER=openai LLM_BASE_URL=https://api.groq.com/openai LLM_MODEL=llama-3.1-8b-instant OCR_PROVIDER=ocrspace ENABLE_LLM_POSTPROCESS=1 bash ./scripts/share_demo_no_account.sh`;
        if (note) note.textContent = "No key inserted. Add key or use one-tap apply.";
      }
    });

    applyBtn?.addEventListener("click", async () => {
      const key = String(keyInput?.value || "").trim();
      if (!key) {
        if (note) note.textContent = "Enter Groq key first.";
        return;
      }
      if (note) note.textContent = "Applying key to local backend...";

      try {
        const out = await localApi("/control/local/groq-key", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ apiKey: key }),
        });
        if (note) note.textContent = out?.message || "Groq key applied locally.";
      } catch (err) {
        if (note) note.textContent = `Apply failed. Run one-tap share script first. (${err.message})`;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", async () => {
    setRevisionBadge();
    wireOneTapShare();
    wireRenderLinkHelper();
    wireGroqSetupPanel();
    wireCopyButtons();

    const runtime = await fetchRuntimeInfo();
    if (runtime?.publicBackendUrl) {
      setGeneratedBackend(runtime.publicBackendUrl);
    } else if (activeBackendUrl()) {
      try {
        await apiWithBase(activeBackendUrl(), "/health");
        setGeneratedBackend(activeBackendUrl());
      } catch {
        localStorage.removeItem(LS_KEY_BACKEND);
      }
    }

    await healthCheck();
  });
})();
