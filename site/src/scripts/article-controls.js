const priorityRank = { S: 0, A: 1, B: 2, C: 3 };
const state = {
  sortMode: "new",
  rangeHours: null,
  searchText: "",
};

function articleTime(card) {
  const value = card.dataset.timestamp ?? "";
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? time : 0;
}

function compareArticles(a, b) {
  if (state.sortMode === "priority") {
    const diff = (priorityRank[a.dataset.priority ?? "C"] ?? 3) - (priorityRank[b.dataset.priority ?? "C"] ?? 3);
    if (diff !== 0) {
      return diff;
    }
  }
  return articleTime(b) - articleTime(a);
}

function matchesFilters(card, cutoff) {
  if (cutoff !== null && articleTime(card) < cutoff) {
    return false;
  }
  if (state.searchText) {
    const searchBlob = card.dataset.searchBlob ?? "";
    return searchBlob.includes(state.searchText);
  }
  return true;
}

function emptyMessageFor(list) {
  const next = list.nextElementSibling;
  if (next?.hasAttribute("data-article-empty-search")) {
    return next;
  }

  const message = document.createElement("p");
  message.textContent = "該当する記事がありません";
  message.hidden = true;
  message.dataset.articleEmptySearch = "";
  message.className =
    "rounded-lg border border-dashed border-slate-300 p-6 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400";
  list.insertAdjacentElement("afterend", message);
  return message;
}

function updateSearchCount(count) {
  document.querySelectorAll("[data-search-count]").forEach((element) => {
    element.textContent = `${count} 件`;
  });
}

function applyArticleControls() {
  const cutoff = state.rangeHours === null ? null : Date.now() - state.rangeHours * 60 * 60 * 1000;
  let visibleCount = 0;

  document.querySelectorAll("[data-article-list]").forEach((list) => {
    const cards = Array.from(list.querySelectorAll("[data-article-card]"));
    cards.sort(compareArticles);

    let listVisibleCount = 0;
    cards.forEach((card) => {
      const isVisible = matchesFilters(card, cutoff);
      card.style.display = isVisible ? "" : "none";
      if (isVisible) {
        listVisibleCount += 1;
      }
    });

    visibleCount += listVisibleCount;
    cards.forEach((card) => list.appendChild(card));

    const message = emptyMessageFor(list);
    message.hidden = listVisibleCount > 0;
  });

  updateSearchCount(visibleCount);
}

function setPressed(selector, activeValue) {
  document.querySelectorAll(selector).forEach((button) => {
    const value = button.dataset.sortButton ?? button.dataset.rangeButton ?? "";
    button.setAttribute("aria-pressed", String(value === activeValue));
  });
}

function debounce(callback, delay) {
  let timeoutId;
  return (...args) => {
    window.clearTimeout(timeoutId);
    timeoutId = window.setTimeout(() => callback(...args), delay);
  };
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-sort-button]").forEach((button) => {
    button.addEventListener("click", () => {
      state.sortMode = button.dataset.sortButton ?? "new";
      setPressed("[data-sort-button]", state.sortMode);
      applyArticleControls();
    });
  });

  document.querySelectorAll("[data-range-button]").forEach((button) => {
    button.addEventListener("click", () => {
      const hours = button.dataset.rangeButton ?? "720";
      setPressed("[data-range-button]", hours);
      state.rangeHours = Number(hours);
      applyArticleControls();
    });
  });

  const debouncedSearch = debounce((value) => {
    state.searchText = value.toLowerCase();
    applyArticleControls();
  }, 150);

  document.querySelectorAll("[data-search-input]").forEach((searchInput) => {
    searchInput.addEventListener("input", () => {
      debouncedSearch(searchInput.value.trim());
    });
  });

  document.querySelectorAll("[data-search-tag]").forEach((tagButton) => {
    tagButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const tag = tagButton.dataset.searchTag ?? "";
      document.querySelectorAll("[data-search-input]").forEach((searchInput) => {
        searchInput.value = tag;
      });
      state.searchText = tag.toLowerCase();
      applyArticleControls();
    });
  });

  const activeSort = document.querySelector('[data-sort-button][aria-pressed="true"]');
  if (activeSort?.dataset.sortButton) {
    state.sortMode = activeSort.dataset.sortButton;
  }

  const activeRange = document.querySelector('[data-range-button][aria-pressed="true"]');
  if (activeRange?.dataset.rangeButton) {
    state.rangeHours = Number(activeRange.dataset.rangeButton);
  }

  applyArticleControls();
});
