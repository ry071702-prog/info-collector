const priorityRank = { S: 0, A: 1, B: 2, C: 3 };

function articleTime(card) {
  const value = card.dataset.timestamp ?? "";
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? time : 0;
}

function sortArticles(mode) {
  document.querySelectorAll("[data-article-list]").forEach((list) => {
    const cards = Array.from(list.querySelectorAll("[data-article-card]"));
    cards.sort((a, b) => {
      if (mode === "priority") {
        const diff = (priorityRank[a.dataset.priority ?? "C"] ?? 3) - (priorityRank[b.dataset.priority ?? "C"] ?? 3);
        if (diff !== 0) {
          return diff;
        }
      }
      return articleTime(b) - articleTime(a);
    });
    cards.forEach((card) => list.appendChild(card));
  });
}

function filterArticles(hours) {
  const cutoff = Date.now() - hours * 60 * 60 * 1000;
  document.querySelectorAll("[data-article-card]").forEach((card) => {
    card.style.display = articleTime(card) >= cutoff ? "" : "none";
  });
}

function setPressed(selector, activeValue) {
  document.querySelectorAll(selector).forEach((button) => {
    const value = button.dataset.sortButton ?? button.dataset.rangeButton ?? "";
    button.setAttribute("aria-pressed", String(value === activeValue));
  });
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-sort-button]").forEach((button) => {
    button.addEventListener("click", () => {
      const mode = button.dataset.sortButton ?? "new";
      setPressed("[data-sort-button]", mode);
      sortArticles(mode);
    });
  });

  document.querySelectorAll("[data-range-button]").forEach((button) => {
    button.addEventListener("click", () => {
      const hours = button.dataset.rangeButton ?? "720";
      setPressed("[data-range-button]", hours);
      filterArticles(Number(hours));
    });
  });

  const activeRange = document.querySelector('[data-range-button][aria-pressed="true"]');
  if (activeRange?.dataset.rangeButton) {
    filterArticles(Number(activeRange.dataset.rangeButton));
  }
});
