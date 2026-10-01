// Reminders run only while a GrowthLog page is open and the server is available.
// Browser notification permission is requested only after an explicit click.
(() => {
  const main = document.querySelector("main");
  const token = document.querySelector('meta[name="csrf-token"]');
  if (!main || !token) return;
  const userId = document.querySelector('meta[name="user-id"]')?.content;
  const storageKey = `growthlog-reminders:${userId}`;
  let remembered = {};
  try { remembered = JSON.parse(sessionStorage.getItem(storageKey) || "{}"); } catch { /* Storage is optional. */ }

  const panel = document.createElement("section");
  panel.className = "card reminder-panel";
  panel.setAttribute("aria-label", "Local reminders");
  const heading = document.createElement("h2");
  heading.textContent = "Reminders";
  const note = document.createElement("p");
  note.className = "muted";
  note.textContent = "Reminders appear here while GrowthLog is open. Rest days are welcome.";
  const list = document.createElement("div");
  list.setAttribute("aria-live", "polite");
  panel.append(heading, note, list);
  main.append(panel);

  // Each tab remembers what it already notified about; dismissals are saved in SQLite.
  const notified = new Set(Array.isArray(remembered.notified) ? remembered.notified : []);
  let currentKeys = "";
  let browserEnabled = remembered.enabled === true && "Notification" in window && Notification.permission === "granted";
  function remember() {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify({enabled: browserEnabled, notified: [...notified].slice(-200)}));
    } catch { /* In-app reminders work even when session storage is unavailable. */ }
  }
  if ("Notification" in window) {
    const enable = document.createElement("button");
    enable.type = "button";
    enable.className = "button secondary";
    enable.textContent = browserEnabled ? "Browser notifications enabled for this tab" : "Enable browser notifications for this tab";
    enable.disabled = browserEnabled;
    enable.addEventListener("click", async () => {
      try {
        const permission = await Notification.requestPermission();
        browserEnabled = permission === "granted";
        remember();
        enable.textContent = browserEnabled ? "Browser notifications enabled for this tab" : "Browser notifications unavailable; in-app reminders still work";
        enable.disabled = browserEnabled;
        if (browserEnabled) poll();
      } catch {
        enable.textContent = "Browser notifications unavailable; in-app reminders still work";
      }
    });
    panel.append(enable);
  }

  async function dismiss(reminder, button) {
    button.disabled = true;
    try {
      const response = await fetch("/api/reminders/dismiss", {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-CSRFToken": token.content},
        body: JSON.stringify({reminder_key: reminder.reminder_key}),
      });
      if (!response.ok) throw new Error("Dismiss failed");
      currentKeys = "";
      await poll();
    } catch {
      button.disabled = false;
      button.textContent = "Could not dismiss — try again";
    }
  }

  async function poll() {
    try {
      const response = await fetch("/api/reminders", {headers: {"Accept": "application/json"}});
      if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) return;
      const data = await response.json();
      note.textContent = "Reminders appear here while GrowthLog is open. Rest days are welcome.";
      const keys = JSON.stringify(data.reminders);
      if (keys !== currentKeys) {
        currentKeys = keys;
        list.replaceChildren();
        if (!data.reminders.length) {
          const empty = document.createElement("p");
          empty.textContent = "No reminders due right now.";
          list.append(empty);
        }
        for (const reminder of data.reminders) {
          const row = document.createElement("div");
          row.className = "reminder-item actions";
          const link = document.createElement("a");
          link.href = reminder.href;
          link.textContent = `${reminder.title} · ${reminder.when}`;
          const button = document.createElement("button");
          button.type = "button";
          button.className = "button secondary";
          button.textContent = "Dismiss";
          button.addEventListener("click", () => dismiss(reminder, button));
          row.append(link, button);
          list.append(row);
        }
      }
      for (const reminder of data.reminders) {
        if (browserEnabled && Notification.permission === "granted" && !notified.has(reminder.reminder_key)) {
          notified.add(reminder.reminder_key);
          remember();
          try {
            new Notification(reminder.title, {body: reminder.when, tag: reminder.reminder_key});
          } catch {
            // Some browsers grant permission but do not implement desktop notifications.
          }
        }
      }
    } catch {
      note.textContent = "Reminders will resume when GrowthLog is available.";
    }
  }

  poll();
  window.setInterval(poll, 60000);
})();
