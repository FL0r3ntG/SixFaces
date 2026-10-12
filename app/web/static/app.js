// Tooltips for [data-tip] (hover + keyboard focus) and the light/dark toggle.
(() => {
  const tip = document.getElementById("tooltip");
  let current = null;

  function show(el, x, y) {
    tip.innerHTML = el.dataset.tip;
    tip.hidden = false;
    const r = tip.getBoundingClientRect();
    let left = x + 14, top = y + 14;
    if (left + r.width > innerWidth - 8) left = x - r.width - 14;
    if (top + r.height > innerHeight - 8) top = y - r.height - 14;
    tip.style.left = Math.max(8, left) + "px";
    tip.style.top = Math.max(8, top) + "px";
  }
  function hide() { tip.hidden = true; current = null; }

  document.addEventListener("pointermove", (e) => {
    const el = e.target.closest("[data-tip]");
    if (!el) { if (current) hide(); return; }
    current = el;
    show(el, e.clientX, e.clientY);
  });
  document.addEventListener("focusin", (e) => {
    const el = e.target.closest("[data-tip]");
    if (!el) return;
    const r = el.getBoundingClientRect();
    show(el, r.left, r.bottom);
  });
  document.addEventListener("focusout", hide);
  document.addEventListener("scroll", hide, { passive: true });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });

  const btn = document.getElementById("theme-toggle");
  btn?.addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.dataset.theme
      ? root.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
  });

  // phones: the search field opens from a button in the header
  const searchBtn = document.getElementById("search-toggle");
  searchBtn?.addEventListener("click", () => {
    const open = document.body.classList.toggle("search-open");
    searchBtn.setAttribute("aria-expanded", String(open));
    if (open) document.querySelector("#search-form input")?.focus();
  });

  // sujet page: one button opens / closes every development's list of articles
  const toggle = document.getElementById("toggle-articles");
  toggle?.addEventListener("click", () => {
    const open = toggle.getAttribute("aria-pressed") !== "true";
    document.querySelectorAll(".tl-articles").forEach((d) => { d.open = open; });
    toggle.setAttribute("aria-pressed", String(open));
    toggle.textContent = open ? "Masquer les articles" : "Afficher tous les articles";
  });

  // keep the front page fresh while it stays open
  if (location.pathname === "/") setTimeout(() => location.reload(), 5 * 60 * 1000);
})();
