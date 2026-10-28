"use strict";
// Mavzuni sahifa chizilishidan oldin o'rnatadi (miltillashning oldini oladi).
(() => {
  let t = null;
  try { t = localStorage.getItem("termchat_theme"); } catch (_) {}
  if (t !== "dark" && t !== "light") t = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.dataset.theme = t;
})();
