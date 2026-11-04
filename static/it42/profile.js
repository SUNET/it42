// Profile page: the server-rendered dialogs and the Academic CV table.
// - A dialog (.it-overlay [role=dialog]) gets the focus; Escape follows its data-close
//   link. Tab stays inside it because the page behind is inert.
// - The CV table's search, section chips and sort filter the rows in place; without
//   JavaScript they are GET parameters handled by the server.
(function () {
  "use strict";

  var dialog = document.querySelector(".it-overlay [role=dialog]");
  if (dialog) {
    var first = dialog.querySelector(".is-invalid, input:not([type=hidden]), select, textarea");
    (first || dialog).focus();
    if (location.hash && dialog.querySelector(location.hash)) {
      dialog.querySelector(location.hash).scrollIntoView({ block: "center" });
    }
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && dialog.dataset.close) location.href = dialog.dataset.close;
    });
  }

  var form = document.querySelector("[data-cv-filter]");
  if (!form) return;
  var body = document.querySelector(".it-cv-table tbody");
  var rows = Array.prototype.slice.call(body.rows);
  var summary = document.querySelector("[data-cv-summary]");
  var search = form.elements.q;

  function order(mode) {
    var sorted = rows.slice();
    if (mode === "oldest") {
      sorted.sort(function (a, b) { return (a.dataset.date || "9999").localeCompare(b.dataset.date || "9999"); });
    } else if (mode === "section") {
      sorted.sort(function (a, b) { return a.dataset.short.localeCompare(b.dataset.short) || a.dataset.order - b.dataset.order; });
    } else {
      sorted.sort(function (a, b) { return a.dataset.order - b.dataset.order; });
    }
    sorted.forEach(function (row) { body.appendChild(row); });
  }

  function update() {
    var query = search.value.trim().toLocaleLowerCase();
    var section = form.elements.section.value;
    var shown = 0;
    rows.forEach(function (row) {
      var match = (!section || row.dataset.section === section) && (!query || row.dataset.search.indexOf(query) !== -1);
      row.hidden = !match;
      if (match) shown += 1;
    });
    order(form.elements.sort.value);
    if (query) {
      summary.textContent = shown + (shown === 1 ? " result" : " results") + " for “" + search.value.trim() + "” in titles and details.";
    } else if (section) {
      summary.textContent = "Showing " + shown + " of " + rows.length + " entries.";
    } else {
      summary.textContent = "Showing all " + rows.length + " entries.";
    }
  }

  form.addEventListener("submit", function (event) { event.preventDefault(); update(); });
  form.addEventListener("input", update);
  form.addEventListener("change", update);
  update();
})();
