/*
 * receipt-camera.js
 * Lets someone photograph a receipt straight from the Add Expense page (and
 * from voice mode) and have it attached to the form's real receipt file
 * input - so it is validated, size-limited and stored by exactly the same
 * server code as a normally uploaded receipt. Nothing is uploaded until the
 * form itself is submitted.
 *
 * Uses the browser's getUserMedia (live camera preview + capture to a JPEG).
 * That needs HTTPS or localhost; where the camera is unavailable or blocked
 * it falls back to the device's own camera app / file picker via
 * <input type="file" capture>, so nobody is left stuck.
 */
(function () {
  "use strict";

  const MAX_DIMENSION = 1600;      // keep photos small enough for the 5 MB receipt limit
  const SIZE_LIMIT = 5 * 1024 * 1024;

  let modal = null;
  let stream = null;
  let pendingBlob = null;
  let onFileCb = null;

  function build() {
    if (modal) return modal;
    modal = document.createElement("div");
    modal.className = "camera-overlay";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-label", "Take a photo of your receipt");
    modal.innerHTML =
      '<div class="camera-modal">' +
      '<div class="camera-title">Take a photo of your receipt</div>' +
      '<div class="camera-stage">' +
      '<video class="camera-video" playsinline muted autoplay></video>' +
      '<img class="camera-shot" alt="Captured receipt preview" style="display:none;">' +
      "</div>" +
      '<div class="camera-error" role="alert" style="display:none;"></div>' +
      '<div class="camera-actions">' +
      '<button type="button" class="btn btn-accent camera-capture"><i class="fa-solid fa-camera"></i> Capture</button>' +
      '<button type="button" class="btn btn-outline camera-retake" style="display:none;">Retake</button>' +
      '<button type="button" class="btn btn-accent camera-use" style="display:none;"><i class="fa-solid fa-check"></i> Use photo</button>' +
      '<button type="button" class="btn btn-outline camera-fallback" style="display:none;"><i class="fa-solid fa-image"></i> Choose a photo instead</button>' +
      '<button type="button" class="btn btn-outline camera-cancel">Cancel</button>' +
      "</div>" +
      '<input type="file" class="camera-fallback-input" accept="image/*" capture="environment" style="display:none;">' +
      "</div>";
    document.body.appendChild(modal);

    q(".camera-capture").addEventListener("click", capture);
    q(".camera-retake").addEventListener("click", retake);
    q(".camera-use").addEventListener("click", usePhoto);
    q(".camera-cancel").addEventListener("click", close);
    q(".camera-fallback").addEventListener("click", () => q(".camera-fallback-input").click());
    q(".camera-fallback-input").addEventListener("change", (e) => {
      const f = e.target.files && e.target.files[0];
      e.target.value = "";
      if (f) deliver(f);
    });
    modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
    document.addEventListener("keydown", (e) => {
      if (modal.classList.contains("open") && e.key === "Escape") close();
    });
    return modal;
  }

  function q(sel) { return modal.querySelector(sel); }
  function show(sel, on) { q(sel).style.display = on ? "" : "none"; }

  function showError(msg) {
    const box = q(".camera-error");
    box.textContent = msg;
    box.style.display = msg ? "block" : "none";
  }

  function stopStream() {
    if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
    const v = modal && q(".camera-video");
    if (v) v.srcObject = null;
  }

  function open(callback) {
    build();
    onFileCb = callback;
    pendingBlob = null;
    showError("");
    show(".camera-video", true);
    show(".camera-shot", false);
    show(".camera-capture", true);
    show(".camera-retake", false);
    show(".camera-use", false);
    show(".camera-fallback", true);
    modal.classList.add("open");

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      noCamera("This browser can't open the camera here (it needs HTTPS or localhost).");
      return;
    }
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false })
      .then((s) => {
        stream = s;
        const v = q(".camera-video");
        v.srcObject = s;
        v.play().catch(() => {});
        q(".camera-capture").focus();
      })
      .catch((err) => {
        const denied = err && (err.name === "NotAllowedError" || err.name === "SecurityError");
        noCamera(denied
          ? "Camera access was blocked. Allow it in your browser's site settings, or choose a photo instead."
          : "No camera was found. You can choose a photo instead.");
      });
  }

  function noCamera(message) {
    showError(message);
    show(".camera-video", false);
    show(".camera-capture", false);
    show(".camera-fallback", true);
  }

  function capture() {
    const v = q(".camera-video");
    if (!v.videoWidth) { showError("The camera isn't ready yet - try again in a moment."); return; }
    const scale = Math.min(1, MAX_DIMENSION / Math.max(v.videoWidth, v.videoHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(v.videoWidth * scale);
    canvas.height = Math.round(v.videoHeight * scale);
    canvas.getContext("2d").drawImage(v, 0, 0, canvas.width, canvas.height);

    const encode = (quality) => new Promise((res) => canvas.toBlob(res, "image/jpeg", quality));
    encode(0.85)
      .then((blob) => (blob && blob.size > SIZE_LIMIT ? encode(0.6) : blob))
      .then((blob) => {
        if (!blob) { showError("Couldn't capture the photo. Please try again."); return; }
        pendingBlob = blob;
        q(".camera-shot").src = URL.createObjectURL(blob);
        show(".camera-video", false);
        show(".camera-shot", true);
        show(".camera-capture", false);
        show(".camera-retake", true);
        show(".camera-use", true);
        q(".camera-use").focus();
      });
  }

  function retake() {
    pendingBlob = null;
    show(".camera-shot", false);
    show(".camera-video", true);
    show(".camera-capture", true);
    show(".camera-retake", false);
    show(".camera-use", false);
  }

  function usePhoto() {
    if (!pendingBlob) return;
    deliver(new File([pendingBlob], "receipt-" + Date.now() + ".jpg", { type: "image/jpeg" }));
  }

  function deliver(file) {
    if (file.size > SIZE_LIMIT) {
      showError("That photo is over the 5 MB receipt limit. Please take or choose a smaller one.");
      return;
    }
    const cb = onFileCb;
    close();
    if (cb) cb(file);
  }

  function close() {
    if (!modal) return;
    stopStream();
    modal.classList.remove("open");
    pendingBlob = null;
  }

  // Put a File into a real <input type="file"> and let the page know.
  function attach(input, file) {
    if (!input || !file) return;
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  window.LedgerReceipt = { capture: open, attach: attach };

  // ---- Manual form wiring: any [data-receipt-camera="<inputId>"] button ---
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-receipt-camera]");
    if (!btn) return;
    const input = document.getElementById(btn.dataset.receiptCamera);
    open((file) => attach(input, file));
  });

  // Preview thumbnail + remove button for any [data-receipt-preview="<inputId>"]
  document.querySelectorAll("[data-receipt-preview]").forEach((box) => {
    const input = document.getElementById(box.dataset.receiptPreview);
    if (!input) return;
    input.addEventListener("change", () => {
      box.innerHTML = "";
      const f = input.files && input.files[0];
      if (!f) return;
      const row = document.createElement("div");
      row.className = "receipt-preview-row";
      if (f.type.startsWith("image/")) {
        const img = document.createElement("img");
        img.alt = "Receipt preview";
        img.src = URL.createObjectURL(f);
        row.appendChild(img);
      }
      const name = document.createElement("span");
      name.textContent = f.name + " · " + Math.max(1, Math.round(f.size / 1024)) + " KB";
      row.appendChild(name);
      const rm = document.createElement("button");
      rm.type = "button";
      rm.className = "voice-ctrl-btn danger";
      rm.textContent = "Remove";
      rm.addEventListener("click", () => {
        input.value = "";
        input.dispatchEvent(new Event("change", { bubbles: true }));
      });
      row.appendChild(rm);
      box.appendChild(row);
    });
  });
})();
