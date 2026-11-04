/* Type-to-search for long <select> lists (select[data-combobox], e.g. the administrating
 * organisation on the apply form).
 *
 * The <select> stays in the form and keeps the value the server validates; this script
 * hides it and shows a text box with a filtered list (ARIA 1.2 combobox pattern: arrow
 * keys move, Enter picks, Escape closes). Without JavaScript the plain select works.
 */
(function () {
  "use strict";

  let counter = 0;

  function enhance(select) {
    const id = "cb-" + ++counter;
    const options = Array.from(select.options).filter((o) => o.value !== "");
    const emptyOption = Array.from(select.options).find((o) => o.value === "");
    const wrap = document.createElement("div");
    wrap.className = "it-combobox";
    const input = document.createElement("input");
    input.type = "text";
    input.className = select.className.replace("form-select", "form-control");
    input.id = select.id;
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-controls", id + "-list");
    input.setAttribute("autocomplete", "off");
    input.placeholder = "Type to search";
    if (select.getAttribute("aria-describedby")) {
      input.setAttribute("aria-describedby", select.getAttribute("aria-describedby"));
    }
    const list = document.createElement("ul");
    list.className = "it-combobox-list";
    list.id = id + "-list";
    list.setAttribute("role", "listbox");
    list.hidden = true;

    // The label points at the visible input; the select keeps its name only. A hidden
    // required control cannot show the browser's message, so the input takes it over.
    const required = select.required;
    input.required = required;
    select.required = false;
    select.id = id + "-select";
    select.hidden = true;
    select.tabIndex = -1;
    select.after(wrap);
    wrap.append(input, list, select);

    let active = -1;
    let shown = [];

    function current() {
      const option = select.selectedOptions[0];
      return option && option.value ? option.text : "";
    }

    function close() {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      active = -1;
    }

    function pick(option) {
      select.value = option ? option.value : "";
      input.value = option ? option.text : "";
      select.dispatchEvent(new Event("change", { bubbles: true }));
      close();
    }

    function highlight(index) {
      active = index;
      shown.forEach((item, i) => item.setAttribute("aria-selected", i === index ? "true" : "false"));
      if (index >= 0 && shown[index]) {
        input.setAttribute("aria-activedescendant", shown[index].id);
        shown[index].scrollIntoView({ block: "nearest" });
      }
    }

    function render() {
      const query = input.value.trim().toLowerCase();
      list.replaceChildren();
      shown = [];
      const matches = options.filter((o) => o.text.toLowerCase().includes(query));
      if (emptyOption && !required && !query) {
        matches.unshift(emptyOption);
      }
      matches.forEach((option, i) => {
        const item = document.createElement("li");
        item.id = id + "-opt-" + i;
        item.setAttribute("role", "option");
        item.textContent = option.value ? option.text : "None";
        item.addEventListener("mousedown", (event) => {
          event.preventDefault();
          pick(option.value ? option : null);
        });
        list.append(item);
        shown.push(item);
      });
      if (!matches.length) {
        const item = document.createElement("li");
        item.className = "it-combobox-empty";
        item.textContent = "No organisation matches";
        list.append(item);
      }
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      highlight(matches.length ? 0 : -1);
      shown.matches = matches;
    }

    input.value = current();
    input.addEventListener("focus", render);
    input.addEventListener("input", () => {
      if (!input.value.trim()) select.value = "";
      render();
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (list.hidden) return render();
        const step = event.key === "ArrowDown" ? 1 : -1;
        highlight(Math.max(0, Math.min(shown.length - 1, active + step)));
      } else if (event.key === "Enter" && !list.hidden && active >= 0) {
        event.preventDefault();
        const option = shown.matches[active];
        pick(option.value ? option : null);
      } else if (event.key === "Escape") {
        input.value = current();
        close();
      }
    });
    input.addEventListener("blur", () => {
      // Leaving the box with half-typed text keeps the last valid choice.
      input.value = current();
      close();
    });
  }

  document.querySelectorAll("select[data-combobox]").forEach(enhance);
})();
