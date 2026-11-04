/* Drag-and-drop grant form builder.
 *
 * Edits the JSON in the form_schema textarea (the field the server validates). Widgets
 * come from the server (WIDGETS in it42.common.formschema, passed through json_script),
 * the base fields are locked (only the administrating organisation's Required box stays
 * editable, see config.optional), and widgets with palette: false are not offered. Field names are never typed: they are derived from the
 * labels (same rules as formschema.assign_names, which the server applies again on save).
 * Everything also works with the keyboard: Add buttons on the palette, Up/Down/Remove
 * buttons on each row. Plain JavaScript, no dependencies.
 */
(function () {
  "use strict";

  const root = document.getElementById("form-builder");
  if (!root) return;
  const config = JSON.parse(document.getElementById(root.dataset.config).textContent);
  const textarea = document.getElementById(root.dataset.target);
  const paletteEl = root.querySelector("[data-palette]");
  const canvasEl = root.querySelector("[data-canvas]");
  const propsEl = root.querySelector("[data-props]");
  const countEl = root.querySelector("[data-count]");
  const announceEl = root.querySelector("[data-announce]");
  const jsonError = document.querySelector("[data-json-error]");
  const widgetsByType = Object.fromEntries(config.widgets.map((w) => [w.type, w]));
  const locked = new Set(config.locked);
  const optional = new Set(config.optional || []);
  const reserved = new Set(["documents", "csrfmiddlewaretoken"]);

  let schema = [];
  let selected = -1;
  let dropIndex = -1;

  // --- helpers ----------------------------------------------------------------

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (value === true) node.setAttribute(key, "");
      else if (value !== false && value != null) node.setAttribute(key, value);
    }
    for (const child of children || []) {
      if (child != null) node.append(child);
    }
    return node;
  }

  function isLayout(spec) {
    return spec.type === "heading" || spec.type === "paragraph";
  }

  function isLocked(spec) {
    return locked.has(spec.name);
  }

  // Mirrors formschema.field_name: ASCII lowercase letters, digits and underscores.
  function fieldName(label) {
    let name = String(label || "")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
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

  function announce(text) {
    announceEl.textContent = text;
  }

  function parse(text) {
    const value = JSON.parse(text);
    if (!Array.isArray(value)) throw new Error("The schema must be a list.");
    return value.map((raw) => (raw && typeof raw === "object" ? raw : {}));
  }

  function save() {
    assignNames();
    textarea.value = JSON.stringify(schema, null, 2);
    jsonError.textContent = "";
    jsonError.classList.remove("d-block");
    textarea.classList.remove("is-invalid");
  }

  // --- palette ----------------------------------------------------------------

  function newField(type) {
    const widget = widgetsByType[type];
    const spec = { name: "", label: widget.label, type: type, required: false };
    if (type === "heading") spec.label = "Section";
    if (type === "paragraph") spec.label = "Explain what this section is about.";
    if (widget.keys.includes("options")) spec.options = ["Option 1", "Option 2"];
    return spec;
  }

  function insertField(type, index) {
    if (schema.length >= config.max_fields) {
      announce("The form already has the maximum number of fields.");
      return;
    }
    const spec = newField(type);
    if (index < 0 || index > schema.length) index = schema.length;
    schema.splice(index, 0, spec);
    selected = index;
    announce(widgetsByType[type].label + " added at position " + (index + 1) + ".");
    render();
    focusRow(index);
  }

  function renderPalette() {
    paletteEl.replaceChildren();
    const groups = new Map();
    for (const widget of config.widgets) {
      if (widget.palette === false) continue;
      if (!groups.has(widget.group)) groups.set(widget.group, []);
      groups.get(widget.group).push(widget);
    }
    const full = schema.length >= config.max_fields;
    for (const [group, widgets] of groups) {
      const section = el("div", { class: "fb-palette-group" }, [el("h3", { text: group })]);
      for (const widget of widgets) {
        const card = el(
          "div",
          {
            class: "fb-widget",
            draggable: full ? null : "true",
            "aria-disabled": full ? "true" : null,
            "data-type": widget.type,
            ondragstart: (event) => {
              if (full) return event.preventDefault();
              event.dataTransfer.setData("text/plain", "new:" + widget.type);
              event.dataTransfer.effectAllowed = "copy";
            },
          },
          [
            el("span", { text: widget.label }),
            el("button", {
              type: "button",
              class: "btn btn-sm btn-outline-primary py-0",
              "aria-label": "Add " + widget.label,
              disabled: full,
              text: "Add",
              onclick: () => insertField(widget.type, selected >= 0 ? selected + 1 : -1),
            }),
          ]
        );
        section.append(card);
      }
      paletteEl.append(section);
    }
  }

  // --- canvas -----------------------------------------------------------------

  function preview(spec) {
    const attrs = { class: "form-control form-control-sm", disabled: true, tabindex: -1 };
    if (spec.placeholder) attrs.placeholder = spec.placeholder;
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
        return el(
          "select",
          { class: "form-select form-select-sm", disabled: true, tabindex: -1 },
          (spec.options || []).map((o) => el("option", { text: o }))
        );
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
        if (options.length > 5) {
          nodes.push(el("div", { class: "small text-body-secondary", text: "+" + (options.length - 5) + " more" }));
        }
        return el("div", {}, nodes);
      }
      case "checkbox":
        return el("div", { class: "form-check" }, [
          el("input", { class: "form-check-input", type: "checkbox", disabled: true, tabindex: -1 }),
          el("label", { class: "form-check-label", text: spec.label }),
        ]);
      case "research_org":
        return el("select", { class: "form-select form-select-sm", disabled: true, tabindex: -1 }, [
          el("option", { text: "Choose an organisation" }),
        ]);
      case "heading":
        return el("h5", { text: spec.label });
      case "paragraph":
        return el("p", { text: spec.label });
      default:
        return el("input", { ...attrs, type: "text" });
    }
  }

  function moveField(from, to) {
    if (to < 0 || to >= schema.length || from === to) return;
    const [spec] = schema.splice(from, 1);
    schema.splice(to, 0, spec);
    selected = to;
    announce(spec.label + " moved to position " + (to + 1) + ".");
    render();
    focusRow(to);
  }

  function removeField(index) {
    const spec = schema[index];
    if (isLocked(spec)) return;
    schema.splice(index, 1);
    selected = Math.min(index, schema.length - 1);
    announce(spec.label + " removed.");
    render();
    if (selected >= 0) focusRow(selected);
  }

  function focusRow(index) {
    const row = canvasEl.querySelector('[data-index="' + index + '"]');
    if (row) row.focus();
  }

  function rowActions(spec, index) {
    const button = (label, text, onclick, disabled) =>
      el("button", {
        type: "button",
        class: "btn btn-sm btn-outline-secondary",
        "aria-label": label + " " + spec.label,
        title: label,
        disabled: !!disabled,
        text: text,
        onclick: (event) => {
          event.stopPropagation();
          onclick();
        },
      });
    return el("div", { class: "fb-row-actions" }, [
      button("Move up", "↑", () => moveField(index, index - 1), index === 0),
      button("Move down", "↓", () => moveField(index, index + 1), index === schema.length - 1),
      button("Remove", "×", () => removeField(index), isLocked(spec)),
    ]);
  }

  function renderCanvas() {
    canvasEl.replaceChildren();
    countEl.textContent = schema.length + " of " + config.max_fields + " fields";
    if (!schema.length) {
      canvasEl.append(el("li", { class: "fb-empty", text: "Drop widgets here to build the form." }));
      return;
    }
    schema.forEach((spec, index) => {
      const widget = widgetsByType[spec.type] || { label: spec.type };
      const row = el(
        "li",
        {
          class: "fb-row" + (index === selected ? " fb-selected" : ""),
          draggable: "true",
          tabindex: 0,
          role: "button",
          "aria-pressed": index === selected ? "true" : "false",
          "aria-label": widget.label + ": " + spec.label + (isLocked(spec) ? " (always included)" : ""),
          "data-index": index,
          onclick: () => select(index),
          onkeydown: (event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              select(index);
            } else if (event.altKey && event.key === "ArrowUp") {
              event.preventDefault();
              moveField(index, index - 1);
            } else if (event.altKey && event.key === "ArrowDown") {
              event.preventDefault();
              moveField(index, index + 1);
            } else if (event.key === "Delete" && !isLocked(spec)) {
              event.preventDefault();
              removeField(index);
            }
          },
          ondragstart: (event) => {
            event.dataTransfer.setData("text/plain", "move:" + index);
            event.dataTransfer.effectAllowed = "move";
            row.classList.add("fb-dragging");
          },
          ondragend: () => {
            row.classList.remove("fb-dragging");
            clearDropMarks();
          },
        },
        [
          el("div", { class: "fb-grip", "aria-hidden": "true", text: "☰" }),
          el("div", { class: "fb-row-main" }, [
            el("div", { class: "d-flex flex-wrap align-items-center gap-1" }, [
              isLayout(spec) ? null : el("span", { class: "fb-row-label", text: spec.label }),
              isLayout(spec) || !spec.required ? null : el("span", { class: "text-danger", "aria-hidden": "true", text: "*" }),
              el("span", { class: "badge text-bg-light border fb-row-type", text: widget.label }),
              isLocked(spec) ? el("span", { class: "badge text-bg-secondary fb-locked", text: "always included" }) : null,
            ]),
            el("div", { class: "fb-preview" }, [preview(spec)]),
            spec.help_text ? el("div", { class: "fb-row-help", text: spec.help_text }) : null,
          ]),
          rowActions(spec, index),
        ]
      );
      canvasEl.append(row);
    });
  }

  function select(index) {
    selected = index;
    render();
    const first = propsEl.querySelector("input, select, textarea");
    if (first) first.focus();
  }

  // Drag and drop onto the canvas: a palette card inserts, a row reorders.
  function clearDropMarks() {
    canvasEl.classList.remove("fb-over", "fb-drop-end");
    for (const row of canvasEl.querySelectorAll(".fb-drop-before, .fb-drop-after")) {
      row.classList.remove("fb-drop-before", "fb-drop-after");
    }
  }

  canvasEl.addEventListener("dragover", (event) => {
    event.preventDefault();
    const types = event.dataTransfer.types;
    if (!types || !Array.from(types).includes("text/plain")) return;
    clearDropMarks();
    canvasEl.classList.add("fb-over");
    const row = event.target.closest ? event.target.closest(".fb-row") : null;
    if (row && canvasEl.contains(row)) {
      const rect = row.getBoundingClientRect();
      const index = Number(row.dataset.index);
      if (event.clientY < rect.top + rect.height / 2) {
        dropIndex = index;
        row.classList.add("fb-drop-before");
      } else {
        dropIndex = index + 1;
        row.classList.add("fb-drop-after");
      }
    } else {
      dropIndex = schema.length;
      canvasEl.classList.add("fb-drop-end");
    }
  });

  canvasEl.addEventListener("dragleave", (event) => {
    if (!canvasEl.contains(event.relatedTarget)) clearDropMarks();
  });

  canvasEl.addEventListener("drop", (event) => {
    event.preventDefault();
    const data = event.dataTransfer.getData("text/plain") || "";
    const target = dropIndex < 0 ? schema.length : dropIndex;
    clearDropMarks();
    if (data.startsWith("new:")) {
      const type = data.slice(4);
      if (widgetsByType[type]) insertField(type, target);
    } else if (data.startsWith("move:")) {
      const from = Number(data.slice(5));
      if (Number.isInteger(from) && from >= 0 && from < schema.length) {
        moveField(from, target > from ? target - 1 : target);
      }
    }
    dropIndex = -1;
  });

  // --- properties -------------------------------------------------------------

  function propInput(id, label, control, hint) {
    return el("div", { class: "mb-2" }, [
      el("label", { for: id, class: "form-label", text: label }),
      control,
      hint ? el("div", { class: "form-text", text: hint }) : null,
    ]);
  }

  function renderProps() {
    propsEl.replaceChildren();
    const spec = schema[selected];
    if (!spec) {
      propsEl.append(el("p", { class: "small text-body-secondary mb-0", text: "Select a field on the form to edit it." }));
      return;
    }
    const widget = widgetsByType[spec.type] || { keys: [] };
    const lockedField = isLocked(spec);
    const layout = isLayout(spec);
    const update = (key, value) => {
      if (value === "" || value == null) delete spec[key];
      else spec[key] = value;
      renderCanvas();
      save();
    };
    const text = (key, label, hint, opts) =>
      propInput(
        "fb-prop-" + key,
        label,
        el(opts && opts.multiline ? "textarea" : "input", {
          id: "fb-prop-" + key,
          class: "form-control form-control-sm",
          type: opts && opts.multiline ? null : opts && opts.type ? opts.type : "text",
          rows: opts && opts.multiline ? 3 : null,
          value: opts && opts.multiline ? null : spec[key] == null ? "" : spec[key],
          text: opts && opts.multiline ? (spec[key] == null ? "" : spec[key]) : null,
          disabled: !!(opts && opts.disabled),
          oninput: (event) => {
            let value = event.target.value;
            if (opts && opts.number) {
              value = value.trim() === "" ? "" : Number(value);
              if (Number.isNaN(value)) return;
              if (opts.integer && !Number.isInteger(value)) return;
            }
            opts && opts.onchange ? opts.onchange(value) : update(key, value);
          },
        }),
        hint
      );

    const nameNote = el("div", { class: "form-text", "data-name": true });
    const showName = () => {
      nameNote.textContent = "Stored as " + spec.name + (lockedField ? " (fixed)" : ", derived from the label");
    };
    propsEl.append(
      text("label", layout ? (spec.type === "heading" ? "Heading" : "Text") : "Label", null, {
        multiline: spec.type === "paragraph",
        onchange: (value) => {
          spec.label = value;
          renderCanvas();
          save();
          showName();
        },
      })
    );
    showName();
    propsEl.append(nameNote);
    const typeSelect = el(
      "select",
      {
        id: "fb-prop-type",
        class: "form-select form-select-sm",
        disabled: lockedField,
        onchange: (event) => {
          const next = widgetsByType[event.target.value];
          spec.type = next.type;
          for (const key of Object.keys(spec)) {
            if (!["name", "label", "type", "required", "help_text"].includes(key) && !next.keys.includes(key)) {
              delete spec[key];
            }
          }
          if (next.keys.includes("options") && !spec.options) spec.options = ["Option 1", "Option 2"];
          if (isLayout(spec)) spec.required = false;
          render();
        },
      },
      config.widgets
        .filter((w) => w.palette !== false || w.type === spec.type)
        .map((w) => el("option", { value: w.type, selected: w.type === spec.type, text: w.label }))
    );
    propsEl.append(propInput("fb-prop-type", "Type", typeSelect));
    if (!layout) {
      propsEl.append(
        el("div", { class: "form-check mb-2" }, [
          el("input", {
            id: "fb-prop-required",
            class: "form-check-input",
            type: "checkbox",
            checked: !!spec.required,
            disabled: lockedField && !optional.has(spec.name),
            onchange: (event) => {
              spec.required = event.target.checked;
              renderCanvas();
              save();
            },
          }),
          el("label", { for: "fb-prop-required", class: "form-check-label", text: "Required" }),
        ])
      );
      propsEl.append(text("help_text", "Help text", "Shown under the field."));
    }
    if (widget.keys.includes("placeholder")) propsEl.append(text("placeholder", "Placeholder"));
    if (widget.keys.includes("max_length")) {
      propsEl.append(text("max_length", "Maximum length", null, { type: "number", number: true, integer: true }));
    }
    if (widget.keys.includes("rows")) {
      propsEl.append(text("rows", "Rows", "Height of the text box (2-20).", { type: "number", number: true, integer: true }));
    }
    if (widget.keys.includes("min")) {
      propsEl.append(text("min", "Minimum", null, { type: "number", number: true, integer: spec.type === "integer" }));
      propsEl.append(text("max", "Maximum", null, { type: "number", number: true, integer: spec.type === "integer" }));
    }
    if (widget.keys.includes("options")) {
      propsEl.append(
        propInput(
          "fb-prop-options",
          "Options",
          el("textarea", {
            id: "fb-prop-options",
            class: "form-control form-control-sm",
            rows: 5,
            text: (spec.options || []).join("\n"),
            oninput: (event) => {
              spec.options = event.target.value.split("\n").map((o) => o.trim()).filter(Boolean);
              renderCanvas();
              save();
            },
          }),
          "One option per line, at most " + config.max_options + "."
        )
      );
    }
  }

  // Pressing Enter in a settings box must not submit the grant form.
  propsEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target.tagName !== "TEXTAREA") event.preventDefault();
  });

  // --- glue -------------------------------------------------------------------

  function render() {
    renderPalette();
    renderCanvas();
    renderProps();
    save();
  }

  function load(text) {
    schema = parse(text);
    for (const spec of schema) {
      if (typeof spec.name !== "string") spec.name = "";
      if (typeof spec.label !== "string") spec.label = "";
      if (!widgetsByType[spec.type]) spec.type = "text";
    }
    assignNames();
    selected = -1;
  }

  textarea.addEventListener("change", () => {
    try {
      load(textarea.value.trim() || "[]");
      render();
    } catch (error) {
      jsonError.textContent = "Not valid JSON: " + error.message;
      jsonError.classList.add("d-block");
      textarea.classList.add("is-invalid");
    }
  });

  try {
    load(textarea.value.trim() || "[]");
    root.hidden = false;
    render();
  } catch (error) {
    // Leave the JSON editor visible when the saved schema cannot be parsed.
    document.getElementById("form-schema-json").open = true;
  }
})();
