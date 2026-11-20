// Keep the board mounted while a same-origin frame runs the card's own forms and scripts.
(function () {
  "use strict";

  function cardUrl(href) {
    const url = new URL(href);
    url.searchParams.set("board_card", "1");
    return url;
  }

  if (document.body.classList.contains("it-card-frame")) {
    // The frame defaults to top-level navigation for workflows such as submitting a grant.
    // Tabs, filters and links to another card stay inside the open dialog.
    document.querySelectorAll('a[href^="#"]').forEach(link => { link.target = "_self"; });
    document.querySelectorAll('a[data-board-card], a[href^="?"]').forEach(link => {
      link.href = cardUrl(link.href).href;
      link.target = "_self";
    });
    const forms = [...document.querySelectorAll("form[data-guard-card-edits]")];
    if (!forms.length) return;
    const values = form => new URLSearchParams(new FormData(form)).toString();
    const initial = new Map(forms.map(form => [form, values(form)]));
    function hasEdits(except) {
      return forms.some(form => form !== except && values(form) !== initial.get(form));
    }
    document.addEventListener("it42-card-dismiss", event => {
      if (hasEdits()) event.preventDefault();
    });
    // Native form submissions navigate out of the card. Exempt only the form being
    // posted, and consume that exemption even if the user cancels navigation.
    let submission;
    window.addEventListener("submit", event => {
      submission = event;
    });
    window.addEventListener("beforeunload", event => {
      const saving = submission && !submission.defaultPrevented ? submission.target : null;
      submission = null;
      if (hasEdits(saving)) {
        event.preventDefault();
        event.returnValue = true;
      }
    });
    return;
  }

  const dialog = document.querySelector(".it-board-dialog");
  if (!dialog || typeof dialog.showModal !== "function") return;
  const expand = dialog.querySelector("[data-card-expand]");
  const loading = dialog.querySelector(".it-card-loading");
  const error = dialog.querySelector(".it-card-error");
  let opener;
  let frame;

  function dismiss() {
    // Removing an iframe does not trigger beforeunload. Let its editor report dirty data first.
    const child = frame?.contentDocument;
    if (child && !child.dispatchEvent(new Event("it42-card-dismiss", { cancelable: true })) &&
        !window.confirm("Discard your unsaved changes and close this card?")) return;
    dialog.close();
    frame.remove();
    frame = null;
    dialog.classList.remove("is-expanded");
    opener.focus({ preventScroll: true });
  }

  function openCard(event) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey ||
        event.shiftKey || event.altKey) return;
    const link = event.currentTarget;
    event.preventDefault();
    opener = link;
    const title = link.getAttribute("aria-label") || link.textContent.trim();
    dialog.setAttribute("aria-label", title);
    expand.setAttribute("aria-pressed", "false");
    expand.title = "Expand card";
    expand.setAttribute("aria-label", expand.title);
    loading.hidden = false;
    error.hidden = true;
    error.querySelector("a").href = link.href;
    frame = document.createElement("iframe");
    frame.title = title;
    frame.src = cardUrl(link.href).href;
    frame.addEventListener("load", event => {
      if (event.currentTarget !== frame) return;
      const child = frame.contentDocument;
      const ready = child?.body?.classList.contains("it-card-frame");
      loading.hidden = true;
      error.hidden = Boolean(ready);
      frame.hidden = !ready;
      if (!ready) return;
      frame.title = child.title;
      dialog.setAttribute("aria-label", child.title);
      child.addEventListener("keydown", event => {
        if (event.key === "Escape" && !event.defaultPrevented && !child.querySelector("dialog[open]")) {
          event.preventDefault();
          dismiss();
        }
      });
    });
    dialog.append(frame);
    dialog.showModal();
    dialog.querySelector("[data-card-close]").focus({ preventScroll: true });
  }

  document.querySelectorAll("a[data-board-card]").forEach(link => {
    link.setAttribute("aria-haspopup", "dialog");
    link.addEventListener("click", openCard);
  });
  expand.addEventListener("click", () => {
    const full = dialog.classList.toggle("is-expanded");
    expand.setAttribute("aria-pressed", String(full));
    expand.title = full ? "Restore card size" : "Expand card";
    expand.setAttribute("aria-label", expand.title);
  });
  dialog.querySelector("[data-card-close]").addEventListener("click", dismiss);
  dialog.addEventListener("cancel", event => { event.preventDefault(); dismiss(); });
  dialog.addEventListener("click", event => {
    if (event.target !== dialog) return;
    const { left, right, top, bottom } = dialog.getBoundingClientRect();
    if (event.clientX < left || event.clientX >= right || event.clientY < top || event.clientY >= bottom) dismiss();
  });
})();
