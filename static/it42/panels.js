// The same links and forms serve the expanded menu and its compact desktop rail.
(function () {
  "use strict";
  const narrow = window.matchMedia("(max-width: 991.98px)");
  const compact = window.matchMedia("(max-width: 1399.98px)");

  document.querySelectorAll(".it-app").forEach(function (app) {
    const bar = app.querySelector(".it-topbar");
    app.querySelectorAll(":scope > .it-sidebar, :scope > .it-panel").forEach(function (panel) {
      const button = panel.querySelector(".it-panel-toggle");
      const right = panel.classList.contains("it-panel");
      const side = right ? "right" : "left";
      const name = right ? "side panel" : "menu";
      const key = "it42-panel-" + side;
      let preference;
      try { preference = localStorage.getItem(key); } catch (_) { /* Storage is optional. */ }

      panel.id = "it-app-" + side + "-panel";
      button.setAttribute("aria-controls", panel.id);
      panel.querySelectorAll(".it-sidebar-item").forEach(function (link) {
        link.title = link.textContent.trim();
      });

      function render() {
        const collapsed = preference ? preference === "hidden" : right && compact.matches;
        if (right) {
          if (narrow.matches && button.parentNode !== bar) bar.append(button);
          if (!narrow.matches && button.parentNode !== panel) panel.prepend(button);
        }
        panel.classList.toggle("is-collapsed", collapsed);
        button.setAttribute("aria-expanded", String(!collapsed));
        button.title = (collapsed ? "Expand " : "Collapse ") + name;
        button.setAttribute("aria-label", button.title);
        button.hidden = false;
      }

      function setCollapsed(collapsed) {
        preference = collapsed ? "hidden" : "shown";
        render();
        try { localStorage.setItem(key, preference); } catch (_) { /* Storage is optional. */ }
      }

      button.addEventListener("click", function () {
        const collapse = !panel.classList.contains("is-collapsed");
        setCollapsed(collapse);
        if (right && narrow.matches && !collapse) panel.querySelector("h2").focus();
      });
      panel.querySelectorAll(".it-panel-shortcuts a").forEach(function (shortcut) {
        shortcut.addEventListener("click", function (event) {
          event.preventDefault();
          setCollapsed(false);
          panel.querySelector(shortcut.hash).focus();
        });
      });
      if (right) {
        narrow.addEventListener("change", render);
        compact.addEventListener("change", render);
      }
      render();
    });
  });
})();
