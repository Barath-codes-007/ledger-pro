/* main.js — shared interactivity: dark mode, live search, toasts, sidebar, loaders */

document.addEventListener("DOMContentLoaded", () => {
  initPageLoader();
  initDarkMode();
  initSidebarToggle();
  initLiveSearch();
  initToasts();
  initCountUp();
  initCommandPalette();
});

/* ---------- Page loader (fades out once DOM ready) ---------- */
function initPageLoader() {
  const loader = document.querySelector(".page-loader");
  if (!loader) return;
  window.addEventListener("load", () => {
    setTimeout(() => loader.classList.add("hide"), 200);
  });
}

/* ---------- Dark mode ---------- */
function initDarkMode() {
  const root = document.documentElement;
  const toggleBtns = document.querySelectorAll(".theme-toggle");
  const stored = localStorage.getItem("theme");
  if (stored === "dark") {
    root.setAttribute("data-theme", "dark");
    updateThemeIcons(true);
  }

  toggleBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const isDark = root.getAttribute("data-theme") === "dark";
      if (isDark) {
        root.removeAttribute("data-theme");
        localStorage.setItem("theme", "light");
      } else {
        root.setAttribute("data-theme", "dark");
        localStorage.setItem("theme", "dark");
      }
      updateThemeIcons(!isDark);

      fetch("/settings/theme", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": (document.querySelector('meta[name="csrf-token"]') || {}).content || "",
        },
        body: JSON.stringify({ dark_mode: !isDark }),
      }).catch(() => {});
    });
  });
}

function updateThemeIcons(isDark) {
  document.querySelectorAll(".theme-toggle i").forEach((icon) => {
    icon.className = isDark ? "fa-solid fa-sun" : "fa-solid fa-moon";
  });
}

/* ---------- Sidebar (mobile) ---------- */
function initSidebarToggle() {
  const toggle = document.querySelector(".menu-toggle");
  const sidebar = document.querySelector(".sidebar");
  if (!toggle || !sidebar) return;
  toggle.addEventListener("click", () => sidebar.classList.toggle("open"));
  document.addEventListener("click", (e) => {
    if (!sidebar.contains(e.target) && !toggle.contains(e.target)) {
      sidebar.classList.remove("open");
    }
  });
}

/* ---------- Live search ---------- */
function initLiveSearch() {
  const input = document.querySelector("#globalSearch");
  const resultsBox = document.querySelector("#searchResults");
  if (!input || !resultsBox) return;

  let debounceTimer;
  input.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    const q = input.value.trim();
    if (!q) {
      resultsBox.classList.remove("show");
      resultsBox.innerHTML = "";
      return;
    }
    debounceTimer = setTimeout(() => runSearch(q, resultsBox), 250);
  });

  document.addEventListener("click", (e) => {
    if (!input.contains(e.target) && !resultsBox.contains(e.target)) {
      resultsBox.classList.remove("show");
    }
  });
}

async function runSearch(q, resultsBox) {
  try {
    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
    const data = await res.json();
    resultsBox.innerHTML = "";
    if (!data.length) {
      resultsBox.innerHTML = `<div class="sr-empty">No transactions match "${escapeHtml(q)}"</div>`;
    } else {
      data.forEach((item) => {
        const row = document.createElement("a");
        row.href = "/expenses";
        row.className = "sr-item";
        row.innerHTML = `<span>${escapeHtml(item.category)} — ${escapeHtml(item.description || "")}</span><span class="mono">${item.amount.toFixed(2)}</span>`;
        resultsBox.appendChild(row);
      });
    }
    resultsBox.classList.add("show");
  } catch (err) {
    console.error("Search failed", err);
  }
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

/* ---------- Toasts ---------- */
function initToasts() {
  document.querySelectorAll(".toast .close-toast").forEach((btn) => {
    btn.addEventListener("click", () => btn.closest(".toast").remove());
  });
  document.querySelectorAll(".toast").forEach((toast) => {
    setTimeout(() => toast.remove(), 5000);
  });
}

/* ---------- Animated count-up for stat values ---------- */
function initCountUp() {
  document.querySelectorAll("[data-countup]").forEach((el) => {
    const target = parseFloat(el.dataset.countup);
    if (isNaN(target)) return;
    const duration = 900;
    const start = performance.now();
    function tick(now) {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = (target * eased).toFixed(2);
      if (progress < 1) requestAnimationFrame(tick);
      else el.textContent = target.toFixed(2);
    }
    requestAnimationFrame(tick);
  });
}

/* ---------- Confirm dialogs for delete forms ---------- */
document.addEventListener("submit", (e) => {
  const form = e.target;
  if (form.matches("[data-confirm]")) {
    const msg = form.getAttribute("data-confirm") || "Are you sure?";
    if (!confirm(msg)) e.preventDefault();
  }
});

/* ---------- Category picker: show/hide custom category field ---------- */
document.addEventListener("change", (e) => {
  if (e.target.matches('input[name="category"]')) {
    const customField = document.querySelector("#customCategoryField");
    if (customField) {
      customField.style.display = e.target.value === "Other" ? "block" : "none";
    }
  }
});

/* ---------- Command palette & keyboard shortcuts ---------- */
function initCommandPalette() {
  const routes = window.LEDGER_ROUTES || {};
  const commands = [
    { label: "Add Expense", key: "N", url: routes.add_expense },
    { label: "Add Income", key: "I", url: routes.add_income },
    { label: "Accounts & Transfers", key: "A", url: routes.accounts },
    { label: "Budget", key: "B", url: routes.budget },
    { label: "Goals", key: "G", url: routes.goals },
    { label: "Reports", key: "R", url: routes.reports },
    { label: "Net Worth", url: routes.net_worth },
    { label: "Subscriptions", url: routes.subscriptions },
    { label: "Toggle Dark Mode", action: () => document.querySelector(".theme-toggle")?.click() },
  ].filter((c) => c.url || c.action);

  const overlay = document.createElement("div");
  overlay.className = "cmdk-overlay";
  overlay.innerHTML = `
    <div class="cmdk-box">
      <input type="text" class="cmdk-input" placeholder="Search commands...">
      <div class="cmdk-list"></div>
    </div>`;
  overlay.style.cssText = "display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:9999;align-items:flex-start;justify-content:center;padding-top:12vh;";
  document.body.appendChild(overlay);
  const box = overlay.querySelector(".cmdk-box");
  box.style.cssText = "background:var(--card-bg,#fff);border-radius:12px;width:min(480px,90vw);box-shadow:0 20px 60px rgba(0,0,0,.3);overflow:hidden;";
  const input = overlay.querySelector(".cmdk-input");
  input.style.cssText = "width:100%;box-sizing:border-box;padding:16px;border:0;border-bottom:1px solid var(--border,#e2e8f0);font-size:15px;outline:none;background:transparent;color:inherit;";
  const list = overlay.querySelector(".cmdk-list");
  list.style.cssText = "max-height:320px;overflow-y:auto;";

  function render(filter = "") {
    const f = filter.toLowerCase();
    list.innerHTML = "";
    commands.filter((c) => c.label.toLowerCase().includes(f)).forEach((c) => {
      const row = document.createElement("div");
      row.textContent = c.label;
      row.style.cssText = "padding:12px 16px;cursor:pointer;font-size:14px;";
      row.addEventListener("mouseenter", () => (row.style.background = "rgba(127,127,127,.12)"));
      row.addEventListener("mouseleave", () => (row.style.background = "transparent"));
      row.addEventListener("click", () => {
        close();
        if (c.action) c.action();
        else if (c.url) window.location.href = c.url;
      });
      list.appendChild(row);
    });
  }

  function open() {
    overlay.style.display = "flex";
    input.value = "";
    render();
    setTimeout(() => input.focus(), 0);
  }
  function close() {
    overlay.style.display = "none";
  }

  input.addEventListener("input", () => render(input.value));
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close();
  });

  document.addEventListener("keydown", (e) => {
    const tag = (e.target.tagName || "").toLowerCase();
    const typing = tag === "input" || tag === "textarea" || e.target.isContentEditable;

    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      overlay.style.display === "flex" ? close() : open();
      return;
    }
    if (overlay.style.display === "flex") {
      if (e.key === "Escape") close();
      return;
    }
    if (typing) return;

    if (e.key === "/") {
      const search = document.getElementById("globalSearch");
      if (search) {
        e.preventDefault();
        search.focus();
      }
      return;
    }
    const shortcut = { n: "add_expense", i: "add_income", a: "accounts", b: "budget", g: "goals", r: "reports" }[e.key.toLowerCase()];
    if (shortcut && routes[shortcut]) {
      window.location.href = routes[shortcut];
    }
  });
}
