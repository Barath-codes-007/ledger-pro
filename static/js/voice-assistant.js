/*
 * voice-assistant.js
 * Drives the AI Voice Financial Entry modal for both the Add Expense and
 * Add Income pages. Speech capture/synthesis are the browser's own
 * Web Speech API (no external service, no API key, works offline from
 * the app's point of view). Understanding the transcript happens on the
 * server via /api/voice/extract (voice_parser.py) - this file only
 * drives the conversation UI and, once confirmed, fills and submits the
 * REAL existing add-expense/add-income form. There is no separate save
 * path: Save here IS that form's normal submit.
 */
(function () {
  "use strict";

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const launchers = document.querySelectorAll("[data-voice-entry]");
  if (!launchers.length) return;

  launchers.forEach((btn) => initVoiceEntry(btn));

  function initVoiceEntry(launchBtn) {
    const context = launchBtn.dataset.voiceEntry; // "expense" | "income"
    const formId = launchBtn.dataset.voiceForm;
    const form = document.getElementById(formId);
    if (!form) return;

    if (!SR) {
      const note = document.createElement("span");
      note.className = "voice-unsupported-note";
      note.textContent = "Voice entry needs Chrome, Edge, or Safari on this device.";
      launchBtn.insertAdjacentElement("afterend", note);
      launchBtn.disabled = true;
      return;
    }

    // ---- Build the modal once per launcher -----------------------------
    const overlay = buildModal(context);
    document.body.appendChild(overlay);

    const els = {
      close: overlay.querySelector(".voice-modal-close"),
      mic: overlay.querySelector(".voice-mic-btn"),
      status: overlay.querySelector(".voice-status-badge"),
      statusLabel: overlay.querySelector(".voice-status-label"),
      waveform: overlay.querySelector(".voice-waveform"),
      question: overlay.querySelector(".voice-question"),
      transcript: overlay.querySelector(".voice-transcript"),
      history: overlay.querySelector(".voice-history"),
      replay: overlay.querySelector(".voice-replay"),
      retry: overlay.querySelector(".voice-retry"),
      typeToggle: overlay.querySelector(".voice-type-toggle"),
      typeForm: overlay.querySelector(".voice-type-fallback"),
      typeInput: overlay.querySelector(".voice-type-input"),
      typeSubmit: overlay.querySelector(".voice-type-submit"),
      cancel: overlay.querySelector(".voice-cancel"),
      review: overlay.querySelector(".voice-review-card"),
      saveRow: overlay.querySelector(".voice-save-row"),
      saveBtn: overlay.querySelector(".voice-save-btn"),
      editBtn: overlay.querySelector(".voice-edit-again"),
      error: overlay.querySelector(".voice-error-box"),
      announce: overlay.querySelector(".voice-sr-announce"),
    };

    const DRAFT_KEY = "ledger_voice_draft_" + context;
    let recognition = null;
    let draft = {};
    let askingField = null;
    let audioCtx = null, analyser = null, micStream = null, rafId = null;

    launchBtn.addEventListener("click", () => openModal());
    els.close.addEventListener("click", closeModal);
    els.cancel.addEventListener("click", closeModal);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) closeModal(); });
    document.addEventListener("keydown", (e) => {
      if (overlay.classList.contains("open") && e.key === "Escape") closeModal();
    });

    els.mic.addEventListener("click", () => {
      if (els.mic.classList.contains("listening")) stopListening();
      else startListening();
    });
    els.replay.addEventListener("click", () => speak(els.question.textContent));
    els.retry.addEventListener("click", () => { hideError(); startListening(); });
    els.typeToggle.addEventListener("click", () => {
      els.typeForm.classList.toggle("open");
      if (els.typeForm.classList.contains("open")) els.typeInput.focus();
    });
    els.typeSubmit.addEventListener("click", submitTyped);
    els.typeInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); submitTyped(); } });
    els.saveBtn.addEventListener("click", saveNow);
    els.editBtn.addEventListener("click", () => {
      draft = {};
      askingField = null;
      sessionStorage.removeItem(DRAFT_KEY);
      els.history.innerHTML = "";
      els.review.style.display = "none";
      els.saveRow.style.display = "none";
      els.editBtn.style.display = "none";
      hideError();
      setStatus("idle");
      askField(draft, true);
    });
    // Per-field Edit buttons on the review card are built dynamically in
    // showReview() (the card doesn't exist in the DOM until then), where
    // their click handlers are attached directly.

    // ---- Modal open/close -----------------------------------------------
    function openModal() {
      overlay.classList.add("open");
      els.error.classList.remove("show");
      els.editBtn.style.display = "none";
      els.review.style.display = "none";
      els.saveRow.style.display = "none";
      const saved = sessionStorage.getItem(DRAFT_KEY);
      if (saved) {
        try {
          const parsed = JSON.parse(saved);
          if (parsed && Object.keys(parsed).length) {
            draft = parsed;
            announce("Resuming your previous unfinished entry.");
          }
        } catch (e) { /* ignore corrupt draft */ }
      } else {
        draft = {};
      }
      askingField = null;
      setStatus("idle");
      els.transcript.textContent = "";
      els.history.innerHTML = "";
      askField(draft, true);
      els.mic.focus();
    }

    function closeModal() {
      stopListening();
      overlay.classList.remove("open");
      launchBtn.focus();
    }

    // ---- Conversation turn -----------------------------------------------
    function askField(currentDraft, speakFirst) {
      callExtract("", askingField, currentDraft, speakFirst);
    }

    function callExtract(utterance, field, currentDraft, speakIt) {
      setStatus("processing");
      fetch("/api/voice/extract", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": (document.querySelector('meta[name="csrf-token"]') || {}).content || "",
        },
        body: JSON.stringify({ context: context, utterance: utterance, asking_field: field, draft: currentDraft }),
      })
        .then((r) => {
          if (!r.ok) throw new Error("extract_failed");
          return r.json();
        })
        .then((data) => {
          draft = data.draft;
          sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
          askingField = data.field;
          els.question.textContent = data.question;
          if (utterance) addHistory("you", utterance);
          if (data.ready) {
            showReview();
            setStatus("confirming");
          } else {
            addHistory("ai", data.question);
            setStatus("idle");
            if (speakIt !== false) speak(data.question);
            startListening();
          }
        })
        .catch(() => showError("I had trouble understanding that. Please try again or type your answer."));
    }

    function submitTyped() {
      const text = els.typeInput.value.trim();
      if (!text) return;
      els.typeInput.value = "";
      els.typeForm.classList.remove("open");
      stopListening();
      callExtract(text, askingField, draft, true);
    }

    // ---- Speech recognition ----------------------------------------------
    function startListening() {
      stopListening();
      recognition = new SR();
      recognition.lang = "en-IN";
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;

      recognition.onstart = () => {
        setStatus("listening");
        els.mic.classList.add("listening");
        els.transcript.textContent = "Listening...";
        els.transcript.classList.remove("is-final");
        startWaveform();
      };
      recognition.onresult = (event) => {
        let interim = "", final = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const t = event.results[i][0].transcript;
          if (event.results[i].isFinal) final += t;
          else interim += t;
        }
        if (interim) {
          els.transcript.textContent = interim;
          els.transcript.classList.remove("is-final");
        }
        if (final) {
          els.transcript.textContent = final;
          els.transcript.classList.add("is-final");
          stopListening();
          callExtract(final.trim(), askingField, draft, true);
        }
      };
      recognition.onerror = (event) => {
        stopListening();
        if (event.error === "not-allowed" || event.error === "service-not-allowed") {
          showError("Microphone access was blocked. You can allow it in your browser's site settings, or type your answer below.");
        } else if (event.error === "no-speech") {
          showError("I couldn't hear that clearly. You can try again or type your answer.");
        } else {
          showError("Voice recognition hit a problem. Please try again or type your answer.");
        }
      };
      recognition.onend = () => {
        els.mic.classList.remove("listening");
        stopWaveform();
        if (document.activeElement !== els.typeInput) setStatus((s) => s);
      };

      try {
        recognition.start();
      } catch (e) {
        showError("Couldn't start the microphone. Please try again or type your answer.");
      }
    }

    function stopListening() {
      if (recognition) {
        try { recognition.onend = null; recognition.stop(); } catch (e) { /* already stopped */ }
        recognition = null;
      }
      els.mic.classList.remove("listening");
      stopWaveform();
    }

    // ---- Lightweight mic level waveform (Web Audio API) -------------------
    function startWaveform() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
      navigator.mediaDevices.getUserMedia({ audio: true })
        .then((stream) => {
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
            bars.forEach((bar, i) => {
              const v = data[i * 2] || 0;
              bar.style.height = Math.max(4, Math.round((v / 255) * 26)) + "px";
            });
            rafId = requestAnimationFrame(step);
          };
          step();
        })
        .catch(() => { /* waveform is decorative - recognition works without it */ });
    }

    function stopWaveform() {
      if (rafId) cancelAnimationFrame(rafId);
      rafId = null;
      if (micStream) { micStream.getTracks().forEach((t) => t.stop()); micStream = null; }
      if (audioCtx) { audioCtx.close().catch(() => {}); audioCtx = null; }
      els.waveform.querySelectorAll("span").forEach((bar) => (bar.style.height = "4px"));
    }

    // ---- Speech synthesis (AI "speaks" the question) ----------------------
    function speak(text) {
      if (!window.speechSynthesis || !text) return;
      try {
        window.speechSynthesis.cancel();
        const u = new SpeechSynthesisUtterance(text);
        u.lang = "en-IN";
        u.rate = 1.02;
        window.speechSynthesis.speak(u);
      } catch (e) { /* speech synthesis is a nice-to-have, never block on it */ }
    }

    // ---- Status / UI helpers ----------------------------------------------
    function setStatus(state) {
      const labels = {
        idle: "Ready", listening: "Listening...", processing: "Understanding your entry...",
        confirming: "Ready for confirmation", saving: "Saving...", success: "Saved", error: "Error",
      };
      els.status.className = "voice-status-badge is-" + state;
      els.statusLabel.textContent = labels[state] || state;
      const dot = els.status.querySelector(".voice-status-dot");
      dot.classList.toggle("pulse", state === "listening" || state === "processing");
      announce(labels[state] || state);
    }

    function announce(text) { els.announce.textContent = text; }

    function addHistory(who, text) {
      const row = document.createElement("div");
      row.className = "vh-row";
      row.innerHTML = '<span class="' + (who === "ai" ? "vh-ai" : "vh-user") + '">' +
        (who === "ai" ? "AI: " : "You: ") + "</span>" + escapeHtml(text);
      els.history.appendChild(row);
      els.history.scrollTop = els.history.scrollHeight;
    }

    function escapeHtml(s) {
      const d = document.createElement("div");
      d.textContent = s;
      return d.innerHTML;
    }

    function showError(msg) {
      els.error.textContent = msg;
      els.error.classList.add("show");
      els.editBtn.style.display = "inline-flex";
      setStatus("error");
    }
    function hideError() {
      els.error.classList.remove("show");
      els.editBtn.style.display = "none";
    }

    function questionFor(field, ctx) {
      const map = {
        category: "What type of expense is this?",
        amount: ctx === "expense" ? "How much did you spend?" : "How much did you receive?",
        description: ctx === "expense" ? "What was it for?" : "What's the source, in a bit more detail?",
        date: "Would you like to use today's date?",
        source: "What type of income is this?",
      };
      return map[field] || "Can you say that again?";
    }

    // ---- Review / confirmation --------------------------------------------
    function showReview() {
      els.question.textContent = "Here's what I have. Should I save this?";
      addHistory("ai", els.question.textContent);
      speak(els.question.textContent);
      els.review.innerHTML = "";

      const rows = context === "expense"
        ? [["Category", draft.category || "—", "category"],
           ["Amount", formatMoney(draft.amount), "amount"],
           ["Description", draft.description || "—", "description"],
           ["Date", draft.date || "—", "date"]]
        : [["Source", draft.source || "—", "source"],
           ["Amount", formatMoney(draft.amount), "amount"],
           ["Description", draft.description || "—", "description"],
           ["Date", draft.date || "—", "date"]];

      rows.forEach(([label, value, field]) => {
        const row = document.createElement("div");
        row.className = "voice-review-row";
        row.innerHTML =
          '<div><div class="voice-review-label">' + label + '</div>' +
          '<div class="voice-review-value">' + escapeHtml(String(value)) + "</div></div>" +
          '<button type="button" class="voice-review-edit" data-edit-field="' + field + '">Edit</button>';
        els.review.appendChild(row);
      });
      els.review.querySelectorAll("[data-edit-field]").forEach((b) => {
        b.addEventListener("click", () => {
          askingField = b.dataset.editField;
          els.review.style.display = "none";
          els.saveRow.style.display = "none";
          setStatus("idle");
          const q = questionFor(askingField, context);
          els.question.textContent = q;
          addHistory("ai", q);
          speak(q);
          startListening();
        });
      });

      els.review.style.display = "block";
      els.saveRow.style.display = "flex";
    }

    function formatMoney(v) {
      if (v === undefined || v === null) return "—";
      const n = Number(v);
      return isNaN(n) ? "—" : n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    // ---- Save: fill the REAL form and submit it normally -------------------
    function saveNow() {
      els.saveBtn.disabled = true; // double-submit guard
      setStatus("saving");

      if (context === "expense") {
        fillExpenseForm(draft);
      } else {
        fillIncomeForm(draft);
      }
      sessionStorage.removeItem(DRAFT_KEY);
      setStatus("success");
      setTimeout(() => form.requestSubmit ? form.requestSubmit() : form.submit(), 250);
    }

    function fillExpenseForm(d) {
      if (d.category) {
        const known = form.querySelector('input[name="category"][value="' + cssEscape(d.category) + '"]');
        if (known) {
          known.checked = true;
          known.dispatchEvent(new Event("change", { bubbles: true }));
        } else {
          const other = form.querySelector('input[name="category"][value="Other"]');
          if (other) {
            other.checked = true;
            other.dispatchEvent(new Event("change", { bubbles: true }));
          }
          const custom = form.querySelector("#custom_category");
          if (custom) custom.value = d.category;
        }
      }
      setVal("#amount", d.amount);
      setVal("#date", d.date);
      setVal("#description", d.description);
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

  // ---- Modal markup (built once per launcher, identical for both contexts)
  function buildModal(context) {
    const overlay = document.createElement("div");
    overlay.className = "voice-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", "AI " + (context === "expense" ? "Expense" : "Income") + " Assistant");
    overlay.innerHTML =
      '<div class="voice-modal">' +
      '<button type="button" class="voice-modal-close" aria-label="Close voice assistant">&times;</button>' +
      '<div class="voice-sr-announce" aria-live="polite"></div>' +
      '<div class="voice-header">' +
      '<div class="voice-eyebrow">AI ' + (context === "expense" ? "Expense" : "Income") + " Assistant</div>" +
      '<div class="voice-title">Voice Entry</div>' +
      "</div>" +
      '<div class="voice-mic-stage">' +
      '<button type="button" class="voice-mic-btn" aria-label="Start or stop listening"><i class="fa-solid fa-microphone"></i></button>' +
      '<span class="voice-status-badge is-idle"><span class="voice-status-dot"></span><span class="voice-status-label">Ready</span></span>' +
      '<div class="voice-waveform" aria-hidden="true">' + "<span></span>".repeat(10) + "</div>" +
      '<div class="voice-question" aria-live="polite"></div>' +
      '<div class="voice-transcript"></div>' +
      "</div>" +
      '<div class="voice-history" aria-hidden="true"></div>' +
      '<div class="voice-error-box" role="alert"></div>' +
      '<div class="voice-controls">' +
      '<button type="button" class="voice-ctrl-btn voice-replay"><i class="fa-solid fa-rotate-left"></i> Replay</button>' +
      '<button type="button" class="voice-ctrl-btn voice-retry"><i class="fa-solid fa-arrows-rotate"></i> Retry</button>' +
      '<button type="button" class="voice-ctrl-btn voice-type-toggle"><i class="fa-solid fa-keyboard"></i> Type instead</button>' +
      '<button type="button" class="voice-ctrl-btn voice-edit-again" style="display:none;"><i class="fa-solid fa-rotate"></i> Start again</button>' +
      '<button type="button" class="voice-ctrl-btn danger voice-cancel"><i class="fa-solid fa-xmark"></i> Cancel</button>' +
      "</div>" +
      '<div class="voice-type-fallback">' +
      '<input type="text" class="voice-type-input" placeholder="Type your answer..." aria-label="Type your answer">' +
      '<button type="button" class="voice-ctrl-btn voice-type-submit">Send</button>' +
      "</div>" +
      '<div class="voice-review-card" style="display:none;"></div>' +
      '<div class="voice-save-row" style="display:none;">' +
      '<button type="button" class="btn btn-outline voice-cancel-save voice-cancel">Cancel</button>' +
      '<button type="button" class="btn btn-accent voice-save-btn"><i class="fa-solid fa-check"></i> Save</button>' +
      "</div>" +
      "</div>";
    return overlay;
  }
})();
