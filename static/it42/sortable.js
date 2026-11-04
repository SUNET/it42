// Drag-and-drop ordering for the CV section lists on the profile page.
//
// Each <ol data-sortable data-reorder-url="..."> holds <li data-id="..."> rows. Rows are
// dragged with Pointer Events (mouse, pen and touch behave the same; HTML5 drag-and-drop
// does nothing on touch screens and differs between browsers). With a mouse a drag can
// start anywhere on the row except on its buttons and links; on a touch screen it starts
// on the grip handle, so the page can still be scrolled by touching the text.
//
// While dragging, the row follows the pointer and the list reorders live. On release the
// new id order is posted as {"order": [ids]} to the reorder URL with the page's CSRF
// token; if that fails the page reloads to show the stored order. The ↑/↓ forms in each
// row remain the keyboard and no-JavaScript path.
(function () {
  "use strict";

  var THRESHOLD = 5; // px of movement before a press becomes a drag (clicks still work)
  var EDGE = 48; // px from the viewport edge where the page auto-scrolls
  var CONTROLS = "a, button, input, select, textarea, label, summary";

  function csrfToken() {
    var input = document.querySelector("input[name=csrfmiddlewaretoken]");
    return input ? input.value : "";
  }

  function rowsOf(list) {
    return Array.prototype.slice.call(list.querySelectorAll(":scope > li[data-id]"));
  }

  function idsOf(list) {
    return rowsOf(list).map(function (row) { return row.dataset.id; });
  }

  function announce(list, text) {
    var card = list.closest("section");
    var out = card ? card.querySelector("[data-announce]") : null;
    if (out) out.textContent = text;
  }

  function refreshArrows(list) {
    var rows = rowsOf(list);
    rows.forEach(function (row, index) {
      var up = row.querySelector('button[aria-label="Move up"]');
      var down = row.querySelector('button[aria-label="Move down"]');
      if (up) up.disabled = index === 0;
      if (down) down.disabled = index === rows.length - 1;
    });
  }

  function post(list) {
    var order = rowsOf(list).map(function (row) { return Number(row.dataset.id); });
    return fetch(list.dataset.reorderUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify({ order: order }),
    }).then(function (response) {
      if (!response.ok) throw new Error("reorder failed: " + response.status);
      return response.json();
    });
  }

  // Move `row` so that it sits where a pointer at `y` (viewport coordinates) points.
  function placeAt(list, row, y) {
    var siblings = rowsOf(list).filter(function (r) { return r !== row; });
    for (var i = 0; i < siblings.length; i++) {
      var rect = siblings[i].getBoundingClientRect();
      if (y < rect.top + rect.height / 2) {
        if (row.nextElementSibling !== siblings[i]) list.insertBefore(row, siblings[i]);
        return;
      }
    }
    if (list.lastElementChild !== row) list.appendChild(row);
  }

  function autoScroll(y) {
    if (y < EDGE) window.scrollBy(0, -Math.ceil((EDGE - y) / 4));
    else if (y > window.innerHeight - EDGE) window.scrollBy(0, Math.ceil((y - window.innerHeight + EDGE) / 4));
  }

  function setup(list) {
    var drag = null; // {row, pointerId, startY, offsetY, before, active}

    function finish(cancelled) {
      if (!drag) return;
      var row = drag.row;
      var state = drag;
      drag = null;
      document.body.classList.remove("cv-sorting");
      row.classList.remove("cv-dragging");
      row.style.transform = "";
      try { list.releasePointerCapture(state.pointerId); } catch (e) { /* already released */ }
      if (!state.active) return;
      var after = idsOf(list).join(",");
      if (cancelled || after === state.before) {
        if (cancelled && after !== state.before) window.location.reload();
        return;
      }
      refreshArrows(list);
      var position = rowsOf(list).indexOf(row) + 1;
      announce(list, "Moved to position " + position + " of " + rowsOf(list).length + ".");
      post(list).catch(function () { window.location.reload(); });
    }

    list.addEventListener("pointerdown", function (event) {
      if (drag || event.button !== 0) return;
      var row = event.target.closest("li[data-id]");
      if (!row || row.parentNode !== list) return;
      if (event.target.closest(CONTROLS)) return; // let buttons and links work
      var onGrip = Boolean(event.target.closest(".cv-grip"));
      if (event.pointerType !== "mouse" && !onGrip) return; // touch scrolls unless on the grip
      drag = {
        row: row,
        pointerId: event.pointerId,
        startY: event.clientY,
        lastY: event.clientY,
        before: idsOf(list).join(","),
        active: false,
      };
      // Capture on the list, not the row: moving the row in the DOM would release a
      // capture held by the row and end the drag after its first move.
      list.setPointerCapture(event.pointerId);
      if (onGrip) event.preventDefault(); // no text selection / focus change from the grip
    });

    list.addEventListener("pointermove", function (event) {
      if (!drag || event.pointerId !== drag.pointerId) return;
      drag.lastY = event.clientY;
      if (!drag.active) {
        if (Math.abs(event.clientY - drag.startY) < THRESHOLD) return;
        drag.active = true;
        drag.row.classList.add("cv-dragging");
        document.body.classList.add("cv-sorting");
      }
      event.preventDefault();
      placeAt(list, drag.row, event.clientY);
      var rect = drag.row.getBoundingClientRect();
      var shift = event.clientY - (rect.top + rect.height / 2);
      drag.row.style.transform = "translateY(" + Math.round(shift) + "px)";
      autoScroll(event.clientY);
    });

    list.addEventListener("pointerup", function (event) {
      if (drag && event.pointerId === drag.pointerId) finish(false);
    });
    list.addEventListener("pointercancel", function (event) {
      if (drag && event.pointerId === drag.pointerId) finish(true);
    });
    list.addEventListener("lostpointercapture", function (event) {
      if (drag && event.pointerId === drag.pointerId) finish(false);
    });
    // A drag that is in progress should not also start the browser's own drag of a link.
    list.addEventListener("dragstart", function (event) {
      if (drag) event.preventDefault();
    });
  }

  document.querySelectorAll("[data-sortable]").forEach(setup);
})();
