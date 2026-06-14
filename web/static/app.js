// Small client-side helpers for the control panel (no build step, no deps).

// Live filter for the country picker on the Campaign Setup page.
document.addEventListener("DOMContentLoaded", () => {
  const filter = document.getElementById("country-filter");
  if (filter) {
    filter.addEventListener("input", () => {
      const q = filter.value.trim().toLowerCase();
      document.querySelectorAll(".country-item").forEach((el) => {
        const hay = el.getAttribute("data-search") || "";
        el.style.display = hay.includes(q) ? "" : "none";
      });
    });
  }

  // Guard the real-send button with a confirmation.
  document.querySelectorAll('form[action="/actions/send"] button').forEach((btn) => {
    btn.addEventListener("click", (e) => {
      if (!confirm("This sends REAL emails through your mailbox (respecting the daily limit and opt-out list). Continue?")) {
        e.preventDefault();
      }
    });
  });
});
