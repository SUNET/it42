// Static site behaviour (Static Site Components, Static Site MD templates).
(function () {
  "use strict";

  // Section reveal: [data-reveal] sections below the fold fade up once when 20% of them
  // scrolls into view. Sections already on screen, browsers without IntersectionObserver
  // and reduced-motion users get them as they are.
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if ("IntersectionObserver" in window && !reduced) {
    var reveal = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.remove("it-reveal-hidden");
        reveal.unobserve(entry.target);
      });
    }, { threshold: 0.2 });
    document.querySelectorAll("[data-reveal]").forEach(function (section) {
      if (section.getBoundingClientRect().top < window.innerHeight) return;
      section.classList.add("it-reveal", "it-reveal-hidden");
      reveal.observe(section);
    });
  }

  // "On this page": mark the link of the last heading scrolled past (or the first one).
  var links = Array.prototype.slice.call(document.querySelectorAll(".it-toc a[href^='#']"));
  var headings = links.map(function (a) { return document.getElementById(a.getAttribute("href").slice(1)); });
  if (!links.length || headings.some(function (h) { return !h; })) return;
  function mark() {
    var current = 0;
    headings.forEach(function (h, i) { if (h.getBoundingClientRect().top < 120) current = i; });
    links.forEach(function (a, i) {
      if (i === current) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current");
    });
  }
  window.addEventListener("scroll", mark, { passive: true });
  mark();
})();
