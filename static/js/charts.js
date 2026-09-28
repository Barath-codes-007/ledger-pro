/* charts.js — renders Chart.js visualizations from /api/chart-data */

document.addEventListener("DOMContentLoaded", () => {
  const hasCharts = document.querySelector("[data-chart]");
  if (!hasCharts) return;
  loadChartData();
});

const PALETTE = ["#1b6b4a", "#c08a25", "#b3402f", "#3e5c76", "#7c5cbf", "#2b8f9e", "#a3673c", "#5a6b47"];

function themeIsDark() {
  return document.documentElement.getAttribute("data-theme") === "dark";
}

function gridColor() {
  return themeIsDark() ? "rgba(255,255,255,0.06)" : "rgba(18,19,26,0.06)";
}

function textColor() {
  return themeIsDark() ? "#9799ab" : "#6b6d7d";
}

async function loadChartData() {
  try {
    const res = await fetch("/api/chart-data");
    const data = await res.json();
    renderCategoryPie(data);
    renderTrendArea(data);
    renderIncomeVsExpense(data);
    renderWeeklyHeat(data);
  } catch (err) {
    console.error("Failed to load chart data", err);
  }
}

function renderCategoryPie(data) {
  const el = document.querySelector("#categoryPieChart");
  if (!el || !data.category_labels.length) return;
  new Chart(el, {
    type: "doughnut",
    data: {
      labels: data.category_labels,
      datasets: [{ data: data.category_values, backgroundColor: PALETTE, borderWidth: 2, borderColor: getComputedStyle(document.body).getPropertyValue("--surface") || "#fff" }],
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: "68%",
      plugins: { legend: { position: "bottom", labels: { color: textColor(), boxWidth: 10, font: { size: 11 } } } },
    },
  });
}

function renderTrendArea(data) {
  const el = document.querySelector("#trendAreaChart");
  if (!el) return;
  new Chart(el, {
    type: "line",
    data: {
      labels: data.trend_labels,
      datasets: [{
        label: "Daily spending",
        data: data.trend_values,
        borderColor: "#1b6b4a",
        backgroundColor: "rgba(27,107,74,0.12)",
        fill: true, tension: 0.35, pointRadius: 0, borderWidth: 2,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { color: textColor(), maxTicksLimit: 8, font: { size: 10 } } },
        y: { grid: { color: gridColor() }, ticks: { color: textColor(), font: { size: 10 } } },
      },
    },
  });
}

function renderIncomeVsExpense(data) {
  const el = document.querySelector("#incomeExpenseChart");
  if (!el) return;
  new Chart(el, {
    type: "bar",
    data: {
      labels: data.months,
      datasets: [
        { label: "Income", data: data.income_series, backgroundColor: "#1b6b4a", borderRadius: 5, maxBarThickness: 16 },
        { label: "Expense", data: data.expense_series, backgroundColor: "#b3402f", borderRadius: 5, maxBarThickness: 16 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: "bottom", labels: { color: textColor(), boxWidth: 10, font: { size: 11 } } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: textColor(), font: { size: 10 } } },
        y: { grid: { color: gridColor() }, ticks: { color: textColor(), font: { size: 10 } } },
      },
    },
  });
}

function renderWeeklyHeat(data) {
  const el = document.querySelector("#weeklyHeatChart");
  if (!el) return;
  new Chart(el, {
    type: "bar",
    data: {
      labels: data.dow_labels,
      datasets: [{ label: "Spending by weekday (12 wks)", data: data.dow_values, backgroundColor: "#c08a25", borderRadius: 6, maxBarThickness: 28 }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { color: textColor(), font: { size: 10 } } },
        y: { grid: { color: gridColor() }, ticks: { color: textColor(), font: { size: 10 } } },
      },
    },
  });
}
