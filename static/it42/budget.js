/* Budget lines for a grant application (textarea[data-budget], a "budget" field of the
 * form schema).
 *
 * The textarea stays in the form with one "What it is for | amount" line per budget line:
 * that is what the server reads. This script hides it and shows a table of label and
 * amount inputs with a running total, writing the lines back on every change. Without
 * JavaScript the textarea is used as it is.
 */
(function () {
  "use strict";

  const THOUSANDS = "\u202f"; // same narrow no-break space as formschema.format_amount

  // 42000 -> "42 000", 12.5 -> "12.50" (same narrow no-break space as the server).
  function formatAmount(value) {
    if (!isFinite(value)) return "";
    const whole = Math.round(value) === value;
    const text = whole ? String(Math.round(value)) : value.toFixed(2);
    const [int, frac] = text.split(".");
    const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, THOUSANDS);
    return frac ? grouped + "." + frac : grouped;
  }

  // The number typed in an amount box (spaces and a decimal comma allowed), NaN if none.
  function parseAmount(text) {
    const digits = String(text).replace(/\s/g, "").replace(",", ".");
    return digits === "" ? NaN : Number(digits);
  }

  // The textarea's "label | amount" lines as objects (a line without | is a label only).
  function parseLines(text) {
    return text
      .split(/\r?\n/)
      .filter((line) => line.trim() !== "")
      .map((line) => {
        const at = line.lastIndexOf("|");
        if (at < 0) return { label: line.trim(), amount: "" };
        return { label: line.slice(0, at).trim(), amount: line.slice(at + 1).trim() };
      });
  }

  // Replace one budget textarea with the table: rows of label + amount inputs, a remove
  // button per row, an add button, the running total and the max-award note.
  function enhance(textarea) {
    const currency = textarea.dataset.currency || "SEK";
    const maxAward = textarea.dataset.maxAward ? Number(textarea.dataset.maxAward) : null;
    const maxLines = Number(textarea.dataset.maxLines || 20);
    const describedBy = textarea.getAttribute("aria-describedby");
    const note = textarea.parentElement.querySelector("[data-budget-note]");

    const wrap = document.createElement("div");
    wrap.className = "it-budget";
    const table = document.createElement("table");
    table.className = "it-budget-table";
    table.innerHTML =
      '<thead><tr><th scope="col">Budget line</th><th scope="col" class="it-budget-amount">Amount (' +
      currency +
      ')</th><th scope="col"><span class="visually-hidden">Remove</span></th></tr></thead>' +
      '<tbody></tbody><tfoot><tr class="it-budget-total"><th scope="row">Total requested</th>' +
      '<td class="it-budget-amount" data-total>0</td><td></td></tr></tfoot>';
    const body = table.querySelector("tbody");
    const totalCell = table.querySelector("[data-total]");
    const add = document.createElement("button");
    add.type = "button";
    add.className = "btn btn-light btn-sm it-budget-add";
    add.textContent = "+ Add a cost line";
    const hint = document.createElement("p");
    hint.className = "form-text";
    hint.textContent = maxAward
      ? "Add your own lines. The total cannot go over " + formatAmount(maxAward) + " " + currency + "."
      : "Add your own lines.";
    const live = document.createElement("p");
    live.className = "visually-hidden";
    live.setAttribute("aria-live", "polite");
    wrap.append(table, add, hint, live);

    // The table's current rows.
    function rows() {
      return Array.from(body.querySelectorAll("tr"));
    }

    // Write the rows back to the textarea as lines, recompute the total and the over-limit mark.
    function save() {
      const lines = rows().map((row) => {
        const label = row.querySelector("[data-label]").value.trim();
        const amount = row.querySelector("[data-amount]").value.trim();
        return label || amount ? label + " | " + amount : "";
      });
      textarea.value = lines.filter(Boolean).join("\n");
      const total = rows().reduce((sum, row) => {
        const n = parseAmount(row.querySelector("[data-amount]").value);
        return sum + (isNaN(n) ? 0 : n);
      }, 0);
      totalCell.textContent = formatAmount(total) + " " + currency;
      const over = maxAward !== null && total > maxAward;
      table.classList.toggle("is-over", over);
      const invalid = over || rows().some(row => {
        const label = row.querySelector("[data-label]").value.trim();
        const amount = row.querySelector("[data-amount]").value.trim();
        if (!label && !amount) return false;
        const n = parseAmount(amount);
        return !label || !Number.isFinite(n) || n < 0 || Math.abs(n * 100 - Math.round(n * 100)) > 0.00001;
      });
      table.classList.toggle("is-invalid", invalid);
      totalCell.setAttribute("aria-invalid", over ? "true" : "false");
      add.disabled = rows().length >= maxLines;
    }

    // Append one row (optionally filled from a parsed line) and wire its buttons.
    function addRow(line, focus) {
      if (rows().length >= maxLines) return;
      const row = document.createElement("tr");
      row.innerHTML =
        '<td><input class="form-control form-control-sm" type="text" maxlength="200" data-label placeholder="e.g. Staff costs" aria-label="What the money is for"></td>' +
        '<td class="it-budget-amount"><input class="form-control form-control-sm" type="text" inputmode="decimal" data-amount placeholder="0" aria-label="Amount in ' +
        currency +
        '"></td>' +
        '<td><button class="it-icon-btn" type="button" data-remove aria-label="Remove line">&times;</button></td>';
      row.querySelector("[data-label]").placeholder = rows().length ? "e.g. Equipment" : "e.g. Staff costs";
      row.querySelector("[data-label]").value = line ? line.label : "";
      row.querySelector("[data-amount]").value = line ? line.amount : "";
      row.querySelector("[data-remove]").addEventListener("click", function () {
        row.remove();
        if (!rows().length) addRow(null, true);
        save();
        live.textContent = "Line removed.";
        textarea.dispatchEvent(new Event("input", {bubbles: true}));
        add.focus();
      });
      row.addEventListener("input", save);
      body.append(row);
      if (focus) row.querySelector("[data-label]").focus();
    }

    const initial = parseLines(textarea.value);
    (initial.length ? initial : Array.from({length: Math.min(2, maxLines)}, () => null)).forEach((line) => addRow(line, false));
    add.addEventListener("click", function () {
      addRow(null, true);
      save();
      live.textContent = "Line added.";
      textarea.dispatchEvent(new Event("input", {bubbles: true}));
    });

    textarea.hidden = true;
    textarea.setAttribute("tabindex", "-1");
    textarea.setAttribute("aria-hidden", "true");
    if (describedBy) table.setAttribute("aria-describedby", describedBy);
    if (note) note.hidden = true;
    textarea.insertAdjacentElement("afterend", wrap);
    save();
  }

  document.querySelectorAll("textarea[data-budget]").forEach(enhance);
})();
