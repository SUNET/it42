// Keep panel controls outside the panels so they remain available when collapsed.
(function () {
  "use strict";
  document.querySelectorAll(".it-app").forEach(function (app) {
    var bar = app.querySelector(".it-topbar");
    if (!bar) return;
    var smallScreen = window.matchMedia("(max-width: 1399.98px)");
    [
      { selector: ".it-sidebar", name: "menu", side: "left", collapsed: false },
      { selector: ".it-panel", name: "side panel", side: "right", collapsed: smallScreen.matches }
    ].forEach(function (item) {
      var panel = app.querySelector(":scope > " + item.selector);
      if (!panel) return;
      var key = "it42-panel-" + item.side;
      var saved;
      try { saved = localStorage.getItem(key); } catch (_) { /* Storage can be disabled. */ }
      var collapsed = saved === "hidden" || (saved !== "shown" && item.collapsed);
      panel.id = panel.id || "it-app-" + item.side + "-panel";
      var button = document.createElement("button");
      button.type = "button";
      button.className = "it-panel-toggle it-panel-toggle-" + item.side;
      button.setAttribute("aria-controls", panel.id);
      var icon = document.createElement("span");
      icon.className = "it-panel-toggle-icon";
      icon.setAttribute("aria-hidden", "true");
      button.append(icon);
      function render() {
        panel.hidden = collapsed;
        button.setAttribute("aria-expanded", String(!collapsed));
        var label = (collapsed ? "Show " : "Hide ") + item.name;
        button.setAttribute("aria-label", label);
        button.title = label;
      }
      button.addEventListener("click", function () {
        collapsed = !collapsed;
        render();
        try { localStorage.setItem(key, collapsed ? "hidden" : "shown"); } catch (_) { /* Optional preference. */ }
      });
      if (item.side === "left") bar.prepend(button);
      else bar.append(button);
      render();
    });
    app.classList.add("it-panels-ready");
  });
})();
