/* Grant form builder (templates/org/grants/form.html, design "Grants / Form builder").
 *
 * Edits the JSON in the form_schema textarea (the field the server validates). Widgets
 * come from the server (WIDGETS in it42.common.formschema, through json_script, and the
 * palette rendered in the template), the base fields are locked (only the administrating
 * organisation's Required switch stays editable, see config.optional) and the names in
 * config.defaults get the "Default" badge. Field names are never typed: they are derived
 * from the labels (same rules as formschema.assign_names, which the server applies again
 * on save).
 *
 * Cards are reordered with Pointer Events (mouse, pen and touch alike; see sortable.js)
 * or the keyboard (Alt+Up/Down moves, Delete removes, Enter edits). Everything is also
 * reachable through buttons, and an aria-live region reports every change. Plain
 * JavaScript, no dependencies.
 */
(function () {
  "use strict";

  const form = document.getElementById("grant-form");
  if (!form) return;
  const content = form.closest(".it-app-content");
  const mobilePanels = form.querySelector(".fb-mobile-panels");
  const compact = window.matchMedia("(max-width: 1199.98px)");
  function resizePanels() { mobilePanels.open = !compact.matches; }
  resizePanels();
  compact.addEventListener("change", resizePanels);
  const config = JSON.parse(document.getElementById(form.dataset.config).textContent);
  const textarea = document.getElementById(form.dataset.target);
  const builder = form.querySelector("[data-builder]");
  const canvasEl = form.querySelector("[data-canvas]");
  const lockedEl = form.querySelector("[data-locked]");
  const announceEl = form.querySelector("[data-announce]");
  const jsonError = form.querySelector("[data-json-error]");
  const saveState = form.querySelector("[data-save-state]");
  const templateInput = form.querySelector('input[name="template"]');
  const deadlineInput = form.querySelector('[name="deadline"]');
  const deadlineTimeInput = form.querySelector('[name="deadline_time"]');
  const widgetsByType = Object.fromEntries(config.widgets.map((w) => [w.type, w]));
  const templatesById = Object.fromEntries(config.templates.map((t) => [String(t.id), t]));
  const locked = new Set(config.locked);
  const optional = new Set(config.optional || []);
  const defaults = new Set(config.defaults || []);
  const reserved = new Set(["documents", "csrfmiddlewaretoken"]);
  const LAYOUT = new Set(["heading", "paragraph", "deadline", "link"]);
  const THRESHOLD = 5; // px before a press becomes a drag
  const EDGE = 48; // px from the content edge where a drag auto-scrolls

  let schema = [];
  let editing = -1; // index into schema of the card with its editor open
  let editorSnapshot = null;
  let dirty = false;
  let submitting = false;

  // --- helpers ----------------------------------------------------------------

  // Build an element: attrs may hold class, text, html, on<event> handlers and plain attributes.
  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key === "html") node.innerHTML = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (value === true) node.setAttribute(key, "");
      else if (value !== false && value != null) node.setAttribute(key, value);
    }
    for (const child of children || []) {
      if (child != null) node.append(child);
    }
    return node;
  }

  // Icons are inlined by the server: a field type's icon sits on its palette item, the
  // others (grip, edit, trash, ...) in the hidden [data-icons] sprite. Cards copy them.
  function icon(name) {
    const item =
      form.querySelector('[data-icons] [data-icon="' + name + '"] svg') ||
      form.querySelector('[data-palette] [data-type="' + name + '"] .fb-palette-icon svg') ||
      form.querySelector(".fb-palette-icon svg");
    return el("span", { class: "fb-card-icon", "aria-hidden": "true" }, [item.cloneNode(true)]);
  }

  // Entries that are shown but have no answer (formschema.LAYOUT_TYPES).
  function isLayout(spec) {
    return LAYOUT.has(spec.type);
  }

  // The three base fields: shown under "Always included", never moved or removed.
  function isLocked(spec) {
    return locked.has(spec.name);
  }

  // Mirrors formschema.field_name: ASCII lowercase letters, digits and underscores.
  function fieldName(label) {
    let name = String(label || "")
      .normalize("NFKD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/[^\x00-\x7f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
    if (!name) return "field";
    if (!/^[a-z]/.test(name) || reserved.has(name)) name = "f_" + name;
    return name.slice(0, 40);
  }

  // Mirrors formschema.assign_names: every entry is named after its label, unique in
  // order; base fields keep their fixed names (a type in config.type_names always gets
  // that name) and nothing else may use them.
  function assignNames() {
    const taken = new Set();
    const typeNames = config.type_names || {};
    for (const spec of schema) {
      let name = typeNames[spec.type] || spec.name;
      if (!locked.has(name) || taken.has(name)) {
        const base = fieldName(spec.label);
        name = base;
        for (let n = 2; taken.has(name) || locked.has(name); n++) {
          const suffix = "_" + n;
          name = base.slice(0, 40 - suffix.length) + suffix;
        }
      }
      taken.add(name);
      spec.name = name;
    }
  }

  // Tell screen readers what just happened (the aria-live region under the cards).
  function announce(text) {
    announceEl.textContent = text;
  }

  // The textarea's JSON as a list of objects; anything else becomes an empty entry.
  function parse(text) {
    const value = JSON.parse(text);
    if (!Array.isArray(value)) throw new Error("The schema must be a list.");
    return value.map((raw) => (raw && typeof raw === "object" ? raw : {}));
  }

  // Flip the save-state text to "Unsaved changes" (once) and arm the leave warning.
  function markDirty() {
    if (dirty) return;
    dirty = true;
    saveState.querySelector("span").textContent = "Unsaved changes";
    saveState.classList.add("is-dirty");
  }

  // Write the schema back to the textarea, the only thing the server reads; `changed`
  // false means the initial load, which is not an edit.
  function save(changed) {
    assignNames();
    textarea.value = JSON.stringify(schema, null, 2);
    jsonError.textContent = "";
    jsonError.classList.remove("d-block");
    textarea.classList.remove("is-invalid");
    if (changed !== false) markDirty();
    renderSummary();
  }

  // The Form summary numbers under Grant settings (same rule as views.form_summary).
  function renderSummary() {
    const added = schema.filter((s) => !isLocked(s));
    const sums = {
      fields: added.length,
      required: added.filter((s) => s.required).length,
      defaults: added.filter((s) => defaults.has(s.name)).length,
    };
    for (const [key, value] of Object.entries(sums)) {
      const out = form.querySelector('[data-sum="' + key + '"]');
      if (out) out.textContent = value;
    }
  }

  // "75000" -> "75 000" (narrow no-break spaces), for the budget card.
  function formatAmount(value) {
    const text = String(value);
    return text.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  }

  // --- adding fields ------------------------------------------------------------

  // A fresh entry for a palette type, with a starter label and the keys the type needs.
  function newField(type) {
    const widget = widgetsByType[type];
    const spec = { name: "", label: widget.label, type: type, required: false };
    if (type === "heading") spec.label = "New section";
    if (type === "paragraph") spec.label = "Explain what this section is about.";
    if (type === "link") spec.label = "Read the full call";
    if (type === "deadline") spec.label = "Application deadline";
    if (type === "budget") spec.currency = (config.currencies || ["SEK"])[0];
    if (widget.keys.includes("options")) spec.options = ["Option 1", "Option 2"];
    return spec;
  }

  // Is there room for `count` more fields under config.max_fields? Announces when not.
  function room(count) {
    if (schema.length + count > config.max_fields) {
      announce("The form can have at most " + config.max_fields + " fields.");
      return false;
    }
    return true;
  }

  // Add one component at the end of the form and open its editor.
  function insertField(type) {
    if (!widgetsByType[type] || !room(1)) return;
    if (type === "deadline" && schema.some((s) => s.type === "deadline")) {
      announce("The form already shows the application deadline.");
      return;
    }
    finishEditing();
    const spec = newField(type);
    schema.push(spec);
    editing = schema.length - 1;
    editorSnapshot = null;
    save();
    render();
    announce(widgetsByType[type].label + " added at the end of the form.");
    focusEditor();
  }

  // A saved template's fields, after the current ones. Base fields are already there;
  // a default field that is still on the form is not added twice.
  function appendTemplate(template) {
    finishEditing();
    const present = new Set(schema.map((s) => s.name));
    const hasDeadline = schema.some(s => s.type === "deadline");
    const fields = template.schema.filter(
      (s) => !locked.has(s.name) && !(s.type === "deadline" && hasDeadline) && !(defaults.has(s.name) && present.has(s.name))
    );
    if (!fields.length) {
      announce("Every field of " + template.name + " is already on the form.");
      return;
    }
    if (!room(fields.length)) return;
    for (const spec of fields) schema.push(JSON.parse(JSON.stringify(spec)));
    editing = -1;
    save();
    render();
    announce(fields.length + " fields from " + template.name + " added at the end of the form.");
    focusCard(schema.length - 1);
  }

  // Replace the whole form with a template (or the blank form) after asking.
  function loadTemplate(key) {
    const template = key === "blank" ? null : templatesById[key];
    const name = template ? template.name : "a blank form";
    const added = schema.filter((s) => !isLocked(s)).length;
    if (added && !window.confirm("Replace the current form with " + name + "? The " + added + " fields you have now are removed.")) {
      return;
    }
    schema = JSON.parse(JSON.stringify(template ? template.schema : config.start));
    for (const spec of schema) normalise(spec);
    templateInput.value = template ? String(template.id) : "";
    editing = -1;
    save();
    render();
    announce((template ? template.name : "A blank form") + " loaded.");
    focusCard(schema.findIndex((s) => !isLocked(s)));
  }

  // The Saved templates dropdown: current name, meta line and the tick on the chosen one.
  function renderPick() {
    const current = templateInput.value ? templatesById[templateInput.value] : null;
    const nameEl = form.querySelector("[data-pick-name]");
    const metaEl = form.querySelector("[data-pick-meta]");
    if (current) {
      nameEl.textContent = current.name;
      metaEl.textContent = current.field_count + " field" + (current.field_count === 1 ? "" : "s") + " · this form is based on it";
    } else {
      nameEl.textContent = "No template";
      metaEl.textContent = "Pick one to replace the form with it";
    }
    for (const item of form.querySelectorAll("[data-load]")) {
      const chosen = current && item.dataset.load === String(current.id);
      item.classList.toggle("is-current", !!chosen);
      item.setAttribute("aria-pressed", chosen ? "true" : "false");
    }
  }

  // --- cards ------------------------------------------------------------------

  // The grey line under a card's title: the secondary text, or type and required-ness.
  function secondary(spec) {
    if (spec.description) return spec.description;
    const widget = widgetsByType[spec.type] || { label: spec.type };
    if (isLayout(spec)) return widget.label;
    return widget.label + " · " + (spec.required ? "Required" : "Optional");
  }

  // The Required switch of a card (role=switch, announces the change).
  function requiredSwitch(spec, index, disabled) {
    const id = "fb-required-" + index;
    return el("label", { class: "it-switch", for: id }, [
      el("input", {
        id: id,
        type: "checkbox",
        role: "switch",
        checked: !!spec.required,
        disabled: !!disabled,
        "aria-label": "Required: " + spec.label,
        onchange: (event) => {
          spec.required = event.target.checked;
          save();
          renderCards();
          announce(spec.label + (spec.required ? " is now required." : " is now optional."));
        },
      }),
      el("span", { class: "it-switch-track", "aria-hidden": "true" }),
      el("span", { class: "it-switch-text", text: spec.required ? "Required" : "Not required" }),
    ]);
  }

  // The deadline card's chips, read from the Grant settings inputs.
  function deadlineText() {
    const date = deadlineInput && deadlineInput.value ? new Date(deadlineInput.value + "T00:00:00") : null;
    const time = deadlineTimeInput && deadlineTimeInput.value ? deadlineTimeInput.value : "";
    const day = date && !isNaN(date) ? date.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }) : "Date not set";
    const zone = date ? new Intl.DateTimeFormat("en-GB", {timeZone: config.timezone, timeZoneName: "short"}).formatToParts(date).find(part => part.type === "timeZoneName").value : config.timezone;
    return { day: day, time: time ? time + " " + zone : "Time not set" };
  }

  // What applicants will see for an entry, disabled: inputs, chips for funder-set blocks,
  // a sketch of the budget table.
  function preview(spec) {
    const attrs = { class: "form-control", disabled: true, tabindex: -1 };
    if (spec.placeholder) attrs.placeholder = spec.placeholder;
    else if (spec.description && !isLayout(spec)) attrs.placeholder = spec.description;
    switch (spec.type) {
      case "textarea":
        return el("textarea", { ...attrs, rows: Math.min(spec.rows || 3, 4) });
      case "email":
      case "url":
      case "tel":
        return el("input", { ...attrs, type: spec.type });
      case "number":
      case "integer":
        return el("input", { ...attrs, type: "number", min: spec.min, max: spec.max });
      case "date":
      case "time":
        return el("input", { ...attrs, type: spec.type });
      case "datetime":
        return el("input", { ...attrs, type: "datetime-local" });
      case "select":
        return el("select", { class: "form-select", disabled: true, tabindex: -1 }, (spec.options || []).map((o) => el("option", { text: o })));
      case "radio":
      case "checkboxes": {
        const type = spec.type === "radio" ? "radio" : "checkbox";
        const options = spec.options || [];
        const nodes = options.slice(0, 5).map((o) =>
          el("div", { class: "form-check" }, [
            el("input", { class: "form-check-input", type: type, disabled: true, tabindex: -1 }),
            el("label", { class: "form-check-label", text: o }),
          ])
        );
        if (options.length > 5) nodes.push(el("div", { class: "fb-more", text: "+" + (options.length - 5) + " more" }));
        return el("div", {}, nodes);
      }
      case "national_infrastructure":
      case "checkbox":
        return el("div", {class: "fb-yesno"}, ["Yes", "No"].map(answer =>
          el("label", {class: "form-check"}, [el("input", {type: "radio", class: "form-check-input", disabled: true}), el("span", {text: answer})])
        ));
      case "research_org":
        return el("select", { class: "form-select", disabled: true, tabindex: -1 }, [el("option", { text: "Choose an organisation" })]);
      case "budget": {
        const currency = spec.currency || "SEK";
        return el("div", { class: "fb-budget" }, [
          el("div", { class: "fb-budget-row fb-budget-head" }, [el("span", { text: "Budget line" }), el("span", { text: "Amount (" + currency + ")" })]),
          el("div", { class: "fb-budget-row" }, [el("span", { text: "e.g. Staff costs" }), el("span", { text: "0 " + currency })]),
          el("div", { class: "fb-budget-row fb-budget-total" }, [el("span", { text: "Total requested" }), el("span", { text: "0 " + currency })]),
          el("p", { class: "fb-more", text: spec.max_award ? "The total cannot go over the maximum award of " + formatAmount(spec.max_award) + " " + currency + "." : "No maximum award set." }),
        ]);
      }
      case "deadline": {
        const when = deadlineText();
        return el("div", { class: "fb-chips" }, [
          el("span", { class: "fb-chip" }, [icon("date"), el("span", { text: when.day })]),
          el("span", { class: "fb-chip" }, [icon("time"), el("span", { text: when.time })]),
        ]);
      }
      case "link":
        return el("div", { class: "fb-chips" }, [
          el("span", { class: "fb-chip" + (spec.url ? "" : " is-empty") }, [icon("link"), el("span", { text: spec.url || "No web address yet — add one before publishing" })]),
        ]);
      case "heading":
        return null;
      case "paragraph":
        return el("p", { class: "fb-paragraph", text: spec.label });
      default:
        return el("input", { ...attrs, type: "text" });
    }
  }

  // The bold title of a card (headings show their text, explanation blocks their type).
  function cardTitle(spec) {
    if (spec.type === "heading") return spec.label || "Section heading";
    if (spec.type === "paragraph") return "Explanation text";
    return spec.label || "Untitled field";
  }

  // A small round button with one icon and an aria-label (edit, remove).
  function iconButton(label, name, onclick, extra) {
    return el("button", { type: "button", class: "it-icon-btn " + (extra || ""), "aria-label": label, title: label, onclick: onclick }, [icon(name).firstChild]);
  }

  // The "Always included" strip: the base fields, with the org field's Required switch.
  function renderLocked() {
    lockedEl.replaceChildren();
    schema.forEach((spec, index) => {
      if (!isLocked(spec)) return;
      const widget = widgetsByType[spec.type] || { label: spec.type };
      lockedEl.append(
        el("li", { class: "fb-locked-row" }, [
          icon(spec.type),
          el("span", { class: "fb-locked-text" }, [el("strong", { text: spec.label }), el("small", { text: widget.label + " · Always included" })]),
          optional.has(spec.name) ? requiredSwitch(spec, index, false) : el("span", { class: "fb-locked-required", text: "Required" }),
        ])
      );
    });
  }

  // Draw every non-locked entry as a card; the one being edited shows the inline editor
  // instead of its preview. Keeps the scroll position when re-drawing during an edit.
  function renderCards() {
    const open = canvasEl.querySelector(".fb-card.is-editing");
    const scrollTop = content.scrollTop;
    canvasEl.replaceChildren();
    const added = schema.map((spec, index) => ({ spec, index })).filter((s) => !isLocked(s.spec));
    if (!added.length) {
      canvasEl.append(el("li", { class: "fb-empty", text: "No fields yet. Add a component or a saved template from the left." }));
    }
    added.forEach(({ spec, index }, position) => {
      const widget = widgetsByType[spec.type] || { label: spec.type };
      const isEditing = index === editing;
      const card = el(
        "li",
        {
          class: "fb-card fb-card-" + spec.type + (isEditing ? " is-editing" : ""),
          tabindex: 0,
          "data-index": index,
          "aria-label": widget.label + ": " + cardTitle(spec) + ". Position " + (position + 1) + " of " + added.length + ".",
          onkeydown: (event) => {
            if (event.target !== card) return;
            if (event.key === "Enter") {
              event.preventDefault();
              openEditor(index);
            } else if (event.altKey && event.key === "ArrowUp") {
              event.preventDefault();
              moveField(index, -1);
            } else if (event.altKey && event.key === "ArrowDown") {
              event.preventDefault();
              moveField(index, 1);
            } else if (event.key === "Delete") {
              event.preventDefault();
              removeField(index);
            }
          },
        },
        [
          el("div", { class: "fb-card-head" }, [
            el("span", { class: "fb-grip", title: "Drag to reorder (or Alt+Up / Alt+Down)", "aria-hidden": "true" }, [icon("grip").firstChild]),
            icon(spec.type),
            el("div", { class: "fb-card-title" }, [el("strong", { text: cardTitle(spec) }), el("small", { text: secondary(spec) })]),
            el("div", { class: "fb-card-tools" }, [
              defaults.has(spec.name) ? el("span", { class: "fb-default" }, [icon("sparkle").firstChild, el("span", { text: "Default" })]) : null,
              isLayout(spec) ? null : requiredSwitch(spec, index, false),
              iconButton(isEditing ? "Close the editor for " + cardTitle(spec) : "Edit " + cardTitle(spec), "edit", () => (isEditing ? closeEditor() : openEditor(index))),
              iconButton("Remove " + cardTitle(spec), "trash", () => removeField(index), "it-icon-btn-danger"),
            ]),
          ]),
          isEditing ? editor(spec, index) : null,
          !isEditing && spec.help_text && !isLayout(spec) ? el("div", { class: "it-form-help" }, [icon("info").firstChild, el("span", { text: spec.help_text })]) : null,
          (() => {
            const body = preview(spec);
            return body ? el("div", { class: "fb-card-body" }, [body]) : null;
          })(),
        ]
      );
      canvasEl.append(card);
    });
    if (open) content.scrollTop = scrollTop;
  }

  // Move keyboard focus to the card of schema index `index`.
  function focusCard(index) {
    const card = canvasEl.querySelector('[data-index="' + index + '"]');
    if (card) card.focus();
  }

  // Move keyboard focus to the first box of the open editor.
  function focusEditor() {
    const first = canvasEl.querySelector(".fb-editor input, .fb-editor textarea, .fb-editor select");
    if (first) first.focus();
  }

  // Move an entry one step up (delta -1) or down (+1) among the non-locked entries.
  function moveField(index, delta) {
    const order = schema.map((s, i) => i).filter((i) => !isLocked(schema[i]));
    const at = order.indexOf(index);
    const target = order[at + delta];
    if (target === undefined) return;
    const [spec] = schema.splice(index, 1);
    schema.splice(target, 0, spec);
    if (editing === index) editing = target;
    save();
    renderCards();
    announce(cardTitle(spec) + " moved to position " + (at + delta + 1) + ".");
    focusCard(target);
  }

  // Remove an entry (never a locked one) and put focus on the next card or the add zone.
  function removeField(index) {
    const spec = schema[index];
    if (!spec || isLocked(spec)) return;
    schema.splice(index, 1);
    if (editing === index) editing = -1;
    else if (editing > index) editing -= 1;
    save();
    renderCards();
    announce(cardTitle(spec) + " removed.");
    const next = schema.findIndex((s, i) => i >= index && !isLocked(s));
    if (next >= 0) focusCard(next);
    else form.querySelector("[data-add-toggle]").focus();
  }

  // Open the inline editor of one card (closing any other).
  function finishEditing() { editorSnapshot = null; editing = -1; }

  function openEditor(index) {
    finishEditing();
    editorSnapshot = JSON.parse(JSON.stringify(schema[index]));
    editing = index;
    renderCards();
    focusEditor();
  }

  function closeEditor(cancel) {
    const index = editing;
    if (cancel && index >= 0) {
      if (editorSnapshot) schema[index] = editorSnapshot;
      else schema.splice(index, 1); // Cancel a newly added field.
      save();
    }
    finishEditing();
    renderCards();
    focusCard(index);
  }

  // --- inline editor ------------------------------------------------------------

  // The inline editor of a card: title, secondary text, explanation, then the settings the
  // type allows (word limit, options, currency and max award, web address, ...). Every
  // box writes straight into the entry and saves; Enter or Escape closes it.
  function editor(spec, index) {
    const widget = widgetsByType[spec.type] || { keys: [] };
    const layout = isLayout(spec);
    const update = (key, value) => {
      if (value === "" || value == null) delete spec[key];
      else spec[key] = value;
      save();
      const title = canvasEl.querySelector('[data-index="' + index + '"] .fb-card-title');
      if (title) {
        title.querySelector("strong").textContent = cardTitle(spec);
        title.querySelector("small").textContent = secondary(spec);
      }
    };
    const field = (key, label, opts) => {
      opts = opts || {};
      const id = "fb-edit-" + key + "-" + index;
      let control;
      if (opts.select) {
        control = el("select", { id: id, class: "form-select", onchange: (e) => update(key, e.target.value) }, opts.select.map((o) => el("option", { value: o, text: o, selected: (spec[key] || opts.select[0]) === o })));
      } else {
        control = el(opts.multiline ? "textarea" : "input", {
          id: id,
          class: "form-control",
          type: opts.multiline ? null : opts.type || "text",
          rows: opts.multiline ? opts.rows || 3 : null,
          value: opts.multiline ? null : spec[key] == null ? "" : spec[key],
          text: opts.multiline ? (spec[key] == null ? "" : spec[key]) : null,
          placeholder: opts.placeholder || null,
          min: opts.min,
          max: opts.max,
          maxlength: opts.maxlength,
          oninput: (event) => {
            let value = event.target.value;
            if (opts.number) {
              value = value.trim() === "" ? "" : Number(value);
              if (Number.isNaN(value)) return;
              if (opts.integer && !Number.isInteger(value)) return;
            }
            if (opts.onchange) opts.onchange(value);
            else update(key, value);
          },
        });
      }
      return el("div", { class: "fb-edit-field" + (opts.half ? " is-half" : "") }, [
        el("label", { for: id, text: label + (opts.optional ? " · optional" : "") }),
        control,
        opts.hint ? el("div", { class: "form-text", text: opts.hint }) : null,
      ]);
    };

    const rows = [];
    if (spec.type === "heading") {
      rows.push(field("label", "Heading", { maxlength: 200, onchange: (v) => update("label", v) }));
    } else if (spec.type === "paragraph") {
      rows.push(field("label", "Text shown to applicants", { multiline: true, rows: 4, maxlength: 2000, onchange: (v) => update("label", v) }));
    } else {
      rows.push(field("label", spec.type === "link" ? "Link text" : "Question title", { maxlength: 200, onchange: (v) => update("label", v) }));
      rows.push(field("description", "Secondary text", { optional: true, maxlength: 300, hint: "A short line under the title." }));
      if (!layout) rows.push(field("help_text", "Explanation for applicants", { optional: true, multiline: true, maxlength: 500, placeholder: "Add guidance, examples or rules. Shown to applicants in a box under the question." }));
    }
    const half = (a, b) => el("div", { class: "fb-edit-row" }, [a, b]);
    if (widget.keys.includes("placeholder")) rows.push(field("placeholder", "Placeholder", { optional: true, maxlength: 200, hint: "Grey example text inside the empty box." }));
    if (spec.type === "textarea") {
      rows.push(half(field("max_words", "Word limit", { optional: true, type: "number", number: true, integer: true, min: 1, max: config.max_words, half: true }), field("rows", "Box height (rows)", { optional: true, type: "number", number: true, integer: true, min: 2, max: 20, half: true })));
    } else if (widget.keys.includes("max_length")) {
      rows.push(field("max_length", "Maximum length (characters)", { optional: true, type: "number", number: true, integer: true, min: 1, max: 500, half: true }));
    }
    if (widget.keys.includes("min")) {
      rows.push(half(field("min", "Minimum", { optional: true, type: "number", number: true, integer: spec.type === "integer", half: true }), field("max", "Maximum", { optional: true, type: "number", number: true, integer: spec.type === "integer", half: true })));
    }
    if (widget.keys.includes("options")) {
      const list = el("div", {class: "fb-options"});
      const drawOptions = () => {
        list.replaceChildren();
        (spec.options || []).forEach((option, i) => {
          list.append(el("div", {class: "fb-option-row"}, [
            el("input", {class: "form-control", value: option, "aria-label": "Option " + (i + 1), maxlength: 200,
              oninput: e => { spec.options[i] = e.target.value; save(); }}),
            el("button", {type: "button", class: "it-icon-btn", text: "×", "aria-label": "Remove option " + (i + 1), onclick: () => {
              spec.options.splice(i, 1); save(); drawOptions();
            }})
          ]));
        });
        list.append(el("button", {type: "button", class: "btn btn-light", text: "+ Add option", disabled: spec.options.length >= config.max_options, onclick: () => {
          spec.options.push("Option " + (spec.options.length + 1)); save(); drawOptions();
          list.querySelectorAll("input")[spec.options.length - 1].focus();
        }}));
      };
      drawOptions();
      rows.push(list);
    }
    if (spec.type === "budget") {
      rows.push(half(field("currency", "Currency", { select: config.currencies }), field("max_award", "Maximum award", { optional: true, type: "number", number: true, integer: true, min: 1, half: true, hint: "Applicants cannot ask for more in total." })));
      rows.push(field("max_lines", "Most lines an applicant may add", { optional: true, type: "number", number: true, integer: true, min: 1, max: config.max_budget_lines, half: true }));
    }
    if (spec.type === "link") {
      rows.push(field("url", "Web address", { type: "url", maxlength: 500, placeholder: "https://", hint: "Needed before the grant can be published." }));
    }
    if (spec.type === "deadline") {
      rows.push(
        el("div", { class: "fb-edit-field" }, [
          el("p", { class: "form-text mb-1", text: "The date and time come from Grant settings." }),
          el("button", { type: "button", class: "btn btn-sm btn-light", text: "Open Grant settings", onclick: openSettings }),
        ])
      );
    }
    if (!isLocked(spec) && !layout) {
      rows.push(
        field("type", "Change the type", {
          select: config.widgets.filter((w) => w.palette !== false && !LAYOUT.has(w.type)).map((w) => w.type),
        })
      );
      const select = rows[rows.length - 1].querySelector("select");
      for (const option of select.options) option.textContent = widgetsByType[option.value].label;
      select.onchange = (event) => {
        const next = widgetsByType[event.target.value];
        spec.type = next.type;
        for (const key of Object.keys(spec)) {
          if (!["name", "label", "type", "required", "help_text", "description"].includes(key) && !next.keys.includes(key)) delete spec[key];
        }
        if (next.keys.includes("options") && !spec.options) spec.options = ["Option 1", "Option 2"];
        if (next.type === "budget" && !spec.currency) spec.currency = config.currencies[0];
        save();
        renderCards();
        focusEditor();
      };
    }
    return el("div", { class: "fb-editor", onkeydown: (event) => {
      if (event.key === "Enter" && event.target.tagName !== "TEXTAREA" && event.target.tagName !== "BUTTON") {
        event.preventDefault();
        closeEditor();
      } else if (event.key === "Escape") {
        event.preventDefault();
        closeEditor(true);
      }
    } }, [
      ...rows,
      el("div", { class: "fb-editor-actions" }, [
        el("button", { type: "button", class: "btn btn-light", text: "Cancel", onclick: () => closeEditor(true) }),
        el("button", { type: "button", class: "btn btn-primary", text: "Done", onclick: () => closeEditor(false) }),
      ]),
    ]);
  }

  // Switch the left panel to Grant settings and focus the deadline (deadline card's pencil).
  function openSettings() {
    mobilePanels.open = true;
    const tab = form.querySelector("#tab-settings");
    if (tab) tab.click();
    if (deadlineInput) deadlineInput.focus();
  }

  // --- pointer drag (after sortable.js) -------------------------------------------

  (function setupDrag() {
    let drag = null;

    // The cards in their current DOM order.
    function cardsOf() {
      return Array.from(canvasEl.querySelectorAll(":scope > li.fb-card"));
    }

    // Put `card` where a pointer at viewport y points.
    function placeAt(card, y) {
      const siblings = cardsOf().filter((c) => c !== card);
      for (const sibling of siblings) {
        const rect = sibling.getBoundingClientRect();
        if (y < rect.top + rect.height / 2) {
          if (card.nextElementSibling !== sibling) canvasEl.insertBefore(card, sibling);
          return;
        }
      }
      if (canvasEl.lastElementChild !== card) canvasEl.appendChild(card);
    }

    // End a drag: tidy up, then apply the new order to the schema (locked fields stay first).
    function finish(cancelled) {
      if (!drag) return;
      const state = drag;
      drag = null;
      document.body.classList.remove("fb-sorting");
      state.card.classList.remove("is-dragging");
      state.card.style.transform = "";
      try { canvasEl.releasePointerCapture(state.pointerId); } catch (e) { /* released */ }
      if (!state.active) return;
      const domOrder = cardsOf().map((c) => Number(c.dataset.index));
      if (cancelled || domOrder.join() === state.before.join()) {
        renderCards();
        return;
      }
      // Rebuild the schema: locked fields stay where they were, the rest follow the DOM.
      const lockedSpecs = schema.filter(isLocked);
      const moved = domOrder.map((i) => schema[i]);
      const editingSpec = editing >= 0 ? schema[editing] : null;
      schema = [...lockedSpecs, ...moved];
      editing = editingSpec ? schema.indexOf(editingSpec) : -1;
      save();
      renderCards();
      const position = domOrder.indexOf(Number(state.card.dataset.index)) + 1;
      announce(cardTitle(moved[position - 1]) + " moved to position " + position + " of " + moved.length + ".");
      focusCard(schema.indexOf(moved[position - 1]));
    }

    canvasEl.addEventListener("pointerdown", (event) => {
      if (drag || event.button !== 0) return;
      const card = event.target.closest("li.fb-card");
      if (!card || card.parentNode !== canvasEl) return;
      if (event.target.closest("a, button, input, select, textarea, label, .fb-editor")) return;
      const onGrip = Boolean(event.target.closest(".fb-grip"));
      if (event.pointerType !== "mouse" && !onGrip) return; // touch scrolls unless on the grip
      if (event.pointerType === "mouse" && !onGrip && !event.target.closest(".fb-card-head")) return;
      drag = { card, pointerId: event.pointerId, startY: event.clientY, before: cardsOf().map((c) => Number(c.dataset.index)), active: false };
      canvasEl.setPointerCapture(event.pointerId);
      if (onGrip) event.preventDefault();
    });
    canvasEl.addEventListener("pointermove", (event) => {
      if (!drag || event.pointerId !== drag.pointerId) return;
      if (!drag.active) {
        if (Math.abs(event.clientY - drag.startY) < THRESHOLD) return;
        drag.active = true;
        drag.card.classList.add("is-dragging");
        document.body.classList.add("fb-sorting");
      }
      event.preventDefault();
      placeAt(drag.card, event.clientY);
      const rect = drag.card.getBoundingClientRect();
      drag.card.style.transform = "translateY(" + Math.round(event.clientY - (rect.top + rect.height / 2)) + "px)";
      const { top, bottom } = content.getBoundingClientRect();
      if (event.clientY < top + EDGE) content.scrollBy(0, -Math.ceil((top + EDGE - event.clientY) / 4));
      else if (event.clientY > bottom - EDGE) content.scrollBy(0, Math.ceil((event.clientY - bottom + EDGE) / 4));
    });
    canvasEl.addEventListener("pointerup", (event) => { if (drag && event.pointerId === drag.pointerId) finish(false); });
    canvasEl.addEventListener("pointercancel", (event) => { if (drag && event.pointerId === drag.pointerId) finish(true); });
    canvasEl.addEventListener("lostpointercapture", (event) => { if (drag && event.pointerId === drag.pointerId) finish(false); });
    canvasEl.addEventListener("dragstart", (event) => { if (drag) event.preventDefault(); });
  })();

  // --- palette, search, add menu, template pick ------------------------------------

  form.addEventListener("click", (event) => {
    const add = event.target.closest("[data-type], [data-template]");
    if (add && form.contains(add) && !add.closest("[data-pick]")) {
      event.preventDefault();
      closeAddMenu();
      if (add.dataset.type) insertField(add.dataset.type);
      else if (templatesById[add.dataset.template]) appendTemplate(templatesById[add.dataset.template]);
      return;
    }
    const load = event.target.closest("[data-load]");
    if (load) {
      event.preventDefault();
      form.querySelector("[data-pick]").open = false;
      loadTemplate(load.dataset.load);
    }
  });

  // Palette items can be dropped between cards; clicking remains the touch/keyboard path.
  let paletteDrag = null;
  const dropMark = el("li", {class: "fb-drop-marker", "aria-hidden": "true"});
  for (const item of form.querySelectorAll("[data-palette] .fb-palette-item")) {
    item.draggable = true;
    item.addEventListener("dragstart", event => {
      paletteDrag = item;
      event.dataTransfer.effectAllowed = "copy";
      event.dataTransfer.setData("text/plain", item.dataset.type || item.dataset.template);
      dropMark.textContent = "Drop here to add " + item.querySelector("strong").textContent;
    });
    item.addEventListener("dragend", () => { paletteDrag = null; dropMark.remove(); });
  }
  canvasEl.addEventListener("dragover", event => {
    if (!paletteDrag) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    const next = [...canvasEl.querySelectorAll(".fb-card")].find(card => {
      const rect = card.getBoundingClientRect();
      return event.clientY < rect.top + rect.height / 2;
    });
    canvasEl.insertBefore(dropMark, next || null);
  });
  canvasEl.addEventListener("drop", event => {
    if (!paletteDrag) return;
    event.preventDefault();
    const next = dropMark.nextElementSibling;
    const target = next ? Number(next.dataset.index) : schema.length;
    const before = schema.length;
    const item = paletteDrag;
    paletteDrag = null; dropMark.remove();
    if (item.dataset.type) insertField(item.dataset.type);
    else appendTemplate(templatesById[item.dataset.template]);
    const added = schema.splice(before);
    schema.splice(target, 0, ...added);
    if (editing >= before) editing = target;
    save(); render();
    if (added.length) { announce(added.length + " field(s) added at the drop position."); focusCard(target); }
  });

  const search = form.querySelector("[data-palette-search]");
  // Show only the palette items whose label or hint contains the search text.
  function filterPalette() {
    const query = search.value.trim().toLowerCase();
    let shown = 0;
    for (const item of form.querySelectorAll("[data-palette] .fb-palette-item")) {
      const match = !query || item.dataset.search.toLowerCase().includes(query);
      item.hidden = !match;
      if (match) shown += 1;
    }
    for (const group of form.querySelectorAll("[data-palette] [data-group]")) {
      group.hidden = !Array.from(group.querySelectorAll(".fb-palette-item")).some((i) => !i.hidden);
    }
    form.querySelector("[data-palette-empty]").hidden = shown > 0;
  }
  search.addEventListener("input", filterPalette);
  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && !event.target.closest("input, textarea, select, [contenteditable]")) {
      event.preventDefault();
      mobilePanels.open = true;
      form.querySelector("#tab-components").click();
      search.focus();
    }
  });

  const addToggle = form.querySelector("[data-add-toggle]");
  const addMenu = form.querySelector("[data-add-menu]");
  // Hide the Add-a-field popover.
  function closeAddMenu() {
    addMenu.hidden = true;
    addToggle.setAttribute("aria-expanded", "false");
  }
  addToggle.addEventListener("click", () => {
    const open = addMenu.hidden;
    if (open) {
      const list = form.querySelector("[data-add-list]");
      list.replaceChildren();
      for (const group of form.querySelectorAll("[data-palette] [data-group]")) {
        const clone = group.cloneNode(true);
        for (const item of clone.querySelectorAll(".fb-palette-item")) item.hidden = false;
        clone.hidden = false;
        list.append(clone);
      }
      addMenu.hidden = false;
      addToggle.setAttribute("aria-expanded", "true");
      const first = addMenu.querySelector("button");
      if (first) first.focus();
    } else {
      closeAddMenu();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !event.defaultPrevented && !addMenu.hidden) {
      event.preventDefault(); // Keep the enclosing card open when dismissing the menu.
      closeAddMenu();
      addToggle.focus();
    }
  });
  document.addEventListener("click", (event) => {
    if (!addMenu.hidden && !event.target.closest("[data-add]")) closeAddMenu();
  });

  // --- grant settings, publish dialog, save state ------------------------------------

  for (const input of [deadlineInput, deadlineTimeInput]) {
    if (input) input.addEventListener("input", () => {
      if (schema.some((s) => s.type === "deadline")) renderCards();
    });
  }
  form.addEventListener("input", (event) => {
    if (event.target.closest("[data-palette-search]")) return;
    markDirty();
  });

  const publishButton = form.querySelector("[data-publish]");
  const publishDialog = document.getElementById("fb-publish-dialog");
  if (publishButton && publishDialog && typeof publishDialog.showModal === "function") {
    publishButton.addEventListener("click", (event) => {
      event.preventDefault();
      publishDialog.showModal();
    });
    publishDialog.querySelector("[data-dialog-close]").addEventListener("click", () => publishDialog.close());
  }

  // Preview as applicant: POST the form to ?action=preview&embed=1 and show the page in
  // the full-screen dialog's iframe. Escape (the dialog's own, or the iframe's message),
  // "Back to editing" and "Publish grant" close it; closing empties the iframe. Without
  // fetch or <dialog> the button submits as usual and the preview opens in a new tab.
  const previewButton = form.querySelector("[data-preview]");
  const previewDialog = document.getElementById("fb-preview-dialog");
  const previewFrame = previewDialog ? previewDialog.querySelector("[data-preview-frame]") : null;
  function closePreview() {
    if (!previewDialog || !previewDialog.open) return;
    previewDialog.close();
    previewFrame.removeAttribute("srcdoc");
    if (previewButton) previewButton.focus();
  }
  if (previewButton && previewDialog && typeof previewDialog.showModal === "function" && window.fetch) {
    previewButton.addEventListener("click", (event) => {
      event.preventDefault();
      const url = new URL(previewButton.getAttribute("formaction"), window.location.href);
      url.searchParams.set("embed", "1");
      previewButton.disabled = true;
      fetch(url, { method: "POST", body: new FormData(form), credentials: "same-origin" })
        .then((response) => response.text().then((text) => ({ ok: response.ok, text })))
        .then(({ ok, text }) => {
          if (!ok) {
            const message = new DOMParser().parseFromString(text, "text/html").body.textContent.trim();
            announce(message);
            window.alert(message);
            return;
          }
          previewFrame.srcdoc = text;
          previewDialog.showModal();
          previewFrame.focus();
        })
        .catch(() => window.alert("The preview could not be loaded. Try again."))
        .finally(() => { previewButton.disabled = false; });
    });
    previewDialog.querySelector("[data-preview-close]").addEventListener("click", closePreview);
    previewDialog.querySelector("[data-preview-publish]").addEventListener("click", () => {
      closePreview();
      if (publishButton) publishButton.click();
    });
    previewDialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      closePreview();
    });
    // The preview page says Escape was pressed inside it. Only its own window is heard,
    // whatever origin the iframe reports (about:srcdoc has none of its own).
    window.addEventListener("message", (event) => {
      if (event.data === "it42-preview-close" && event.source === previewFrame.contentWindow) closePreview();
    });
  }

  form.addEventListener("submit", () => {
    submitting = true;
  });
  // Both page navigation and closing an embedded editor must protect unsaved work.
  function guardUnsaved(event) {
    if (dirty && !submitting) {
      event.preventDefault();
      if (event.type === "beforeunload") event.returnValue = "";
    }
  }
  window.addEventListener("beforeunload", guardUnsaved);
  document.addEventListener("it42-card-dismiss", guardUnsaved);
  // The preview opens in a new tab: the page stays, so allow leaving again afterwards.
  window.addEventListener("pageshow", () => { submitting = false; });
  window.addEventListener("focus", () => { submitting = false; });

  // --- glue -------------------------------------------------------------------

  // Make a loaded entry safe to draw: string name and label, a known type, layout never required.
  function normalise(spec) {
    if (typeof spec.name !== "string") spec.name = "";
    if (typeof spec.label !== "string") spec.label = "";
    if (!widgetsByType[spec.type]) spec.type = "text";
    if (isLayout(spec)) spec.required = false;
  }

  // Draw everything from the current schema.
  function render() {
    renderLocked();
    renderCards();
    renderPick();
    renderSummary();
  }

  // Parse the textarea into the schema and derive every name (also what the server does).
  function load(text) {
    schema = parse(text);
    for (const spec of schema) normalise(spec);
    assignNames();
    editing = -1;
  }

  textarea.addEventListener("change", () => {
    try {
      load(textarea.value.trim() || "[]");
      save();
      render();
    } catch (error) {
      jsonError.textContent = "Not valid JSON: " + error.message;
      jsonError.classList.add("d-block");
      textarea.classList.add("is-invalid");
    }
  });

  try {
    load(textarea.value.trim() || "[]");
    builder.hidden = false;
    form.classList.add("is-ready");
    save(false);
    render();
    const settingsTab = form.querySelector("#tab-settings[data-open]");
    if (settingsTab) { mobilePanels.open = true; settingsTab.click(); }
  } catch (error) {
    // Leave the JSON editor visible when the saved schema cannot be parsed.
    document.getElementById("form-schema-json").open = true;
  }
})();
