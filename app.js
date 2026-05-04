(function () {
  const PENDING_FILE_KEY = "ocr.pending.file";
  const REVIEW_STATE_KEY = "ocr.review.state";
  const LAST_SUBMISSION_KEY = "ocr.last.submission";
  let BACKEND_BASE_CACHE = null;

  function setBackendStatus(online) {
    const wrap = byId("backendStatus");
    const label = byId("backendStatusLabel");
    if (!wrap || !label) return;
    wrap.classList.toggle("online", !!online);
    wrap.classList.toggle("offline", !online);
    label.textContent = online ? "online" : "offline";
  }

  function byId(id) {
    return document.getElementById(id);
  }

  async function resolveBackendUrl() {
    if (BACKEND_BASE_CACHE) return BACKEND_BASE_CACHE;

    const candidates = [];
    if (window.location.protocol.startsWith("http")) {
      candidates.push(window.location.origin.replace(/\/+$/, ""));
    }
    candidates.push(
      "http://127.0.0.1:8000",
      "http://localhost:8000",
      "http://127.0.0.1:8010",
      "http://localhost:8010"
    );

    const seen = new Set();
    for (const base of candidates) {
      if (seen.has(base)) continue;
      seen.add(base);
      try {
        const res = await fetch(`${base}/health`);
        if (res.ok) {
          BACKEND_BASE_CACHE = base;
          setBackendStatus(true);
          return base;
        }
      } catch {
        // try next
      }
    }

    setBackendStatus(false);

    throw new Error(
      "Could not connect to local backend. Start backend with uvicorn on http://127.0.0.1:8000 (or :8010)."
    );
  }

  async function probeBackendStatus() {
    try {
      if (BACKEND_BASE_CACHE) {
        const res = await fetch(`${BACKEND_BASE_CACHE}/health`);
        setBackendStatus(res.ok);
        if (!res.ok) BACKEND_BASE_CACHE = null;
        return;
      }
      await resolveBackendUrl();
    } catch {
      setBackendStatus(false);
    }
  }

  async function toDataUrl(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result || ""));
      r.onerror = reject;
      r.readAsDataURL(file);
    });
  }

  function dataUrlToBase64(dataUrl) {
    if (!dataUrl || !dataUrl.includes(",")) return "";
    return dataUrl.split(",")[1] || "";
  }

  function dataUrlToBlob(dataUrl, mimeType) {
    const b64 = dataUrlToBase64(dataUrl);
    const binary = atob(b64);
    const len = binary.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    return new Blob([bytes], { type: mimeType || "application/octet-stream" });
  }

  function extFromFileName(name) {
    const m = (name || "").toLowerCase().match(/\.([a-z0-9]+)$/);
    return m ? m[1] : "";
  }

  function classifyField(value, confidence, validate, userAdjusted = false) {
    const v = (value || "").trim();
    if (!v) return "red";
    if (!validate(v)) return "red";
    if (!userAdjusted && confidence < 0.9) return "yellow";
    return "green";
  }

  function validContainer(v) {
    return /^[A-Za-z]{4}\d{7}$/.test((v || "").trim());
  }

  function validDate(v) {
    return /^\d{2}\/\d{2}\/\d{4}$/.test((v || "").trim());
  }

  function setDot(dotEl, status) {
    if (!dotEl) return;
    dotEl.classList.remove("green", "yellow", "red");
    dotEl.classList.add(status);
  }

  function setRowHighlight(rowEl, status) {
    if (!rowEl) return;
    rowEl.classList.toggle("needs-review", status !== "green");
  }

  async function initUploadPage() {
    const fileInput = byId("fileInput");
    const cameraBtn = byId("openCamera");
    const processBtn = byId("processBtn");
    const fileMeta = byId("fileMeta");
    const filePreview = byId("filePreview");
    const uploadError = byId("uploadError");

    if (!fileInput || !processBtn) return;

    let selectedFile = null;

    // Initial and periodic health probes for online/offline badge
    probeBackendStatus();
    setInterval(probeBackendStatus, 5000);

    fileInput.addEventListener("change", () => {
      uploadError.classList.add("hidden");
      selectedFile = fileInput.files && fileInput.files[0] ? fileInput.files[0] : null;
      if (!selectedFile) {
        fileMeta.textContent = "No file selected.";
        processBtn.disabled = true;
        filePreview.classList.add("hidden");
        filePreview.removeAttribute("src");
        return;
      }

      const ext = extFromFileName(selectedFile.name);
      if (!["pdf", "png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff"].includes(ext)) {
        uploadError.textContent = "Unsupported file type. Use PDF or image files.";
        uploadError.classList.remove("hidden");
        processBtn.disabled = true;
        return;
      }

      fileMeta.textContent = `${selectedFile.name} (${Math.round(selectedFile.size / 1024)} KB)`;
      processBtn.disabled = false;

      if ((selectedFile.type || "").startsWith("image/")) {
        const objUrl = URL.createObjectURL(selectedFile);
        filePreview.src = objUrl;
        filePreview.classList.remove("hidden");
      } else {
        filePreview.classList.add("hidden");
        filePreview.removeAttribute("src");
      }
    });

    cameraBtn.addEventListener("click", () => {
      fileInput.setAttribute("accept", "image/*");
      fileInput.setAttribute("capture", "environment");
      fileInput.click();
      setTimeout(() => {
        fileInput.setAttribute("accept", ".pdf,image/*");
        fileInput.removeAttribute("capture");
      }, 300);
    });

    processBtn.addEventListener("click", async () => {
      if (!selectedFile) return;
      processBtn.disabled = true;
      processBtn.textContent = "Preparing...";

      try {
        await resolveBackendUrl();
        const dataUrl = await toDataUrl(selectedFile);
        sessionStorage.setItem(
          PENDING_FILE_KEY,
          JSON.stringify({
            name: selectedFile.name,
            type: selectedFile.type || "application/octet-stream",
            size: selectedFile.size,
            dataUrl,
          })
        );
        window.location.href = "./processing.html";
      } catch (err) {
        uploadError.textContent = `Could not prepare file: ${err?.message || err}`;
        uploadError.classList.remove("hidden");
        processBtn.disabled = false;
        processBtn.textContent = "Process";
      }
    });
  }

  async function initProcessingPage() {
    const step1 = byId("step1");
    const step2 = byId("step2");
    const step3 = byId("step3");
    const msg = byId("processingMsg");
    const errBox = byId("processingError");

    const raw = sessionStorage.getItem(PENDING_FILE_KEY);
    if (!raw) {
      window.location.href = "./upload.html";
      return;
    }

    const file = JSON.parse(raw);
    step1?.classList.add("active");

    try {
      msg.textContent = "Running scan...";
      step2?.classList.add("active");
      const backend = await resolveBackendUrl();
      const blob = dataUrlToBlob(file.dataUrl, file.type || "application/octet-stream");
      const form = new FormData();
      form.append("file", blob, file.name || "upload.bin");

      const res = await fetch(`${backend}/scan`, {
        method: "POST",
        body: form,
      });

      if (!res.ok) {
        const t = await res.text();
        throw new Error(`Scan failed (${res.status}): ${t}`);
      }

      const scan = await res.json();
      const containerNo = scan?.extracted?.containerNo || "";
      const eventDate = scan?.extracted?.date || "";
      const confidence = {
        containerNo: containerNo ? 0.96 : 0.4,
        eventDate: eventDate ? 0.82 : 0.35,
      };

      step3?.classList.add("active");
      msg.textContent = "Preparing review screen...";

      sessionStorage.setItem(
        REVIEW_STATE_KEY,
        JSON.stringify({
          file,
          submissionId: scan?.submissionId || null,
          classifier: scan?.classifier || "container",
          fields: { containerNo, eventDate },
          confidence,
          scan,
        })
      );

      window.location.href = "./review.html";
    } catch (err) {
      errBox.textContent = err?.message || String(err);
      errBox.classList.remove("hidden");
      msg.textContent = "Processing failed. Please return and try again.";
    }
  }

  async function initReviewPage() {
    const raw = sessionStorage.getItem(REVIEW_STATE_KEY);
    if (!raw) {
      window.location.href = "./upload.html";
      return;
    }

    const state = JSON.parse(raw);
    const containerInput = byId("containerNo");
    const eventInput = byId("eventDate");
    const dotContainer = byId("dot-containerNo");
    const dotDate = byId("dot-eventDate");
    const rowContainer = byId("row-containerNo");
    const rowDate = byId("row-eventDate");
    const submitBtn = byId("submitBtn");
    const rerunBtn = byId("rerunScan");
    const errBox = byId("reviewError");
    const reviewFilePreview = byId("reviewFilePreview");

    containerInput.value = state.fields?.containerNo || "";
    eventInput.value = state.fields?.eventDate || "";

    const initialContainer = String(state.fields?.containerNo || "").trim();
    const initialEventDate = String(state.fields?.eventDate || "").trim();

    if (reviewFilePreview && state.file?.dataUrl && String(state.file?.type || "").startsWith("image/")) {
      reviewFilePreview.src = state.file.dataUrl;
      reviewFilePreview.classList.remove("hidden");
    }

    function evaluate() {
      const containerAdjusted = containerInput.value.trim() !== initialContainer;
      const dateAdjusted = eventInput.value.trim() !== initialEventDate;

      const s1 = classifyField(containerInput.value, Number(state.confidence?.containerNo || 0), validContainer, containerAdjusted);
      const s2 = classifyField(eventInput.value, Number(state.confidence?.eventDate || 0), validDate, dateAdjusted);
      setDot(dotContainer, s1);
      setDot(dotDate, s2);
      setRowHighlight(rowContainer, s1);
      setRowHighlight(rowDate, s2);
      return { s1, s2 };
    }

    containerInput.addEventListener("input", () => {
      errBox.classList.add("hidden");
      evaluate();
    });
    eventInput.addEventListener("input", () => {
      errBox.classList.add("hidden");
      evaluate();
    });

    rerunBtn.addEventListener("click", () => {
      window.location.href = "./processing.html";
    });

    submitBtn.addEventListener("click", async () => {
      const evalResult = evaluate();
      if (evalResult.s1 !== "green" || evalResult.s2 !== "green") {
        errBox.textContent = "Review these items before submitting.";
        errBox.classList.remove("hidden");
        return;
      }

      submitBtn.disabled = true;
      submitBtn.textContent = "Submitting...";
      try {
        const backend = await resolveBackendUrl();
        const fileType = extFromFileName(state.file?.name || "") || "pdf";
        const payload = {
          submissionId: state.submissionId || undefined,
          sourceFileName: state.file?.name || "upload.pdf",
          fileType,
          classifier: state.classifier || "container",
          originalFileName: state.file?.name || null,
          fileContentBase64: dataUrlToBase64(state.file?.dataUrl || ""),
          extracted: {
            container_number: containerInput.value.trim(),
            event_date: eventInput.value.trim(),
          },
          confidence: {
            container_number: 1.0,
            event_date: 1.0,
          },
        };

        const res = await fetch(`${backend}/submit`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });

        if (!res.ok) {
          const t = await res.text();
          throw new Error(`Submit failed (${res.status}): ${t}`);
        }

        const out = await res.json();
        sessionStorage.setItem(LAST_SUBMISSION_KEY, JSON.stringify(out));
        window.location.href = "./confirmation.html";
      } catch (err) {
        errBox.textContent = err?.message || String(err);
        errBox.classList.remove("hidden");
        submitBtn.disabled = false;
        submitBtn.textContent = "Confirm & Submit";
      }
    });

    evaluate();
  }

  function initConfirmationPage() {
    const submissionIdEl = byId("submissionId");
    const statusEl = byId("submissionStatus");
    const raw = sessionStorage.getItem(LAST_SUBMISSION_KEY);
    if (!raw) return;
    try {
      const out = JSON.parse(raw);
      submissionIdEl.textContent = out.submissionId || "-";
      statusEl.textContent = out.status || "-";
    } catch {
      // ignore parse issues
    }
  }

  const page = document.body?.dataset?.page;
  if (page === "upload") initUploadPage();
  if (page === "processing") initProcessingPage();
  if (page === "review") initReviewPage();
  if (page === "confirmation") initConfirmationPage();
})();
