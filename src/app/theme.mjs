// Theme system: one preference ("dark" | "light" | "system"), stored in this
// browser, applied as <html data-theme="dark|light">. Every colour in the
// terminal is a CSS token (app.css), so switching is instant and needs no
// reload. index.html applies the stored theme before first paint; this module
// keeps it in sync, follows the OS when the preference is "system", and tells
// pages (charts) to redraw via the "td:theme" event.
export const THEMES = ["dark", "light", "system"];
const KEY = "td_theme";
const DEFAULT = "dark";            // TRADEDEN's identity; light is opt-in (or via "system")
const media = typeof matchMedia === "function" ? matchMedia("(prefers-color-scheme: light)") : null;

export function preference() {
  try { const v = localStorage.getItem(KEY); return THEMES.includes(v) ? v : DEFAULT; } catch { return DEFAULT; }
}
export const resolve = (pref = preference()) => pref === "system" ? (media?.matches ? "light" : "dark") : pref;
export const current = () => document.documentElement.dataset.theme === "light" ? "light" : "dark";

function paint(theme, animate) {
  const root = document.documentElement;
  if (root.dataset.theme === theme) return false;
  if (animate && root.dataset.motion !== "off") {
    root.classList.add("theme-anim");
    clearTimeout(paint.t);
    paint.t = setTimeout(() => root.classList.remove("theme-anim"), 320);
  }
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = theme === "light" ? "#eef1f6" : "#05070b";
  window.dispatchEvent(new CustomEvent("td:theme", { detail: { theme } }));
  return true;
}

export function setPreference(pref, { animate = true } = {}) {
  if (!THEMES.includes(pref)) return;
  try { localStorage.setItem(KEY, pref); } catch {}
  paint(resolve(pref), animate);
}
export const toggle = () => setPreference(current() === "light" ? "dark" : "light");

export function initTheme() {
  paint(resolve(), false);
  media?.addEventListener?.("change", () => { if (preference() === "system") paint(resolve("system"), true); });
  // Another tab changed the preference.
  window.addEventListener("storage", e => { if (e.key === KEY) paint(resolve(), true); });
}
