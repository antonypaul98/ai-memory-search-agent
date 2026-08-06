/** Hash router for workspace views with dispose support. */
const ROUTES = [
  "dashboard",
  "search",
  "ask",
  "timeline",
  "topics",
  "imports",
  "capture",
  "settings",
  "memory",
];

let _generation = 0;
let _bound = false;
let _onChange = null;
let _hashHandler = null;
let _navHandlers = [];

export function currentRoute() {
  const hash = (location.hash || "#dashboard").replace(/^#/, "");
  const [name, ...rest] = hash.split("/");
  const route = ROUTES.includes(name) ? name : "dashboard";
  return { route, param: rest.join("/") || "", generation: _generation };
}

export function navigate(route, param = "") {
  const path = param ? `#${route}/${encodeURIComponent(param)}` : `#${route}`;
  if (location.hash === path) {
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    return;
  }
  location.hash = path;
}

export function routeGeneration() {
  return _generation;
}

/**
 * Bind navigation once. Returns unbind().
 * onChange(route, param, { generation, signal }) — signal aborts when route changes.
 */
export function bindNav(onChange) {
  if (_bound) unbindNav();
  _onChange = onChange;
  _bound = true;

  let routeAbort = null;

  const apply = () => {
    _generation += 1;
    if (routeAbort) routeAbort.abort();
    routeAbort = new AbortController();
    const { route, param } = currentRoute();
    document.querySelectorAll(".nav-link").forEach((el) => {
      const active = el.dataset.route === route;
      el.classList.toggle("active", active);
      if (active) el.setAttribute("aria-current", "page");
      else el.removeAttribute("aria-current");
    });
    document.querySelectorAll(".view").forEach((el) => {
      el.hidden = el.id !== `view-${route}`;
    });
    _onChange(route, param, {
      generation: _generation,
      signal: routeAbort.signal,
    });
  };

  _hashHandler = apply;
  window.addEventListener("hashchange", _hashHandler);

  document.querySelectorAll(".nav-link").forEach((el) => {
    const handler = (e) => {
      e.preventDefault();
      navigate(el.dataset.route);
    };
    el.addEventListener("click", handler);
    _navHandlers.push({ el, handler });
  });

  if (!location.hash) location.hash = "#dashboard";
  else apply();

  return unbindNav;
}

export function unbindNav() {
  if (_hashHandler) window.removeEventListener("hashchange", _hashHandler);
  _navHandlers.forEach(({ el, handler }) => el.removeEventListener("click", handler));
  _navHandlers = [];
  _hashHandler = null;
  _onChange = null;
  _bound = false;
}

export function knownRoutes() {
  return [...ROUTES];
}
