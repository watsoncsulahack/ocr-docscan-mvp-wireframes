(function () {
  const PENDING_FILE_KEY = "ocr.pending.file";
  const REVIEW_STATE_KEY = "ocr.review.state";
  const LAST_SUBMISSION_KEY = "ocr.last.submission";
  const ADMIN_MOCK_DB_KEY = "ocr.admin.mockdb.v1";
  let BACKEND_BASE_CACHE = null;

  function setBackendStatus(online) {
    const wrap = byId("backendStatus");
    const label = byId("backendStatusLabel");
    if (!wrap) return;

    wrap.classList.toggle("online", !!online);
    wrap.classList.toggle("offline", !online);

    if (label) {
      label.textContent = online ? "online" : "offline";
    } else {
      wrap.textContent = `Backend: ${online ? "online" : "offline"}`;
    }
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
        containerNo: Number(scan?.confidence?.containerNo ?? (containerNo ? 0.96 : 0.4)),
        eventDate: Number(scan?.confidence?.date ?? (eventDate ? 0.82 : 0.35)),
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
      evaluate();
      errBox.classList.add("hidden");

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
            container_number: Number(state.confidence?.containerNo ?? 0.5),
            event_date: Number(state.confidence?.eventDate ?? 0.5),
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

  async function initRecordsPage() {
    const body = byId("recordsBody");
    const resetBtn = byId("resetDemoBtn");
    if (!body) return;

    async function loadRows() {
      body.innerHTML = '<tr><td colspan="3">Loading...</td></tr>';
      try {
        const backend = await resolveBackendUrl();
        const res = await fetch(`${backend}/records`);
        if (!res.ok) {
          const t = await res.text();
          throw new Error(t || `HTTP ${res.status}`);
        }

        const out = await res.json();
        const rows = Array.isArray(out?.records) ? out.records : [];
        if (!rows.length) {
          try {
            const subRes = await fetch(`${backend}/submissions`);
            const subOut = subRes.ok ? await subRes.json() : { submissions: [] };
            const submissions = Array.isArray(subOut?.submissions) ? subOut.submissions : [];
            const duplicateCount = submissions.filter((s) => s.status === "DUPLICATE").length;
            const approvedCount = submissions.filter((s) => s.status === "APPROVED").length;

            if (submissions.length) {
              body.innerHTML = `<tr><td colspan="3">No approved records yet. Submissions found: ${submissions.length} (approved: ${approvedCount}, duplicate: ${duplicateCount}).</td></tr>`;
            } else {
              body.innerHTML = '<tr><td colspan="3">No records yet.</td></tr>';
            }
          } catch {
            body.innerHTML = '<tr><td colspan="3">No records yet.</td></tr>';
          }
          return;
        }

        body.innerHTML = "";
        rows.forEach((r) => {
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td>${r.containerNo || "-"}</td>
            <td>${r.date || "-"}</td>
            <td>${r.corrected ? "Yes" : "No"}</td>
          `;
          body.appendChild(tr);
        });
      } catch (err) {
        body.innerHTML = `<tr><td colspan="3">Failed to load records: ${err?.message || err}</td></tr>`;
      }
    }

    resetBtn?.addEventListener("click", async () => {
      try {
        const backend = await resolveBackendUrl();
        const res = await fetch(`${backend}/reset-demo`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirm: "RESET_DEMO" }),
        });
        if (!res.ok) {
          const t = await res.text();
          throw new Error(t || `HTTP ${res.status}`);
        }
        await loadRows();
      } catch (err) {
        body.innerHTML = `<tr><td colspan="3">Reset failed: ${err?.message || err}</td></tr>`;
      }
    });

    await loadRows();
  }

  async function initAdminPage() {
    const queueBody = byId("adminQueueBody");
    const filterEl = byId("adminQueueFilter");
    const refreshBtn = byId("adminRefresh");
    const detailWrap = byId("adminDetail");
    const modalBackdrop = byId("adminModalBackdrop");
    const modalCloseBtn = byId("adminModalClose");
    const sourcePreviewWrap = byId("adminSourcePreviewWrap");
    const sourcePreviewImg = byId("adminSourcePreview");
    const selectedHint = byId("adminSelectedHint");
    const submissionIdEl = byId("adminSubmissionId");
    const submissionStatusEl = byId("adminSubmissionStatus");
    const ruleResultsEl = byId("adminRuleResults");
    const fieldEditorEl = byId("adminFieldEditor");
    const actorEl = byId("adminActor");
    const noteEl = byId("adminNote");
    const rejectWrapEl = byId("adminRejectWrap");
    const rejectReasonEl = byId("adminRejectReason");
    const actionMsgEl = byId("adminActionMsg");
    const saveReviewBtn = byId("adminSaveReview");
    const approveBtn = byId("adminApprove");
    const rejectBtn = byId("adminReject");
    const rejectCancelBtn = byId("adminRejectCancel");
    const auditListEl = byId("adminAuditList");

    if (!queueBody || !filterEl) return;

    let selectedSubmissionId = null;
    let selectedBundle = null;
    let rejectConfirmArmed = false;
    const forceMock = new URLSearchParams(window.location.search).get("mockdb") === "1";
    const isGitHubPages = /github\.io$/i.test(window.location.hostname || "");
    let useMockDb = forceMock;

    function openDetailModal() {
      selectedHint?.classList.add("hidden");
      detailWrap?.classList.remove("hidden");
      modalBackdrop?.classList.remove("hidden");
      document.body.classList.add("modal-open");
    }

    function closeDetailModal() {
      detailWrap?.classList.add("hidden");
      modalBackdrop?.classList.add("hidden");
      document.body.classList.remove("modal-open");
      setRejectMode(false);
      if (!selectedSubmissionId) {
        selectedHint?.classList.remove("hidden");
      }
    }

    function setRejectMode(on) {
      rejectConfirmArmed = !!on;
      if (rejectWrapEl) {
        rejectWrapEl.classList.toggle("hidden", !rejectConfirmArmed);
      }
      if (rejectCancelBtn) {
        rejectCancelBtn.classList.toggle("hidden", !rejectConfirmArmed);
      }
      if (rejectBtn) {
        rejectBtn.classList.toggle("danger", rejectConfirmArmed);
        rejectBtn.textContent = rejectConfirmArmed ? "Confirm Reject" : "Reject";
      }
      if (!rejectConfirmArmed && rejectReasonEl) {
        rejectReasonEl.value = "";
      }
    }

    function nowIso() {
      return new Date().toISOString();
    }

    function seedMockDb() {
      const seeded = {
        submissions: [
          {
            id: "SUB-20260510-0001",
            source_file_name: "dock_receipt_alpha.pdf",
            classifier: "container",
            status: "NEEDS_REVIEW",
            created_at: nowIso(),
          },
          {
            id: "SUB-20260510-0002",
            source_file_name: "yard_scan_beta.jpg",
            classifier: "container",
            status: "DUPLICATE",
            created_at: nowIso(),
          },
          {
            id: "SUB-20260510-0003",
            source_file_name: "gate_capture_gamma.png",
            classifier: "container",
            status: "APPROVED",
            created_at: nowIso(),
          },
        ],
        details: {
          "SUB-20260510-0001": {
            submission: { id: "SUB-20260510-0001", status: "NEEDS_REVIEW" },
            extractedFields: [
              { field_name: "container_number", field_value: "MSCU1234567", source: "ocr", confidence: 0.74 },
              { field_name: "event_date", field_value: "10/05/2026", source: "ocr", confidence: 0.81 },
            ],
            reviewTasks: [{ status: "OPEN", reason_code: "LOW_CONFIDENCE", assigned_to: "admin" }],
            audit: [{ created_at: nowIso(), action: "QUEUED", actor: "system", details: "{\"note\":\"Auto-ingested\"}" }],
          },
          "SUB-20260510-0002": {
            submission: { id: "SUB-20260510-0002", status: "DUPLICATE" },
            extractedFields: [
              { field_name: "container_number", field_value: "MSCU1234567", source: "ocr", confidence: 0.95 },
              { field_name: "event_date", field_value: "10/05/2026", source: "ocr", confidence: 0.93 },
            ],
            reviewTasks: [{ status: "OPEN", reason_code: "POSSIBLE_DUPLICATE", assigned_to: "admin" }],
            audit: [{ created_at: nowIso(), action: "FLAG_DUPLICATE", actor: "rules", details: "{\"match\":\"SUB-20260510-0001\"}" }],
          },
          "SUB-20260510-0003": {
            submission: { id: "SUB-20260510-0003", status: "APPROVED" },
            extractedFields: [
              { field_name: "container_number", field_value: "OOLU7654321", source: "ocr", confidence: 0.98 },
              { field_name: "event_date", field_value: "09/05/2026", source: "ocr", confidence: 0.97 },
            ],
            reviewTasks: [{ status: "DONE", reason_code: "NONE", assigned_to: "admin" }],
            audit: [{ created_at: nowIso(), action: "APPROVED", actor: "admin", details: "{\"note\":\"Looks good\"}" }],
          },
        },
      };
      localStorage.setItem(ADMIN_MOCK_DB_KEY, JSON.stringify(seeded));
      return seeded;
    }

    function loadMockDb() {
      try {
        const raw = localStorage.getItem(ADMIN_MOCK_DB_KEY);
        if (!raw) return seedMockDb();
        const parsed = JSON.parse(raw);
        if (!parsed?.submissions || !parsed?.details) return seedMockDb();
        return parsed;
      } catch {
        return seedMockDb();
      }
    }

    function saveMockDb(db) {
      localStorage.setItem(ADMIN_MOCK_DB_KEY, JSON.stringify(db));
    }

    function setMockStatus() {
      const wrap = byId("backendStatus");
      if (!wrap) return;
      wrap.classList.remove("online", "offline");
      wrap.textContent = "Backend: demo mock DB";
    }

    async function mockFetchJson(path, init) {
      const db = loadMockDb();
      const method = (init?.method || "GET").toUpperCase();

      if (path === "/admin/flagged") {
        const submissions = db.submissions.filter((s) => s.status === "NEEDS_REVIEW" || s.status === "DUPLICATE");
        return { submissions };
      }
      if (path.startsWith("/admin/submissions")) {
        const url = new URL(`http://local${path}`);
        const status = url.searchParams.get("status");
        return { submissions: status ? db.submissions.filter((s) => s.status === status) : db.submissions };
      }
      if (path.startsWith("/submission/")) {
        const id = decodeURIComponent(path.split("/submission/")[1] || "");
        return db.details[id] || { submission: { id, status: "UNKNOWN" }, extractedFields: [], reviewTasks: [], audit: [] };
      }

      const m = path.match(/^\/(review|approve|reject)\/(.+)$/);
      if (m && method === "POST") {
        const action = m[1];
        const id = decodeURIComponent(m[2]);
        const payload = init?.body ? JSON.parse(init.body) : {};
        const detail = db.details[id];
        const sub = db.submissions.find((s) => s.id === id);
        if (!detail || !sub) throw new Error("Mock submission not found");

        if (action === "review") {
          const corrections = payload?.corrections || {};
          detail.extractedFields = detail.extractedFields.map((f) => ({
            ...f,
            field_value: Object.prototype.hasOwnProperty.call(corrections, f.field_name)
              ? corrections[f.field_name]
              : f.field_value,
            source: "admin_review",
          }));
          sub.status = "NEEDS_REVIEW";
          detail.submission.status = sub.status;
          detail.audit.unshift({ created_at: nowIso(), action: "REVIEW_EDITED", actor: payload?.actor || "admin", details: JSON.stringify({ note: payload?.note || null }) });
        }

        if (action === "approve") {
          const verifiedFields = payload?.verifiedFields || {};
          detail.extractedFields = detail.extractedFields.map((f) => ({
            ...f,
            field_value: Object.prototype.hasOwnProperty.call(verifiedFields, f.field_name)
              ? verifiedFields[f.field_name]
              : f.field_value,
            source: "admin_approved",
          }));
          sub.status = "APPROVED";
          detail.submission.status = sub.status;
          detail.audit.unshift({ created_at: nowIso(), action: "APPROVED", actor: payload?.actor || "admin", details: JSON.stringify({ note: payload?.note || null }) });
        }

        if (action === "reject") {
          sub.status = "REJECTED";
          detail.submission.status = sub.status;
          detail.audit.unshift({ created_at: nowIso(), action: "REJECTED", actor: payload?.actor || "admin", details: JSON.stringify({ reason: payload?.reason || "unspecified" }) });
        }

        saveMockDb(db);
        return { status: sub.status, submissionId: id };
      }

      throw new Error(`Mock route not implemented: ${path}`);
    }

    async function fetchJson(path, init) {
      if (useMockDb) {
        return mockFetchJson(path, init);
      }
      try {
        const backend = await resolveBackendUrl();
        const res = await fetch(`${backend}${path}`, init);
        const text = await res.text();
        if (!res.ok) {
          throw new Error(text || `HTTP ${res.status}`);
        }
        setBackendStatus(true);
        try {
          const parsed = JSON.parse(text);
          if (parsed && typeof parsed === "object") {
            parsed.__backendBase = backend;
          }
          return parsed;
        } catch {
          throw new Error(`Invalid JSON response for ${path}`);
        }
      } catch (err) {
        setBackendStatus(false);
        if (isGitHubPages || forceMock) {
          useMockDb = true;
          setMockStatus();
          return mockFetchJson(path, init);
        }
        throw err;
      }
    }

    function getEditableFieldsFromUI() {
      const out = {};
      const inputs = fieldEditorEl.querySelectorAll("[data-field-name]");
      inputs.forEach((input) => {
        const key = input.getAttribute("data-field-name");
        out[key] = (input.value || "").trim();
      });
      return out;
    }

    function setActionMessage(msg, isError = false) {
      if (!actionMsgEl) return;
      actionMsgEl.textContent = msg || "";
      actionMsgEl.style.color = isError ? "#dc2626" : "inherit";
    }

    function renderAudit(auditRows) {
      if (!auditListEl) return;
      const rows = Array.isArray(auditRows) ? auditRows : [];
      if (!rows.length) {
        auditListEl.innerHTML = "<li>No audit entries.</li>";
        return;
      }
      auditListEl.innerHTML = "";
      rows.slice(0, 20).forEach((a) => {
        const li = document.createElement("li");
        let details = a.details || "";
        try {
          details = JSON.stringify(JSON.parse(details), null, 0);
        } catch {
          // keep raw
        }
        li.textContent = `${a.created_at || ""} · ${a.action || ""} · ${a.actor || ""} · ${details || ""}`;
        auditListEl.appendChild(li);
      });
    }

    function renderFieldEditor(bundle) {
      if (!fieldEditorEl) return;
      const fields = Array.isArray(bundle?.extractedFields) ? bundle.extractedFields : [];
      if (!fields.length) {
        fieldEditorEl.innerHTML = '<p class="note">No extracted fields to edit.</p>';
        return;
      }

      fieldEditorEl.innerHTML = "";
      fields.forEach((f) => {
        const row = document.createElement("label");
        row.className = "field-row";
        row.innerHTML = `
          <span class="field-label">${f.field_name}</span>
          <input class="input" data-field-name="${f.field_name}" value="${(f.field_value || "").replace(/"/g, "&quot;")}" />
          <small class="field-help">source=${f.source || "-"} confidence=${f.confidence == null ? "-" : f.confidence}</small>
        `;
        fieldEditorEl.appendChild(row);
      });
    }

    function renderRuleSummary(bundle) {
      if (!ruleResultsEl) return;
      const tasks = Array.isArray(bundle?.reviewTasks) ? bundle.reviewTasks : [];
      if (!tasks.length) {
        ruleResultsEl.textContent = "No review tasks recorded.";
        return;
      }
      const latest = tasks[0];
      ruleResultsEl.textContent = `Review task: ${latest.status || "-"} · reason=${latest.reason_code || "-"} · assigned_to=${latest.assigned_to || "-"}`;
    }

    function renderSourcePreview(bundle) {
      if (!sourcePreviewWrap || !sourcePreviewImg) return;

      const directDataUrl = bundle?.previewDataUrl || "";
      const backendBase = bundle?.__backendBase || "";
      const previewPath = bundle?.previewUrl || "";
      const backendPreviewUrl = previewPath && previewPath.startsWith("/") ? `${backendBase}${previewPath}` : previewPath;
      const imageSrc = directDataUrl || backendPreviewUrl;

      if (!imageSrc) {
        sourcePreviewWrap.classList.add("hidden");
        sourcePreviewImg.removeAttribute("src");
        return;
      }

      sourcePreviewImg.src = imageSrc;
      sourcePreviewWrap.classList.remove("hidden");
    }

    async function loadSubmissionDetail(submissionId) {
      selectedSubmissionId = submissionId;
      setActionMessage("");
      setRejectMode(false);
      openDetailModal();

      const out = await fetchJson(`/submission/${encodeURIComponent(submissionId)}`);
      selectedBundle = out;

      submissionIdEl.textContent = out?.submission?.id || submissionId;
      submissionStatusEl.textContent = out?.submission?.status || "-";
      renderSourcePreview(out);
      renderRuleSummary(out);
      renderFieldEditor(out);
      renderAudit(out?.audit || []);
    }

    async function loadQueue() {
      queueBody.innerHTML = '<tr><td colspan="6">Loading...</td></tr>';
      setActionMessage("");
      const mode = filterEl.value || "flagged";
      let out;
      if (mode === "flagged") {
        out = await fetchJson("/admin/flagged");
      } else if (mode === "all") {
        out = await fetchJson("/admin/submissions");
      } else {
        out = await fetchJson(`/admin/submissions?status=${encodeURIComponent(mode)}`);
      }

      const rows = Array.isArray(out?.submissions) ? out.submissions : [];
      if (!rows.length) {
        queueBody.innerHTML = '<tr><td colspan="6">No submissions in this queue.</td></tr>';
        selectedSubmissionId = null;
        selectedBundle = null;
        closeDetailModal();
        return rows;
      }

      const stillPresent = selectedSubmissionId && rows.some((r) => r?.id === selectedSubmissionId);
      if (!stillPresent) {
        selectedSubmissionId = null;
        selectedBundle = null;
        closeDetailModal();
      }

      queueBody.innerHTML = "";
      rows.forEach((s) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${s.id || "-"}</td>
          <td>${s.source_file_name || "-"}</td>
          <td>${s.classifier || "-"}</td>
          <td>${s.status || "-"}</td>
          <td>${s.created_at || "-"}</td>
          <td><button class="btn secondary" data-open-id="${s.id}">Open</button></td>
        `;
        queueBody.appendChild(tr);
      });

      return rows;
    }

    queueBody.addEventListener("click", async (e) => {
      const target = e.target;
      if (!(target instanceof HTMLElement)) return;
      const id = target.getAttribute("data-open-id");
      if (!id) return;
      try {
        await loadSubmissionDetail(id);
      } catch (err) {
        setActionMessage(`Failed to load submission: ${err?.message || err}`, true);
      }
    });

    modalCloseBtn?.addEventListener("click", () => {
      closeDetailModal();
    });

    modalBackdrop?.addEventListener("click", () => {
      closeDetailModal();
    });

    detailWrap?.addEventListener("click", (e) => {
      if (e.target === detailWrap) {
        closeDetailModal();
      }
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && detailWrap && !detailWrap.classList.contains("hidden")) {
        closeDetailModal();
      }
    });

    filterEl.addEventListener("change", async () => {
      try {
        await loadQueue();
      } catch (err) {
        queueBody.innerHTML = `<tr><td colspan="6">Failed to load queue: ${err?.message || err}</td></tr>`;
      }
    });

    refreshBtn?.addEventListener("click", async () => {
      try {
        const rows = await loadQueue();
        if (selectedSubmissionId && Array.isArray(rows) && rows.some((r) => r?.id === selectedSubmissionId)) {
          await loadSubmissionDetail(selectedSubmissionId);
        }
      } catch (err) {
        setActionMessage(`Refresh failed: ${err?.message || err}`, true);
      }
    });

    saveReviewBtn?.addEventListener("click", async () => {
      if (!selectedSubmissionId) return;
      try {
        const corrections = getEditableFieldsFromUI();
        const out = await fetchJson(`/review/${encodeURIComponent(selectedSubmissionId)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            actor: (actorEl?.value || "admin").trim() || "admin",
            note: (noteEl?.value || "").trim() || null,
            corrections,
          }),
        });
        setActionMessage(`Saved review edits. Status: ${out.status}`);
        await loadQueue();
        await loadSubmissionDetail(selectedSubmissionId);
      } catch (err) {
        setActionMessage(`Save review failed: ${err?.message || err}`, true);
      }
    });

    approveBtn?.addEventListener("click", async () => {
      if (!selectedSubmissionId) return;
      try {
        setRejectMode(false);
        const verifiedFields = getEditableFieldsFromUI();
        const out = await fetchJson(`/approve/${encodeURIComponent(selectedSubmissionId)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            actor: (actorEl?.value || "admin").trim() || "admin",
            note: (noteEl?.value || "").trim() || null,
            verifiedFields,
          }),
        });
        setActionMessage(`Approved submission. Status: ${out.status}`);
        await loadQueue();
        await loadSubmissionDetail(selectedSubmissionId);
      } catch (err) {
        setActionMessage(`Approve failed: ${err?.message || err}`, true);
      }
    });

    rejectBtn?.addEventListener("click", async () => {
      if (!selectedSubmissionId) return;

      if (!rejectConfirmArmed) {
        setRejectMode(true);
        setActionMessage("Provide a reject reason, then click Confirm Reject.");
        return;
      }

      const reason = (rejectReasonEl?.value || "").trim();
      if (!reason) {
        setActionMessage("Reject reason is required.", true);
        return;
      }
      try {
        const out = await fetchJson(`/reject/${encodeURIComponent(selectedSubmissionId)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            actor: (actorEl?.value || "admin").trim() || "admin",
            reason,
          }),
        });
        setActionMessage(`Rejected submission. Status: ${out.status}`);
        setRejectMode(false);
        await loadQueue();
        await loadSubmissionDetail(selectedSubmissionId);
      } catch (err) {
        setActionMessage(`Reject failed: ${err?.message || err}`, true);
      }
    });

    rejectCancelBtn?.addEventListener("click", () => {
      setRejectMode(false);
      setActionMessage("");
    });

    try {
      if (forceMock) setMockStatus();
      await probeBackendStatus();
      await loadQueue();
    } catch (err) {
      queueBody.innerHTML = `<tr><td colspan="6">Failed to load queue: ${err?.message || err}</td></tr>`;
    }
  }

  const page = document.body?.dataset?.page;
  if (page === "upload") initUploadPage();
  if (page === "processing") initProcessingPage();
  if (page === "review") initReviewPage();
  if (page === "confirmation") initConfirmationPage();
  if (page === "records") initRecordsPage();
  if (page === "admin") initAdminPage();
})();
