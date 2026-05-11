const POLL_INTERVAL_MS = 30 * 60 * 1000;
const STORAGE_KEY = "info-collector:last-read-generated-at";

function toastElement() {
  return document.getElementById("update-toast");
}

function currentCount() {
  const toast = toastElement();
  return Number(toast?.dataset.articleCount ?? "0");
}

function markRead(generatedAt) {
  if (generatedAt) {
    localStorage.setItem(STORAGE_KEY, generatedAt);
  }
}

function showToast(newCount, generatedAt) {
  const toast = toastElement();
  if (!toast) {
    return;
  }
  const message = toast.querySelector("[data-update-toast-message]");
  if (message) {
    message.textContent = `新しい記事 ${newCount} 件`;
  }
  toast.dataset.generatedAt = generatedAt;
  toast.classList.remove("hidden");
}

async function pollArticles() {
  try {
    const response = await fetch("/articles.json", {
      cache: "no-cache",
      headers: { Accept: "application/json" },
    });
    if (response.status === 304 || !response.ok) {
      return;
    }
    const payload = await response.json();
    const generatedAt = payload.generated_at ?? "";
    const lastRead = localStorage.getItem(STORAGE_KEY) ?? toastElement()?.dataset.generatedAt ?? "";
    const nextCount = Array.isArray(payload.articles) ? payload.articles.length : currentCount();
    const diff = Math.max(0, nextCount - currentCount());
    if (generatedAt && generatedAt !== lastRead && diff > 0) {
      showToast(diff, generatedAt);
    }
  } catch {
    // Polling is best-effort and should never disturb page usage.
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const toast = toastElement();
  if (!toast) {
    return;
  }
  markRead(toast.dataset.generatedAt ?? "");
  toast.querySelector("[data-update-toast-reload]")?.addEventListener("click", () => {
    markRead(toast.dataset.generatedAt ?? "");
    location.reload();
  });
  toast.querySelector("[data-update-toast-close]")?.addEventListener("click", () => {
    markRead(toast.dataset.generatedAt ?? "");
    toast.classList.add("hidden");
  });
  window.setInterval(pollArticles, POLL_INTERVAL_MS);
});
