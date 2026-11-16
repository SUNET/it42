/* Word counter for long-text answers with a word limit (textarea[data-max-words], set by
 * formschema._form_field). Shows "N / limit words" in the [data-wordcount=<textarea id>]
 * element next to the box and marks it when over; the server still enforces the limit.
 */
(function () {
  "use strict";

  // Words as the server counts them: runs of non-whitespace (str.split).
  function words(text) {
    const trimmed = text.trim();
    return trimmed ? trimmed.split(/\s+/).length : 0;
  }

  // Wire one textarea to its counter element (nothing happens without one).
  function enhance(textarea) {
    const max = Number(textarea.dataset.maxWords);
    const out = document.querySelector('[data-wordcount="' + textarea.id + '"]');
    if (!out || !max) return;
    function update() {
      const n = words(textarea.value);
      out.textContent = n.toLocaleString("en-GB") + " / " + max.toLocaleString("en-GB") + " words";
      out.classList.toggle("is-over", n > max);
    }
    textarea.addEventListener("input", update);
    update();
  }

  document.querySelectorAll("textarea[data-max-words]").forEach(enhance);
})();
