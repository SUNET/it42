// Tabs for [data-tabs] containers: links in [role=tablist] point at #panel ids. Without
// JavaScript every panel stays visible and the links scroll to them.
(function () {
  "use strict";
  document.querySelectorAll("[data-tabs]").forEach(function (root) {
    var tabs = Array.prototype.slice.call(root.querySelectorAll('[role="tablist"] a[href^="#"]'));
    var panels = tabs.map(function (tab) { return root.querySelector(tab.getAttribute("href")); });
    if (panels.some(function (p) { return !p; })) return;
    root.classList.add("js-tabs");

    function show(index, focus) {
      tabs.forEach(function (tab, i) {
        var active = i === index;
        tab.setAttribute("aria-selected", active ? "true" : "false");
        tab.tabIndex = active ? 0 : -1;
        tab.setAttribute("aria-controls", panels[i].id);
        panels[i].hidden = !active;
      });
      if (focus) tabs[index].focus();
    }

    tabs.forEach(function (tab, i) {
      tab.addEventListener("click", function (event) {
        event.preventDefault();
        show(i, false);
        history.replaceState(null, "", tab.getAttribute("href"));
      });
      tab.addEventListener("keydown", function (event) {
        var next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[event.key];
        if (next === undefined) return;
        event.preventDefault();
        show((next + tabs.length) % tabs.length, true);
      });
    });

    function fromHash() {
      var index = tabs.findIndex(function (tab) { return tab.getAttribute("href") === location.hash; });
      show(index < 0 ? 0 : index, false);
    }
    // In-page links elsewhere (e.g. "Answer 1 question" → #messages) switch tabs too.
    window.addEventListener("hashchange", fromHash);
    fromHash();
  });
})();
