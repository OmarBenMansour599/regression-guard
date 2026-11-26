// Applies the saved theme before the first paint (no light flash in dark mode).
// A separate file because the Content-Security-Policy forbids inline scripts.
(function () {
  var theme = "system";
  try {
    theme = localStorage.getItem("regguard-theme") || "system";
  } catch (e) {
    /* storage blocked: follow the system */
  }
  var dark =
    theme === "dark" ||
    (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
})();
