/*
 * voice-assistant.js
 * Drives the AI Voice Financial Entry modal for both the Add Expense and
 * Add Income pages. Speech capture/synthesis are the browser's own
 * Web Speech API (no external service, no API key). Understanding the
 * transcript happens on the server via /api/voice/extract (voice_parser.py)
 * - this file only drives the conversation UI and, once confirmed, fills and
 * submits the REAL existing add-expense/add-income form. There is no
 * separate save path: Save here IS that form's normal submit, so a receipt
 * photo taken here travels in that same multipart request.
 */
(function () {
  "use strict";

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const launchers = document.querySelectorAll("[data-voice-entry]");
  if (!launchers.length) return;

  launchers.forEach((btn) => initVoiceEntry(btn));

  function initVoiceEntry(launchBtn) {
    const context = launchBtn.dataset.voiceEntry; // "expense" | "income"
    const form = document.getElementById(launchBtn.dataset.voiceForm);
    if (!form) return;

    if (!SR) {
      const note = document.createElement("span");
      note.className = "voice-unsupported-note";
      note.textContent = "Voice entry needs Chrome, Edge, or Safari on this device.";
      launchBtn.insertAdjacentElement("afterend", note);
      launchBtn.disabled = true;
      return;
    }

    const overlay = buildModal(context);
    document.body.appendChild(overlay);
    const $ = (sel) => overlay.querySelector(sel);
    const els = {
      close: $(".voice-modal-close"), mic: $(".voice-mic-btn"), status: $(".voice-status-badge"),
      statusLabel: $(".voice-status-label"), waveform: $(".voice-waveform"), question: $(".voice-question"),
      hint: $(".voice-hint"), transcript: $(".voice-transcript"), history: $(".voice-history"),
      replay: $(".voice-replay"), retry: $(".voice-retry"), mute: $(".voice-mute"),
      typeToggle: $(".voice-type-toggle"), typeForm: $(".voice-type-fallback"),
      typeInput: $(".voice-type-input"), typeSubmit: $(".voice-type-submit"),
      cancel: overlay.querySelectorAll(".voice-cancel"), review: $(".voice-review-card"),
      saveRow: $(".voice-save-row"), saveBtn: $(".voice-save-btn"), startAgain: $(".voice-edit-again"),
      error: $(".voice-error-box"), announce: $(".voice-sr-announce"),
      receiptPanel: $(".voice-receipt-panel"), receiptCamera: $(".voice-receipt-camera"),
      receiptUpload: $(".voice-receipt-upload"), receiptSkip: $(".voice-receipt-skip"),
    };
    const receiptInput = context === "expense" ? form.querySelector("#receipt") : null;

    const DRAFT_KEY = "ledger_voice_draft_" + context;
    const MUTE_KEY = "ledger_voice_muted";
    let recognition = null, draft = {}, askingField = null, state = "idle";
    let gotResult = false, speakToken = 0, receiptBusy = false;
    let audioCtx = null, analyser = null, micStream = null, rafId = null;
    let muted = localStorage.getItem(MUTE_KEY) === "1";
    renderMute();

    launchBtn.addEventListener("click", openModal);
    els.close.addEventListener("click", closeModal);
    els.cancel.forEach((b) => b.addEventListener("click", closeModal));
    overlay.addEventListener("click", (e) => { if (e.target === overlay) closeModal(); });
    document.addEventListener("keydown", (e) => {
      // Escape closes the camera first if it's open on top of this dialog.
      if (e.key === "Escape" && overlay.classList.contains("open") &&
          !document.querySelector(".camera-overlay.open")) closeModal();
    });

    els.mic.addEventListener("click", () => {
      if (els.mic.classList.contains("listening")) { stopListening(); setStatus("idle"); }
      else { cancelSpeech(); startListening(); }
    });
    els.replay.addEventListener("click", () => speakOnly(els.question.textContent));
    els.retry.addEventListener("click", () => { hideError(); cancelSpeech(); startListening(); });
    els.mute.addEventListener("click", () => {
      muted = !muted;
      localStorage.setItem(MUTE_KEY, muted ? "1" : "0");
      if (muted) cancelSpeech();
      renderMute();
    });
    els.typeToggle.addEventListener("click", () => {
      els.typeForm.classList.toggle("open");
      if (els.typeForm.classList.contains("open")) els.typeInput.focus();
    });
    els.typeSubmit.addEventListener("click", submitTyped);
    els.typeInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); submitTyped(); } });
    els.saveBtn.addEventListener("click", saveNow);
    els.startAgain.addEventListener("click", startOver);

    // ---- Receipt capture (expense only): camera, upload, or skip ----------
    if (receiptInput) {
      els.receiptCamera.addEventListener("click", () => {
        stopListening();
        if (window.LedgerReceipt) {
          // attach() fires the input's change event, handled just below
          window.LedgerReceipt.capture((file) => window.LedgerReceipt.attach(receiptInput, file));
        } else {
          receiptInput.click();
        }
      });
      els.receiptUpload.addEventListener("click", () => receiptInput.click());
      els.receiptSkip.addEventListener("click", () => {
        receiptInput.value = "";
        receiptInput.dispatchEvent(new Event("change", { bubbles: true }));
        callExtract("skip", "receipt_capture", draft, "Skip the receipt");
      });
      receiptInput.addEventListener("change", () => {
        if (askingField !== "receipt_capture" || receiptBusy) return;
        if (receiptInput.files && receiptInput.files.length) {
          receiptBusy = true;
          callExtract("attached", "receipt_capture", draft, "Receipt attached: " + receiptInput.files[0].name);
        }
      });
    } else {
      els.receiptPanel.remove();
    }

    // ---- Modal open/close -------------------------------------------------
    function openModal() {
      overlay.classList.add("open");
      hideError();
      els.review.style.display = "none";
      els.saveRow.style.display = "none";
      els.receiptPanel.classList.remove("open");
      els.saveBtn.disabled = false;
      receiptBusy = false;
      draft = {};
      try {
        const saved = JSON.parse(sessionStorage.getItem(DRAFT_KEY) || "null");
        if (saved && Object.keys(saved).length) { draft = saved; announce("Resuming your previous unfinished entry."); }
      } catch (e) { /* ignore a corrupt saved draft */ }
      if (receiptInput) {
        const hasFile = receiptInput.files && receiptInput.files.length;
        // A file chosen on the form beats the saved draft; a saved "attached"
        // with no file behind it (page was reloaded) must be asked again.
        if (hasFile) draft.receipt = "attached";
        else if (draft.receipt === "attached" || draft.receipt === "pending") delete draft.receipt;
      }
      askingField = null;
      els.transcript.textContent = "";
      els.history.innerHTML = "";
      setStatus("idle");
      callExtract("", null, draft, null);
      els.mic.focus();
    }

    function closeModal() {
      stopListening();
      cancelSpeech();
      overlay.classList.remove("open");
      launchBtn.focus();
    }

    function startOver() {
      draft = {};
      askingField = null;
      sessionStorage.removeItem(DRAFT_KEY);
      if (receiptInput) { receiptInput.value = ""; receiptInput.dispatchEvent(new Event("change", { bubbles: true })); }
      els.history.innerHTML = "";
      els.review.style.display = "none";
      els.saveRow.style.display = "none";
      els.receiptPanel.classList.remove("open");
      hideError();
      setStatus("idle");
      callExtract("", null, draft, null);
    }

    // ---- Conversation turns ----------------------------------------------
    function postJson(body) {
      return fetch("/api/voice/extract", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": (document.querySelector('meta[name="csrf-token"]') || {}).content || "",
        },
        body: JSON.stringify(Object.assign({ context: context }, body)),
      }).then((r) => { if (!r.ok) throw new Error("extract_failed"); return r.json(); });
    }

    function callExtract(utterance, field, currentDraft, shownText) {
      setStatus("processing");
      postJson({ utterance: utterance, asking_field: field, draft: currentDraft })
        .then((data) => handleResponse(data, shownText === null ? null : (shownText || utterance)))
        .catch(() => showError("I had trouble understanding that. Please try again or type your answer."));
    }

    // Edit buttons on the review card: the question text comes from the
    // server so the wording lives in one place.
    function reask(field) {
      setStatus("processing");
      postJson({ reask: field, draft: draft })
        .then((data) => handleResponse(data, null))
        .catch(() => showError("I had trouble with that. Please try again or type your answer."));
    }

    function handleResponse(data, userText) {
      receiptBusy = false;
      draft = data.draft;
      sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
      askingField = data.field;
      els.question.textContent = data.question;
      els.hint.textContent = data.hint || "";
      els.review.style.display = "none";
      els.saveRow.style.display = "none";
      els.receiptPanel.classList.remove("open");
      hideError();
      if (userText) addHistory("you", userText);

      if (data.ready) {
        showReview();
        setStatus("confirming");
        return;
      }
      addHistory("ai", data.question);
      if (data.field === "receipt_capture") {
        els.receiptPanel.classList.add("open");
        setStatus("idle", "Waiting for your receipt");
        speakOnly(data.question);          // no listening - they're using the camera/buttons
        return;
      }
      setStatus("idle");
      speakThenListen(data.question);
    }

    function submitTyped() {
      const text = els.typeInput.value.trim();
      if (!text) return;
      els.typeInput.value = "";
      els.typeForm.classList.remove("open");
      stopListening();
      cancelSpeech();
      callExtract(text, askingField, draft);
    }

    // ---- Speech recognition ----------------------------------------------
    function startListening() {
      stopListening();
      gotResult = false;
      recognition = new SR();
      recognition.lang = "en-IN";
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;

      recognition.onstart = () => {
        setStatus("listening");
        els.mic.classList.add("listening");
        els.transcript.textContent = "I'm listening...";
        els.transcript.classList.remove("is-final");
        startWaveform();
      };
      recognition.onresult = (event) => {
        let interim = "", final = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const t = event.results[i][0].transcript;
          if (event.results[i].isFinal) final += t; else interim += t;
        }
        if (interim) { els.transcript.textContent = interim; els.transcript.classList.remove("is-final"); }
        if (final) {
          gotResult = true;
          els.transcript.textContent = final;
          els.transcript.classList.add("is-final");
          stopListening();
          callExtract(final.trim(), askingField, draft);
        }
      };
      recognition.onerror = (event) => {
        stopListening();
        if (event.error === "not-allowed" || event.error === "service-not-allowed") {
          showError("Microphone access was blocked. Allow it in your browser's site settings, or type your answer instead.");
        } else if (event.error === "no-speech") {
          showError("I couldn't hear that clearly. You can try again or type your answer.");
        } else if (event.error !== "aborted") {
          showError("Voice recognition hit a problem. Please try again or type your answer.");
        }
      };
      recognition.onend = () => {
        els.mic.classList.remove("listening");
        stopWaveform();
        // The browser ended the session on its own with nothing heard.
        if (!gotResult && state === "listening" && overlay.classList.contains("open")) {
          showError("I couldn't hear that clearly. You can try again or type your answer.");
        }
      };
      try { recognition.start(); }
      catch (e) { showError("Couldn't start the microphone. Please try again or type your answer."); }
    }

    function stopListening() {
      if (recognition) {
        try { recognition.onend = null; recognition.onerror = null; recognition.stop(); } catch (e) { /* already stopped */ }
        recognition = null;
      }
      els.mic.classList.remove("listening");
      stopWaveform();
    }

    // ---- Mic level waveform (Web Audio API) -------------------------------
    function startWaveform() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
      navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
        if (!els.mic.classList.contains("listening")) { stream.getTracks().forEach((t) => t.stop()); return; }
        micStream = stream;
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const source = audioCtx.createMediaStreamSource(stream);
        analyser = audioCtx.createAnalyser();
        analyser.fftSize = 64;
        source.connect(analyser);
        const data = new Uint8Array(analyser.frequencyBinCount);
        const bars = els.waveform.querySelectorAll("span");
        const step = () => {
          analyser.getByteFrequencyData(data);
          bars.forEach((bar, i) => { bar.style.height = Math.max(4, Math.round(((data[i * 2] || 0) / 255) * 26)) + "px"; });
          rafId = requestAnimationFrame(step);
        };
        step();
      }).catch(() => { /* decorative - recognition works without it */ });
    }

    function stopWaveform() {
      if (rafId) cancelAnimationFrame(rafId);
      rafId = null;
      if (micStream) { micStream.getTracks().forEach((t) => t.stop()); micStream = null; }
      if (audioCtx) { audioCtx.close().catch(() => {}); audioCtx = null; }
      els.waveform.querySelectorAll("span").forEach((bar) => (bar.style.height = "4px"));
    }

    // ---- Speech synthesis -------------------------------------------------
    // The mic only opens AFTER the AI finishes speaking, otherwise it would
    // transcribe the assistant's own voice as the person's answer.
    function cancelSpeech() {
      speakToken++;
      if (window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch (e) { /* ignore */ } }
    }

    function speakThenListen(text) {
      stopListening();
      const token = ++speakToken;
      let started = false;
      const go = () => {
        if (started || token !== speakToken || !overlay.classList.contains("open")) return;
        started = true;
        startListening();
      };
      if (muted || !window.speechSynthesis || !text) { go(); return; }
      try {
        window.speechSynthesis.cancel();
        const u = new SpeechSynthesisUtterance(text);
        u.lang = "en-IN";
        u.rate = 1.02;
        u.onstart = () => { if (token === speakToken) setStatus("speaking"); };
        u.onend = go;
        u.onerror = go;
        window.speechSynthesis.speak(u);
        setTimeout(go, Math.max(4000, text.length * 95)); // safety net if onend never fires
      } catch (e) { go(); }
    }

    function speakOnly(text) {
      cancelSpeech();
      if (muted || !window.speechSynthesis || !text) return;
      try {
        const u = new SpeechSynthesisUtterance(text);
        u.lang = "en-IN";
        u.rate = 1.02;
        window.speechSynthesis.speak(u);
      } catch (e) { /* nice-to-have only */ }
    }

    function renderMute() {
      els.mute.innerHTML = muted
        ? '<i class="fa-solid fa-volume-xmark"></i> Voice off'
        : '<i class="fa-solid fa-volume-high"></i> Voice on';
      els.mute.setAttribute("aria-pressed", muted ? "true" : "false");
    }

    // ---- Status / UI helpers ----------------------------------------------
    function setStatus(next, labelOverride) {
      state = next;
      const labels = {
        idle: "Ready", listening: "I'm listening...", speaking: "Speaking...",
        processing: "Understanding your entry...", confirming: "Ready for confirmation",
        saving: "Saving...", success: "Saved", error: "Needs attention",
      };
      const label = labelOverride || labels[next] || next;
      els.status.className = "voice-status-badge is-" + (next === "speaking" ? "thinking" : next);
      els.statusLabel.textContent = label;
      els.status.querySelector(".voice-status-dot").classList.toggle("pulse", next === "listening" || next === "processing");
      announce(label);
    }
    function announce(text) { els.announce.textContent = text; }

    function addHistory(who, text) {
      const row = document.createElement("div");
      row.className = "vh-row";
      const tag = document.createElement("span");
      tag.className = who === "ai" ? "vh-ai" : "vh-user";
      tag.textContent = who === "ai" ? "AI: " : "You: ";
      row.appendChild(tag);
      row.appendChild(document.createTextNode(text));
      els.history.appendChild(row);
      els.history.scrollTop = els.history.scrollHeight;
    }

    function showError(msg) {
      els.error.textContent = msg;
      els.error.classList.add("show");
      els.startAgain.style.display = "inline-flex";
      setStatus("error");
    }
    function hideError() {
      els.error.classList.remove("show");
      els.startAgain.style.display = "none";
    }

    // ---- Review / confirmation --------------------------------------------
    function formatDate(iso) {
      const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
      if (!m) return iso || "—";
      return new Date(+m[1], +m[2] - 1, +m[3]).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
    }
    function formatMoney(v, currency) {
      const n = Number(v);
      if (v === undefined || v === null || isNaN(n)) return "—";
      return (currency ? currency + " " : "") + n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function showReview() {
      const msg = "Here's what I have. Should I save this?";
      els.question.textContent = msg;
      els.hint.textContent = "Use Edit next to any line to change just that one.";
      addHistory("ai", msg);
      speakOnly(msg);
      els.review.innerHTML = "";

      const receiptText = draft.receipt === "attached"
        ? "Attached" + (receiptInput && receiptInput.files[0] ? " (" + receiptInput.files[0].name + ")" : "")
        : "None";
      const rows = context === "expense"
        ? [["Category", draft.category || "—", "category"],
           ["Amount", formatMoney(draft.amount, draft.currency), "amount"],
           ["Description", draft.description || "—", "description"],
           ["Date", formatDate(draft.date), "date"],
           ["Payment", draft.payment_mode || "—", "payment_mode"],
           ["Merchant", draft.merchant || "—", "merchant"],
           ["Currency", draft.currency || "—", "currency"],
           ["Receipt", receiptText, "receipt"]]
        : [["Source", draft.source || "—", "source"],
           ["Amount", formatMoney(draft.amount), "amount"],
           ["Description", draft.description || "—", "description"],
           ["Date", formatDate(draft.date), "date"]];

      rows.forEach(([label, value, field]) => {
        const row = document.createElement("div");
        row.className = "voice-review-row";
        const left = document.createElement("div");
        const l = document.createElement("div");
        l.className = "voice-review-label"; l.textContent = label;
        const v = document.createElement("div");
        v.className = "voice-review-value"; v.textContent = String(value);
        left.appendChild(l); left.appendChild(v);
        const edit = document.createElement("button");
        edit.type = "button"; edit.className = "voice-review-edit"; edit.textContent = "Edit";
        edit.setAttribute("aria-label", "Edit " + label);
        edit.addEventListener("click", () => reask(field));
        row.appendChild(left); row.appendChild(edit);
        els.review.appendChild(row);
      });
      els.review.style.display = "block";
      els.saveRow.style.display = "flex";
    }

    // ---- Save: fill the REAL form and submit it normally -------------------
    function saveNow() {
      els.saveBtn.disabled = true; // double-submit guard
      setStatus("saving");
      if (context === "expense") fillExpenseForm(draft); else fillIncomeForm(draft);
      sessionStorage.removeItem(DRAFT_KEY);
      setStatus("success");
      setTimeout(() => (form.requestSubmit ? form.requestSubmit() : form.submit()), 250);
    }

    function fillExpenseForm(d) {
      if (d.category) {
        const known = form.querySelector('input[name="category"][value="' + cssEscape(d.category) + '"]');
        if (known) {
          known.checked = true;
          known.dispatchEvent(new Event("change", { bubbles: true }));
        } else {
          const other = form.querySelector('input[name="category"][value="Other"]');
          if (other) { other.checked = true; other.dispatchEvent(new Event("change", { bubbles: true })); }
          const custom = form.querySelector("#custom_category");
          if (custom) custom.value = d.category;
        }
      }
      setVal("#amount", d.amount);
      setVal("#date", d.date);
      setVal("#description", d.description);
      setVal("#payment_mode", d.payment_mode);
      setVal("#merchant", d.merchant);
      setVal("#currency", d.currency);
      // the receipt, if any, is already in the form's own file input
    }

    function fillIncomeForm(d) {
      setVal("#source", d.source);
      setVal("#amount", d.amount);
      setVal("#date", d.date);
      setVal("#description", d.description);
    }

    function setVal(selector, value) {
      if (value === undefined || value === null || value === "") return;
      const el = form.querySelector(selector);
      if (el) el.value = value;
    }

    function cssEscape(s) {
      return window.CSS && CSS.escape ? CSS.escape(s) : s.replace(/["\\]/g, "\\$&");
    }
  }

  // ---- Modal markup (built once per launcher) -----------------------------
  function buildModal(context) {
    const title = context === "expense" ? "Expense" : "Income";
    const overlay = document.createElement("div");
    overlay.className = "voice-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", "AI " + title + " Assistant");
    overlay.innerHTML =
      '<div class="voice-modal">' +
      '<button type="button" class="voice-modal-close" aria-label="Close voice assistant">&times;</button>' +
      '<div class="voice-sr-announce" aria-live="polite"></div>' +
      '<div class="voice-header"><div class="voice-eyebrow">AI ' + title + " Assistant</div>" +
      '<div class="voice-title">Voice Entry</div></div>' +
      '<div class="voice-mic-stage">' +
      '<button type="button" class="voice-mic-btn" aria-label="Start or stop listening"><i class="fa-solid fa-microphone"></i></button>' +
      '<span class="voice-status-badge is-idle"><span class="voice-status-dot"></span><span class="voice-status-label">Ready</span></span>' +
      '<div class="voice-waveform" aria-hidden="true">' + "<span></span>".repeat(10) + "</div>" +
      '<div class="voice-question" aria-live="polite"></div>' +
      '<div class="voice-hint"></div>' +
      '<div class="voice-transcript"></div>' +
      "</div>" +
      '<div class="voice-receipt-panel">' +
      '<button type="button" class="voice-ctrl-btn voice-receipt-camera"><i class="fa-solid fa-camera"></i> Take photo</button>' +
      '<button type="button" class="voice-ctrl-btn voice-receipt-upload"><i class="fa-solid fa-file-arrow-up"></i> Upload file</button>' +
      '<button type="button" class="voice-ctrl-btn voice-receipt-skip">Skip receipt</button>' +
      "</div>" +
      '<div class="voice-history" aria-hidden="true"></div>' +
      '<div class="voice-error-box" role="alert"></div>' +
      '<div class="voice-controls">' +
      '<button type="button" class="voice-ctrl-btn voice-replay"><i class="fa-solid fa-rotate-left"></i> Replay</button>' +
      '<button type="button" class="voice-ctrl-btn voice-retry"><i class="fa-solid fa-arrows-rotate"></i> Retry</button>' +
      '<button type="button" class="voice-ctrl-btn voice-type-toggle"><i class="fa-solid fa-keyboard"></i> Type instead</button>' +
      '<button type="button" class="voice-ctrl-btn voice-mute" aria-pressed="false"></button>' +
      '<button type="button" class="voice-ctrl-btn voice-edit-again" style="display:none;"><i class="fa-solid fa-rotate"></i> Start again</button>' +
      '<button type="button" class="voice-ctrl-btn danger voice-cancel"><i class="fa-solid fa-xmark"></i> Cancel</button>' +
      "</div>" +
      '<div class="voice-type-fallback">' +
      '<input type="text" class="voice-type-input" placeholder="Type your answer..." aria-label="Type your answer">' +
      '<button type="button" class="voice-ctrl-btn voice-type-submit">Send</button>' +
      "</div>" +
      '<div class="voice-review-card" style="display:none;"></div>' +
      '<div class="voice-save-row" style="display:none;">' +
      '<button type="button" class="btn btn-outline voice-cancel">Cancel</button>' +
      '<button type="button" class="btn btn-accent voice-save-btn"><i class="fa-solid fa-check"></i> Save</button>' +
      "</div></div>";
    return overlay;
  }
})();
