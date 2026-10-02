// Apply the theme before the stylesheet paints, then connect the header toggle.
(() => {
  const storageKey = "growthlog-theme";
  const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
  let preference = null;
  let toggle = null;

  function validTheme(value) {
    return value === "dark" || value === "light" ? value : null;
  }

  try {
    preference = validTheme(localStorage.getItem(storageKey));
  } catch {
    // The toggle still works if browser storage is unavailable.
  }

  function applyTheme() {
    const theme = preference || (systemTheme.matches ? "dark" : "light");
    document.documentElement.dataset.theme = theme;
    if (toggle) toggle.setAttribute("aria-pressed", String(theme === "dark"));
  }

  applyTheme();

  document.addEventListener("DOMContentLoaded", () => {
    toggle = document.getElementById("theme-toggle");
    if (!toggle) return;
    toggle.hidden = false;
    applyTheme();

    toggle.addEventListener("click", () => {
      preference = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      applyTheme();
      try {
        localStorage.setItem(storageKey, preference);
      } catch {
        // Keep the chosen mode for this page even when it cannot be saved.
      }
    });
  });

  systemTheme.addEventListener("change", () => {
    if (!preference) applyTheme();
  });

  // Keep other open GrowthLog tabs in sync, including when storage is cleared.
  window.addEventListener("storage", (event) => {
    if (event.key === storageKey || event.key === null) {
      preference = validTheme(event.newValue);
      applyTheme();
    }
  });
})();
