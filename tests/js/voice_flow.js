/*
 * Front-end flow test for Voice Entry.
 *
 * Loads the REAL rendered Add Expense / Add Income pages from a live Ledger
 * server into jsdom, runs the REAL voice-assistant.js and receipt-camera.js,
 * and replaces only the browser features jsdom lacks with scripted fakes:
 *   - SpeechRecognition  -> "hears" a scripted list of utterances (or errors)
 *   - speechSynthesis    -> instantly "finishes speaking"
 *   - DataTransfer / input.files -> a minimal stand-in (jsdom has no FileList constructor)
 * Everything else - the conversation state, the /api/voice/extract calls
 * (real HTTP to the real Flask app), the review card, Edit, and the final
 * fill-and-submit of the real form - is the production code.
 *
 * Usage: node voice_flow.js http://127.0.0.1:PORT
 */
const assert = require("assert");
const { JSDOM, CookieJar, ResourceLoader, VirtualConsole } = require("jsdom");

const base = process.argv[2];
if (!base) { console.error("usage: node voice_flow.js <base-url>"); process.exit(2); }

class LocalOnlyLoader extends ResourceLoader {
  fetch(url, options) {
    // Load our own scripts/styles; skip external CDNs (fonts, icons).
    if (url.startsWith(base)) return super.fetch(url, options);
    return Promise.resolve(Buffer.from(""));
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(fn, what, timeout = 5000) {
  const start = Date.now();
  for (;;) {
    let v;
    try { v = fn(); } catch (e) { v = false; }
    if (v) return v;
    if (Date.now() - start > timeout) throw new Error("Timed out waiting for: " + what);
    await sleep(10);
  }
}

async function loadPage(path, cookieJar, script) {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (e) => {
    if (!/Not implemented/.test(e.message)) console.error("jsdom error:", e.message);
  });
  const dom = await JSDOM.fromURL(base + path, {
    cookieJar, runScripts: "dangerously", resources: new LocalOnlyLoader(),
    pretendToBeVisual: true, virtualConsole,
    beforeParse(window) {
      window.__script = script.slice();
      window.__fileInputs = [];

      // Scripted microphone: each start() "hears" the next scripted item.
      window.SpeechRecognition = class {
        start() {
          setTimeout(() => {
            if (this.onstart) this.onstart();
            const next = window.__script.shift();
            if (next === undefined) return;               // nothing more to say: stay listening
            setTimeout(() => {
              if (typeof next === "object" && next.error) {
                if (this.onerror) this.onerror({ error: next.error });
                return;
              }
              const result = [{ transcript: next }];
              result.isFinal = true;
              if (this.onresult) this.onresult({ resultIndex: 0, results: [result] });
            }, 5);
          }, 5);
        }
        stop() {}
      };
      window.URL.createObjectURL = () => "blob:test";
      window.URL.revokeObjectURL = () => {};
      window.SpeechSynthesisUtterance = function (text) { this.text = text; };
      window.speechSynthesis = {
        speak(u) { setTimeout(() => u.onstart && u.onstart(), 1); setTimeout(() => u.onend && u.onend(), 3); },
        cancel() {},
      };
      // Minimal DataTransfer so receipt-camera.js's attach() can run.
      window.DataTransfer = class {
        constructor() { this._f = []; this.items = { add: (f) => this._f.push(f) }; }
        get files() { return this._f; }
      };
      // Real fetch to the real server, carrying the session cookie.
      window.fetch = (url, opts = {}) => {
        const abs = new URL(url, base).href;
        const headers = Object.assign({}, opts.headers, { Cookie: cookieJar.getCookieStringSync(abs) });
        return fetch(abs, Object.assign({}, opts, { headers }));
      };
    },
  });
  const { window } = dom;
  await waitFor(() => window.document.readyState === "complete", "page load");
  // jsdom has no FileList constructor; give file inputs a settable `files`.
  window.document.querySelectorAll('input[type="file"]').forEach(makeFilesSettable);
  return dom;
}

function makeFilesSettable(input) {
  let held = [];
  Object.defineProperty(input, "files", { get: () => held, set: (v) => { held = v; }, configurable: true });
  Object.defineProperty(input, "value", {
    get: () => (held.length ? "C:\\fakepath\\" + held[0].name : ""),
    set: (v) => { if (v === "") held = []; }, configurable: true,
  });
}

function captureSubmit(window, formId) {
  const form = window.document.getElementById(formId);
  const box = { done: false, data: null };
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const checked = form.querySelector('input[name="category"]:checked');
    const get = (sel) => (form.querySelector(sel) || {}).value;
    const receipt = form.querySelector("#receipt");
    box.data = {
      category: checked && checked.value, custom_category: get("#custom_category"),
      amount: get("#amount"), date: get("#date"), description: get("#description"),
      payment_mode: get("#payment_mode"), merchant: get("#merchant"), currency: get("#currency"),
      source: get("#source"), receiptName: receipt && receipt.files.length ? receipt.files[0].name : null,
    };
    box.done = true;
  });
  return box;
}

const $ = (doc, sel) => doc.querySelector(sel);
const aiLines = (doc) => [...doc.querySelectorAll(".vh-ai")].map((n) => n.parentElement.textContent);
const reviewRows = (doc) => {
  const rows = {};
  doc.querySelectorAll(".voice-review-row").forEach((r) => {
    rows[r.querySelector(".voice-review-label").textContent] = r.querySelector(".voice-review-value").textContent;
  });
  return rows;
};
const clickEdit = (doc, label) => {
  const row = [...doc.querySelectorAll(".voice-review-row")].find((r) => r.querySelector(".voice-review-label").textContent === label);
  row.querySelector(".voice-review-edit").click();
};

let passed = 0;
async function test(name, fn) {
  try { await fn(); passed++; console.log("  ok   " + name); }
  catch (e) { console.error("  FAIL " + name + "\n       " + (e.stack || e)); process.exitCode = 1; }
}

async function newSession() {
  const cookieJar = new CookieJar();
  const d = await JSDOM.fromURL(base + "/demo/start", { cookieJar });   // seeds an isolated demo account + session
  d.window.close();
  return cookieJar;
}

(async () => {
  console.log("Voice entry front-end flow (real JS, scripted microphone, live server)");

  await test("expense: full conversation incl. 'no' to today's date, receipt photo, Edit, and Save", async () => {
    const jar = await newSession();
    const { window } = await loadPage("/expenses/add", jar,
      ["food", "350 rupees", "lunch", "no", "yesterday", "upi", "swiggy", "yes"]);
    const doc = window.document;
    const submitted = captureSubmit(window, "expenseForm");

    $(doc, "[data-voice-entry]").click();

    // The flow runs on its own until it needs a receipt.
    await waitFor(() => $(doc, ".voice-receipt-panel.open"), "receipt panel");
    const asked = aiLines(doc).join(" | ");
    for (const piece of ["What type of expense", "How much did you spend", "What was it for",
                         "Would you like to use today's date", "What date was it?",
                         "type of payment", "Where did you spend it", "Do you have a receipt"]) {
      assert(asked.includes(piece), "never asked: " + piece + "\n" + asked);
    }
    // the reported bug: after "no" it must ask for the date, not repeat today's-date question
    const todayAsks = aiLines(doc).filter((l) => l.includes("use today's date")).length;
    assert.strictEqual(todayAsks, 1, "today's-date question was repeated");
    assert(!asked.includes("Was this in"), "currency was asked even though 'rupees' was said");
    assert(/day-month-year/.test(asked), "date format was not stated");

    // Receipt step: camera is unavailable in jsdom, so the camera dialog must fall back gracefully.
    $(doc, ".voice-receipt-camera").click();
    const cam = $(doc, ".camera-overlay");
    assert(cam.classList.contains("open"), "camera dialog did not open");
    assert(/can't open the camera/i.test($(doc, ".camera-error").textContent), "no graceful camera fallback message");
    assert.strictEqual($(doc, ".camera-capture").style.display, "none");
    assert.notStrictEqual($(doc, ".camera-fallback").style.display, "none");
    // "Choose a photo instead" -> file arrives -> attached to the real receipt input
    const fallbackInput = $(doc, ".camera-fallback-input");
    makeFilesSettable(fallbackInput);
    const jpeg = new window.File([Uint8Array.from([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3])], "receipt-1.jpg", { type: "image/jpeg" });
    fallbackInput.files = [jpeg];
    fallbackInput.dispatchEvent(new window.Event("change", { bubbles: true }));

    await waitFor(() => $(doc, ".voice-review-card").style.display === "block", "review card");
    assert(!cam.classList.contains("open"), "camera dialog should close after a photo is chosen");
    let rows = reviewRows(doc);
    assert.strictEqual(rows["Category"], "Food");
    assert.strictEqual(rows["Amount"], "INR 350.00");
    assert.strictEqual(rows["Description"], "Lunch");
    assert.strictEqual(rows["Payment"], "UPI");
    assert.strictEqual(rows["Merchant"], "Swiggy");
    assert.strictEqual(rows["Currency"], "INR");
    assert.strictEqual(rows["Receipt"], "Attached (receipt-1.jpg)");
    assert(/\d{4}/.test(rows["Date"]) && rows["Date"] !== "—", "date missing: " + rows["Date"]);
    const firstDate = rows["Date"];

    // Edit just the date by voice - the server supplies the question
    window.__script.push("two days ago");
    clickEdit(doc, "Date");
    await waitFor(() => /What date was it/.test($(doc, ".voice-question").textContent) || $(doc, ".voice-review-card").style.display === "block",
                  "date re-ask");
    await waitFor(() => $(doc, ".voice-review-card").style.display === "block" && reviewRows(doc)["Date"] !== firstDate, "date edited");
    assert.notStrictEqual(reviewRows(doc)["Date"], firstDate);

    // Save fills and submits the REAL form (including the receipt)
    $(doc, ".voice-save-btn").click();
    await waitFor(() => submitted.done, "form submit", 3000);
    const d = submitted.data;
    assert.deepStrictEqual(
      [d.category, d.amount, d.description, d.payment_mode, d.merchant, d.currency, d.receiptName],
      ["Food", "350", "Lunch", "UPI", "Swiggy", "INR", "receipt-1.jpg"]);
    assert(/^\d{4}-\d{2}-\d{2}$/.test(d.date));
    assert($(doc, ".voice-save-btn").disabled, "Save should disable itself (double-submit guard)");
    window.close();
  });

  await test("expense: everything in one sentence skips what was said, asks the rest, and can skip the receipt", async () => {
    const jar = await newSession();
    const { window } = await loadPage("/expenses/add", jar,
      ["I spent 500 rupees on food for lunch at Swiggy by UPI today", "no"]);
    const doc = window.document;
    $(doc, "[data-voice-entry]").click();
    await waitFor(() => $(doc, ".voice-review-card").style.display === "block", "review card");
    const asked = aiLines(doc).join(" | ");
    // (the opening "what type of expense" question is always asked first; the
    // one-sentence answer must then cover everything else)
    const afterOpening = aiLines(doc).slice(1).join(" | ");
    assert(!/What type of expense|How much did you spend|What was it for|use today's date|type of payment|Where did you spend/.test(afterOpening),
      "re-asked something already said: " + afterOpening);
    assert(asked.includes("Do you have a receipt"));
    const rows = reviewRows(doc);
    assert.strictEqual(rows["Receipt"], "None");
    assert.strictEqual(rows["Merchant"], "Swiggy");
    assert.strictEqual(rows["Payment"], "UPI");
    window.close();
  });

  await test("expense: custom category is confirmed, then lands in the form's Other + custom field", async () => {
    const jar = await newSession();
    const { window } = await loadPage("/expenses/add", jar,
      ["pet grooming", "yes", "800", "nail trim", "today", "cash", "skip", "dollars", "no"]);
    const doc = window.document;
    const submitted = captureSubmit(window, "expenseForm");
    $(doc, "[data-voice-entry]").click();
    await waitFor(() => $(doc, ".voice-review-card").style.display === "block", "review card");
    const asked = aiLines(doc).join(" | ");
    assert(asked.includes("Should I use"), "custom category was not confirmed: " + asked);
    assert(asked.includes("Was this in"), "currency should be asked when no currency was said");
    const rows = reviewRows(doc);
    assert.strictEqual(rows["Category"], "Pet Grooming");
    assert.strictEqual(rows["Currency"], "USD");
    $(doc, ".voice-save-btn").click();
    await waitFor(() => submitted.done, "submit");
    assert.strictEqual(submitted.data.category, "Other");
    assert.strictEqual(submitted.data.custom_category, "Pet Grooming");
    assert.strictEqual(submitted.data.currency, "USD");
    window.close();
  });

  await test("expense: unclear answers explain what to say instead of repeating silently", async () => {
    const jar = await newSession();
    const { window } = await loadPage("/expenses/add", jar, ["food", "a lot", "500 rupees"]);
    const doc = window.document;
    $(doc, "[data-voice-entry]").click();
    await waitFor(() => /What was it for/.test($(doc, ".voice-question").textContent), "reached description");
    const asked = aiLines(doc).join(" | ");
    assert(/couldn't understand the amount/i.test(asked) && /500 rupees/.test(asked), asked);
    window.close();
  });

  await test("errors: microphone blocked and no-speech show guidance; Type instead continues the flow", async () => {
    const jar = await newSession();
    // 1st listen -> permission blocked; after typing an answer, the next listen -> heard nothing
    const { window } = await loadPage("/expenses/add", jar, [{ error: "not-allowed" }, { error: "no-speech" }]);
    const doc = window.document;
    $(doc, "[data-voice-entry]").click();
    await waitFor(() => $(doc, ".voice-error-box.show"), "error box");
    assert(/Microphone access was blocked/.test($(doc, ".voice-error-box").textContent));
    assert.notStrictEqual($(doc, ".voice-edit-again").style.display, "none", "Start again should be offered on error");
    // keep going by typing - parity with speaking
    $(doc, ".voice-type-toggle").click();
    $(doc, ".voice-type-input").value = "food";
    $(doc, ".voice-type-submit").click();
    await waitFor(() => /couldn't hear that clearly/.test($(doc, ".voice-error-box").textContent), "no-speech guidance");
    assert(/How much did you spend/.test($(doc, ".voice-question").textContent), "typed answer should have advanced the flow");
    assert(!/function|=>/.test($(doc, ".voice-status-label").textContent), "status badge shows code: " + $(doc, ".voice-status-label").textContent);
    window.close();
  });

  await test("cancel closes the dialog and keeps the manual form untouched", async () => {
    const jar = await newSession();
    const { window } = await loadPage("/expenses/add", jar, ["food"]);
    const doc = window.document;
    $(doc, "[data-voice-entry]").click();
    await waitFor(() => $(doc, ".voice-overlay.open"), "open");
    $(doc, ".voice-controls .voice-cancel").click();
    assert(!$(doc, ".voice-overlay").classList.contains("open"));
    assert.strictEqual($(doc, "#amount").value, "");
    window.close();
  });

  await test("income: conversation fills source, amount, description, date and saves via the real form", async () => {
    const jar = await newSession();
    const { window } = await loadPage("/income/add", jar, ["freelance", "15000", "website development", "yesterday"]);
    const doc = window.document;
    const submitted = captureSubmit(window, "incomeForm");
    $(doc, "[data-voice-entry]").click();
    await waitFor(() => $(doc, ".voice-review-card").style.display === "block", "review card");
    const rows = reviewRows(doc);
    assert.strictEqual(rows["Source"], "Freelance");
    assert.strictEqual(rows["Amount"], "15,000.00");
    assert.strictEqual(rows["Description"], "Website development");
    assert(!/receipt|payment|merchant/i.test(Object.keys(rows).join(" ")), "income should not ask expense-only fields");
    $(doc, ".voice-save-btn").click();
    await waitFor(() => submitted.done, "submit");
    assert.deepStrictEqual([submitted.data.source, submitted.data.amount, submitted.data.description],
      ["Freelance", "15000", "Website development"]);
    window.close();
  });

  await test("manual form: Take photo button opens the camera dialog, falls back, and previews/removes the receipt", async () => {
    const jar = await newSession();
    const { window } = await loadPage("/expenses/add", jar, []);
    const doc = window.document;
    $(doc, "[data-receipt-camera]").click();
    assert($(doc, ".camera-overlay").classList.contains("open"));
    const fallbackInput = $(doc, ".camera-fallback-input");
    makeFilesSettable(fallbackInput);
    fallbackInput.files = [new window.File([Uint8Array.from([0xff, 0xd8, 0xff, 1])], "shot.jpg", { type: "image/jpeg" })];
    fallbackInput.dispatchEvent(new window.Event("change", { bubbles: true }));
    const receipt = $(doc, "#receipt");
    assert.strictEqual(receipt.files.length, 1);
    assert(/shot\.jpg/.test($(doc, ".upload-drop").textContent), "upload label should show the captured file");
    assert(/shot\.jpg/.test($(doc, "[data-receipt-preview]").textContent), "preview row missing");
    $(doc, "[data-receipt-preview] button").click();                 // Remove
    assert.strictEqual(receipt.files.length, 0);
    assert(/Click to upload/.test($(doc, ".upload-drop").textContent), "label should reset after removing");
    window.close();
  });

  console.log(passed + " front-end flow tests passed" + (process.exitCode ? " (with failures)" : ""));
  process.exit(process.exitCode || 0);
})().catch((e) => { console.error(e); process.exit(1); });
