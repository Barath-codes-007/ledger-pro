/* main.js — shared interactivity: dark mode, live search, toasts, sidebar, loaders */

document.addEventListener("DOMContentLoaded", () => {
  initPageLoader();
  initDarkMode();
  initSidebarToggle();
  initLiveSearch();
  initToasts();
  initCountUp();
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
        headers: { "Content-Type": "application/json" },
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
