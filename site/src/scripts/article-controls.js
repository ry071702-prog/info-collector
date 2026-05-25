import { favoriteIds, isFavorite, isRead, markRead, resetReads, toggleFavorite } from "../lib/clientStorage.ts";

const priorityRank = { S: 0, A: 1, B: 2, C: 3 };
const periodHours = { "24h": 24, "7d": 168, "30d": 720 };
const pageSize = 20;
const defaultState = {
  sortMode: "new",
  period: "all",
  searchText: "",
  tags: [],
  sources: [],
};
let state = { ...defaultState };
let infiniteObserver = null;

function articleTime(card) {
  const value = card.dataset.timestamp ?? "";
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? time : 0;
}

function articleTags(card) {
  try {
    const tags = JSON.parse(card.dataset.tags ?? "[]");
    return Array.isArray(tags) ? tags.map((tag) => String(tag).toLowerCase()) : [];
  } catch {
    return [];
  }
}

function compareArticles(a, b) {
  if (state.sortMode === "importance") {
    const diff = (priorityRank[a.dataset.priority ?? "C"] ?? 3) - (priorityRank[b.dataset.priority ?? "C"] ?? 3);
    if (diff !== 0) {
      return diff;
    }
  }
  return articleTime(b) - articleTime(a);
}

function cutoffTime() {
  if (state.period === "all") {
    return null;
  }
  const hours = periodHours[state.period];
  return hours ? Date.now() - hours * 60 * 60 * 1000 : null;
}

function matchesFilters(card, cutoff) {
  if (card.closest("[data-favorites-list]") && !isFavorite(card.dataset.articleId ?? "")) {
    return false;
  }
  if (cutoff !== null && articleTime(card) < cutoff) {
    return false;
  }
  if (state.searchText) {
    const searchBlob = card.dataset.searchBlob ?? "";
    if (!searchBlob.includes(state.searchText.toLowerCase())) {
      return false;
    }
  }
  if (state.tags.length > 0) {
    const tags = articleTags(card);
    if (!state.tags.every((tag) => tags.includes(tag.toLowerCase()))) {
      return false;
    }
  }
  if (state.sources.length > 0 && !state.sources.includes((card.dataset.source ?? "").toLowerCase())) {
    return false;
  }
  return true;
}

function siblingFor(list, selector, attribute) {
  let next = list.nextElementSibling;
  while (next?.hasAttribute("data-infinite-status") || next?.hasAttribute("data-infinite-sentinel")) {
    next = next.nextElementSibling;
  }
  if (next?.matches(selector)) {
    return next;
  }
  const element = document.createElement("p");
  element.dataset[attribute] = "";
  list.insertAdjacentElement("afterend", element);
  return element;
}

function emptyMessageFor(list) {
  const message = siblingFor(list, "[data-article-empty-search]", "articleEmptySearch");
  message.textContent = "該当する記事がありません";
  message.hidden = true;
  message.dataset.articleEmptySearch = "";
  message.className =
    "rounded-lg border border-dashed border-slate-300 p-6 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400";
  return message;
}

function statusFor(list) {
  const next = list.nextElementSibling;
  if (next?.hasAttribute("data-infinite-status")) {
    return next;
  }

  const status = document.createElement("p");
  status.dataset.infiniteStatus = "";
  status.className = "mt-5 text-center text-sm text-slate-500 dark:text-slate-400";
  list.insertAdjacentElement("afterend", status);
  return status;
}

function sentinelFor(status) {
  const next = status.nextElementSibling;
  if (next?.hasAttribute("data-infinite-sentinel")) {
    return next;
  }

  const sentinel = document.createElement("div");
  sentinel.dataset.infiniteSentinel = "";
  sentinel.className = "h-8";
  status.insertAdjacentElement("afterend", sentinel);
  return sentinel;
}

function updateSearchCount(count) {
  document.querySelectorAll("[data-search-count]").forEach((element) => {
    element.textContent = `${count} 件`;
  });
}

function selectedCount(selector, count) {
  document.querySelectorAll(selector).forEach((element) => {
    element.textContent = String(count);
  });
}

function setFieldValues() {
  document.querySelectorAll("[data-sort-select]").forEach((select) => {
    select.value = state.sortMode;
  });
  document.querySelectorAll("[data-period-select]").forEach((select) => {
    select.value = state.period;
  });
  document.querySelectorAll("[data-search-input]").forEach((input) => {
    input.value = state.searchText;
  });
  document.querySelectorAll("[data-filter-checkbox]").forEach((checkbox) => {
    const group = checkbox.dataset.filterCheckbox;
    const value = (checkbox.value ?? "").toLowerCase();
    checkbox.checked = group === "tag" ? state.tags.includes(value) : state.sources.includes(value);
  });
  selectedCount("[data-tag-count]", state.tags.length);
  selectedCount("[data-source-count]", state.sources.length);
}

function visibleLimitFor(list) {
  const current = Number(list.dataset.visibleLimit);
  if (Number.isFinite(current) && current > 0) {
    return current;
  }
  list.dataset.visibleLimit = String(pageSize);
  return pageSize;
}

function resetVisibleLimits() {
  document.querySelectorAll("[data-article-list]").forEach((list) => {
    list.dataset.visibleLimit = String(pageSize);
  });
}

function updateCardStorageState(card) {
  const articleId = card.dataset.articleId ?? "";
  const read = isRead(articleId);
  card.classList.toggle("opacity-60", read);
  card.querySelector("[data-read-label]")?.classList.toggle("hidden", !read);

  const favoriteButton = card.querySelector("[data-favorite-toggle]");
  if (favoriteButton) {
    const favorite = isFavorite(articleId);
    favoriteButton.setAttribute("aria-pressed", String(favorite));
    favoriteButton.setAttribute("aria-label", favorite ? "お気に入りから削除" : "お気に入りに追加");
    favoriteButton.textContent = favorite ? "★" : "☆";
    favoriteButton.classList.toggle("text-yellow-500", favorite);
    favoriteButton.classList.toggle("text-slate-500", !favorite);
    favoriteButton.classList.toggle("dark:text-yellow-300", favorite);
    favoriteButton.classList.toggle("dark:text-slate-400", !favorite);
  }
}

function applyStorageState() {
  document.querySelectorAll("[data-article-card]").forEach(updateCardStorageState);

  document.querySelectorAll("[data-favorites-empty]").forEach((element) => {
    element.hidden = favoriteIds().length > 0;
  });
}

function applyArticleControls() {
  document.documentElement.classList.add("articles-ready");
  const cutoff = cutoffTime();
  let visibleCount = 0;

  document.querySelectorAll("[data-article-list]").forEach((list) => {
    const cards = Array.from(list.querySelectorAll("[data-article-card]"));
    cards.sort(compareArticles);

    const limit = visibleLimitFor(list);
    const matchingCards = [];
    cards.forEach((card) => {
      const isVisible = matchesFilters(card, cutoff);
      if (isVisible) {
        matchingCards.push(card);
      }
    });

    visibleCount += matchingCards.length;
    cards.forEach((card) => list.appendChild(card));
    cards.forEach((card) => {
      const matchIndex = matchingCards.indexOf(card);
      card.style.display = matchIndex >= 0 && matchIndex < limit ? "" : "none";
    });

    const message = emptyMessageFor(list);
    const favoriteListWithoutFavorites = list.hasAttribute("data-favorites-list") && favoriteIds().length === 0;
    message.hidden = matchingCards.length > 0 || favoriteListWithoutFavorites;

    const status = statusFor(list);
    const sentinel = sentinelFor(status);
    if (matchingCards.length === 0) {
      status.hidden = true;
      sentinel.hidden = true;
    } else if (limit >= matchingCards.length) {
      status.hidden = false;
      status.textContent = "すべて読み込み完了";
      sentinel.hidden = true;
    } else {
      status.hidden = false;
      status.textContent = `${Math.min(limit, matchingCards.length)} / ${matchingCards.length} 件を表示中`;
      sentinel.hidden = false;
    }
  });

  applyStorageState();
  updateSearchCount(visibleCount);
  setFieldValues();
  document.documentElement.classList.add("articles-ready");
  observeInfiniteSentinels();
}

function valuesFromParam(params, key) {
  const value = params.get(key);
  return value
    ? value
        .split(",")
        .map((item) => item.trim().toLowerCase())
        .filter(Boolean)
    : [];
}

function stateFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const sortMode = params.get("sort") === "importance" ? "importance" : "new";
  const period = ["24h", "7d", "30d"].includes(params.get("period") ?? "") ? params.get("period") : "all";
  return {
    sortMode,
    period,
    searchText: params.get("q")?.trim() ?? "",
    tags: valuesFromParam(params, "tag"),
    sources: valuesFromParam(params, "source"),
  };
}

function writeUrl(mode = "push") {
  const params = new URLSearchParams(window.location.search);
  if (state.searchText) params.set("q", state.searchText);
  else params.delete("q");
  if (state.tags.length > 0) params.set("tag", state.tags.join(","));
  else params.delete("tag");
  if (state.sources.length > 0) params.set("source", state.sources.join(","));
  else params.delete("source");
  if (state.period !== "all") params.set("period", state.period);
  else params.delete("period");
  if (state.sortMode !== "new") params.set("sort", state.sortMode);
  else params.delete("sort");

  const query = params.toString();
  const nextUrl = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
  window.history[mode === "replace" ? "replaceState" : "pushState"]({ ...state }, "", nextUrl);
}

function uniqueOptions() {
  const tags = new Map();
  const sources = new Map();

  document.querySelectorAll("[data-article-list] [data-article-card]").forEach((card) => {
    try {
      const parsedTags = JSON.parse(card.dataset.tags ?? "[]");
      if (Array.isArray(parsedTags)) {
        parsedTags.forEach((tag) => {
          const label = String(tag).trim();
          if (label) tags.set(label.toLowerCase(), label);
        });
      }
    } catch {
      // Ignore malformed data attributes.
    }

    const source = (card.dataset.source ?? "").toLowerCase();
    const sourceLabel = card.dataset.sourceLabel ?? source;
    if (source) {
      sources.set(source, sourceLabel);
    }
  });

  return {
    tags: [...tags.entries()].sort((a, b) => a[1].localeCompare(b[1], "ja")),
    sources: [...sources.entries()].sort((a, b) => a[1].localeCompare(b[1], "ja")),
  };
}

function renderCheckboxOptions(containerSelector, options, group, emptyText) {
  document.querySelectorAll(containerSelector).forEach((container) => {
    container.replaceChildren();
    if (options.length === 0) {
      const empty = document.createElement("p");
      empty.className = "px-2 py-1.5 text-sm text-slate-500 dark:text-slate-400";
      empty.textContent = emptyText;
      container.appendChild(empty);
      return;
    }

    options.forEach(([value, label]) => {
      const wrapper = document.createElement("label");
      wrapper.className = "article-filter-option";

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = value;
      checkbox.dataset.filterCheckbox = group;
      checkbox.className = "h-4 w-4 rounded border-slate-300 text-slate-950 focus:ring-slate-400 dark:border-slate-700 dark:bg-slate-900";
      checkbox.addEventListener("change", () => {
        const key = group === "tag" ? "tags" : "sources";
        const selected = new Set(state[key]);
        if (checkbox.checked) selected.add(value);
        else selected.delete(value);
        state = { ...state, [key]: [...selected] };
        resetVisibleLimits();
        writeUrl();
        applyArticleControls();
      });

      const text = document.createElement("span");
      text.textContent = label;

      wrapper.append(checkbox, text);
      container.appendChild(wrapper);
    });
  });
}

function buildFilterOptions() {
  const options = uniqueOptions();
  renderCheckboxOptions("[data-tag-options]", options.tags, "tag", "タグ候補がありません");
  renderCheckboxOptions("[data-source-options]", options.sources, "source", "Source 候補がありません");
}

function observeInfiniteSentinels() {
  infiniteObserver?.disconnect();
  infiniteObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) {
          return;
        }
        const sentinel = entry.target;
        const status = sentinel.previousElementSibling;
        const list = status?.previousElementSibling;
        if (!list?.hasAttribute("data-article-list")) {
          return;
        }
        const limit = visibleLimitFor(list);
        list.dataset.visibleLimit = String(limit + pageSize);
        applyArticleControls();
      });
    },
    { rootMargin: "320px 0px" },
  );

  document.querySelectorAll("[data-infinite-sentinel]:not([hidden])").forEach((sentinel) => {
    infiniteObserver?.observe(sentinel);
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
  buildFilterOptions();
  state = stateFromUrl();
  resetVisibleLimits();

  document.querySelectorAll("[data-article-link]").forEach((link) => {
    link.addEventListener("click", () => {
      const card = link.closest("[data-article-card]");
      const articleId = card?.dataset.articleId ?? "";
      markRead(articleId);
      if (card) updateCardStorageState(card);
    });
  });

  document.querySelectorAll("[data-favorite-toggle]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const card = button.closest("[data-article-card]");
      const articleId = card?.dataset.articleId ?? "";
      toggleFavorite(articleId);
      if (card) updateCardStorageState(card);
      applyArticleControls();
    });
  });

  document.querySelectorAll("[data-reset-reads]").forEach((button) => {
    button.addEventListener("click", () => {
      resetReads();
      applyStorageState();
    });
  });

  document.querySelectorAll("[data-sort-select]").forEach((select) => {
    select.addEventListener("change", () => {
      state = { ...state, sortMode: select.value === "importance" ? "importance" : "new" };
      resetVisibleLimits();
      writeUrl();
      applyArticleControls();
    });
  });

  document.querySelectorAll("[data-period-select]").forEach((select) => {
    select.addEventListener("change", () => {
      state = { ...state, period: ["24h", "7d", "30d"].includes(select.value) ? select.value : "all" };
      resetVisibleLimits();
      writeUrl();
      applyArticleControls();
    });
  });

  const debouncedSearch = debounce((value) => {
    state = { ...state, searchText: value.trim() };
    resetVisibleLimits();
    writeUrl("replace");
    applyArticleControls();
  }, 150);

  document.querySelectorAll("[data-search-input]").forEach((searchInput) => {
    searchInput.addEventListener("input", () => {
      debouncedSearch(searchInput.value);
    });
  });

  document.querySelectorAll("[data-search-tag]").forEach((tagButton) => {
    tagButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const tag = (tagButton.dataset.searchTag ?? "").toLowerCase();
      if (!tag) return;
      state = { ...state, tags: [...new Set([...state.tags, tag])] };
      resetVisibleLimits();
      writeUrl();
      applyArticleControls();
    });
  });

  document.querySelectorAll("[data-clear-filters]").forEach((button) => {
    button.addEventListener("click", () => {
      state = { ...defaultState };
      resetVisibleLimits();
      writeUrl();
      applyArticleControls();
    });
  });

  window.addEventListener("popstate", () => {
    state = stateFromUrl();
    resetVisibleLimits();
    applyArticleControls();
  });

  applyArticleControls();
});
