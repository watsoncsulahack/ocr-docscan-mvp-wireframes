(function () {
  const LS_KEY = "ocr.backend.url";

  function backendUrl() {
    const params = new URLSearchParams(window.location.search);
    const fromQuery = String(params.get("backend") || "").trim().replace(/\/$/, "");
    if (fromQuery) {
      localStorage.setItem(LS_KEY, fromQuery);
      return fromQuery;
    }
    return (localStorage.getItem(LS_KEY) || window.OCR_BACKEND_URL || "http://127.0.0.1:8010").replace(/\/$/, "");
  }

  async function api(path, options = {}) {
    const res = await fetch(`${backendUrl()}${path}`, options);
    const json = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(json?.detail || json?.message || `HTTP ${res.status}`);
    return json;
  }

  function setStatus(text, ok) {
    const el = document.getElementById("backendStatus");
    if (!el) return;
    el.textContent = text;
    el.className = ok ? "status-chip ok" : "status-chip bad";
  }

  async function healthCheck() {
    try {
      await api("/health");
      setStatus("Backend: online", true);
      return true;
    } catch {
      setStatus("Backend: offline", false);
      return false;
    }
  }

  function wireBackendUrlControls() {
    const input = document.getElementById("backendUrlInput");
    const save = document.getElementById("saveBackendUrlBtn");
    if (!input || !save) return;
    input.value = backendUrl();
    save.addEventListener("click", async () => {
      const v = String(input.value || "").trim().replace(/\/$/, "");
      if (!v) return;
      localStorage.setItem(LS_KEY, v);
      await healthCheck();
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
    if (!containerInput || !dateInput || !confirmBtn) return;

    const scan = JSON.parse(sessionStorage.getItem("ocr.scan") || "{}");
    containerInput.value = scan?.extracted?.containerNo || "";
    dateInput.value = scan?.extracted?.date || "";

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
        .map(
          (r) => `<tr><td>${r.containerNo || ""}</td><td>${r.date || ""}</td><td>${r.corrected ? "Yes" : "No"}</td></tr>`
        )
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
    wireBackendUrlControls();
    await healthCheck();

    const page = document.body.dataset.page;
    if (page === "upload") wireUploadPage();
    if (page === "review") wireReviewPage();
    if (page === "confirmation") wireConfirmationPage();
    if (page === "records") wireRecordsPage();
  });
})();
