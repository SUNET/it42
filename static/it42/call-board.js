// Keyboard and touch users submit the same archive form through the card menu.
(function () {
  "use strict";
  const board = document.querySelector("[data-call-board]");
  if (!board) return;
  let dragged;
  document.addEventListener("dragstart", event => {
    const card = event.target.closest("[data-archive-card]");
    if (!card || event.target.closest("details, input, textarea")) return;
    dragged = card;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", card.querySelector("h3").textContent);
  });
  function resetDrag() {
    dragged = null;
    document.querySelectorAll(".cb-archive.is-over").forEach(zone => zone.classList.remove("is-over"));
  }
  document.addEventListener("dragend", resetDrag);
  document.querySelectorAll("[data-archive-drop]").forEach(zone => {
    zone.addEventListener("dragover", event => {
      if (!dragged) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      zone.classList.add("is-over");
    });
    zone.addEventListener("dragleave", event => {
      if (!zone.contains(event.relatedTarget)) zone.classList.remove("is-over");
    });
    zone.addEventListener("drop", event => {
      if (!dragged) return;
      event.preventDefault();
      const button = dragged.querySelector("[data-archive-button]");
      resetDrag();
      button.form.requestSubmit(button);
    });
  });

  // A panel shared between calls can appear in more than one group.
  const checks = Array.from(document.querySelectorAll(".cb-check"));
  const selectionCount = board.querySelector("[data-selection-count]");
  checks.forEach(check => check.addEventListener("change", () => {
    checks.filter(other => other.value === check.value).forEach(other => { other.checked = check.checked; });
    const count = new Set(checks.filter(other => other.checked).map(other => other.value)).size;
    selectionCount.textContent = count ? count + " selected" : "Select cards";
  }));
  // Dismiss an open action/filter menu on Escape or when moving to another control.
  document.addEventListener("click", event => {
    document.querySelectorAll(".cb-menu[open], .cb-card-menu[open]").forEach(menu => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape") return;
    const menu = event.target.closest(".cb-menu[open], .cb-card-menu[open]");
    if (menu) {
      menu.open = false;
      menu.querySelector("summary").focus();
    }
  });
})();
