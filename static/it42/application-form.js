/* Question progress and ordered, debounced draft saving. No answers leave this site. */
(function () {
  "use strict";
  const form = document.getElementById("application-form");
  if (!form) return;
  const questions = [...form.querySelectorAll("[data-question]")];
  const statuses = [...form.querySelectorAll("[data-save-status]")];
  let timer, inFlight = null, revision = 0, savedRevision = 0, leaving = false, savedAt = null;
  function status(text, error) {
    statuses.forEach(node => { node.textContent = text; node.classList.toggle("is-error", !!error); });
  }
  function controlsOf(question) { return [...question.querySelectorAll("input, textarea, select")].filter(el => !el.disabled); }
  function state(question) {
    const controls = controlsOf(question);
    const groups = new Map();
    let started = false, valid = true;
    for (const field of controls) {
      if (field.type === "radio" || field.type === "checkbox") {
        if (!groups.has(field.name)) groups.set(field.name, []);
        groups.get(field.name).push(field);
        continue;
      }
      const value = field.value.trim();
      if (value) started = true;
      // The generated budget inputs are checked through their source textarea below.
      if (field.closest(".it-budget")) continue;
      if (!value || !field.checkValidity()) valid = false;
      if (field.dataset.maxWords && value.split(/\s+/).filter(Boolean).length > Number(field.dataset.maxWords)) valid = false;
      if (field.matches("[data-budget]")) {
        const table = question.querySelector(".it-budget-table");
        if (table && table.classList.contains("is-invalid")) valid = false;
      }
    }
    for (const fields of groups.values()) {
      const selected = fields.some(field => field.checked);
      started ||= selected;
      valid &&= selected;
    }
    return {done: started && valid, started};
  }
  function progress() {
    let required = 0, done = 0, next = null;
    questions.forEach(question => {
      const s = state(question), mandatory = question.dataset.required === "true";
      if (mandatory) { required++; if (s.done) done++; else next ||= question; }
      const badge = question.querySelector("[data-question-state]");
      badge.textContent = s.done ? "Answered" : s.started ? "In progress" : mandatory ? "Required" : "Optional";
      badge.classList.toggle("is-answered", s.done);
      const nav = form.querySelector('[data-progress-for="' + question.dataset.number + '"]');
      const words = question.querySelector("[data-max-words]");
      nav.textContent = s.done ? "Done" : words && s.started ? words.value.trim().split(/\s+/).length + " words" : badge.textContent;
    });
    form.querySelector("[data-progress-count]").textContent = done + " of " + required + " required questions answered";
    const bar = form.querySelector("[data-progress]"); bar.max = required || 1; bar.value = done;
    const link = form.querySelector("[data-continue]");
    link.textContent = next ? "Continue question " + next.dataset.number : "Review and submit";
    link.href = next ? "#" + next.id : "#application-form";
  }
  function changed(event) {
    if (leaving || event.target.closest("dialog") || event.target.name === "confirm") return;
    revision++;
    progress();
    status("Unsaved changes");
    clearTimeout(timer);
    timer = setTimeout(save, 900);
  }
  async function save() {
    clearTimeout(timer);
    if (inFlight) { await inFlight; if (!leaving && savedRevision < revision) return save(); return; }
    if (savedRevision === revision || leaving) return;
    const current = revision;
    const body = new FormData(form); body.set("autosave", "1"); body.delete("confirm");
    status("Saving…");
    inFlight = (async () => {
      try {
        const response = await fetch(form.action || location.href, {method: "POST", body, credentials: "same-origin", headers: {Accept: "application/json"}});
        if (response.redirected || !response.headers.get("content-type")?.includes("application/json")) throw new Error("Your session may have ended. Copy your answers before signing in again.");
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Your draft could not be saved.");
        savedRevision = current; savedAt = Date.now();
        status(savedRevision === revision ? "Saved just now" : "Unsaved changes");
      } catch (error) { status(error.message + " Use Save draft to retry.", true); }
    })();
    await inFlight; inFlight = null;
  }
  form.addEventListener("input", changed);
  form.addEventListener("change", changed);
  // Wait for any older autosave before the final POST so it cannot recreate a submitted draft.
  form.addEventListener("submit", async event => {
    if (leaving) return;
    if (event.submitter?.hasAttribute("form")) return;
    event.preventDefault();
    clearTimeout(timer);
    leaving = true;
    const button = event.submitter;
    if (inFlight) await inFlight;
    form.requestSubmit(button);
  });
  window.addEventListener("beforeunload", event => {
    if (!leaving && savedRevision < revision) { event.preventDefault(); event.returnValue = ""; }
  });
  window.addEventListener("pageshow", () => { leaving = false; });
  setInterval(() => {
    if (savedAt && savedRevision === revision && !inFlight) {
      const minutes = Math.floor((Date.now() - savedAt) / 60000);
      status(minutes ? "Saved " + minutes + " min ago" : "Saved just now");
    }
  }, 30000);
  progress();
})();
