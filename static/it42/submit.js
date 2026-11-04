// "Submit your application" dialog on the apply page. The infobar's Submit button opens
// it with a checklist of the form; its own checkbox stands in for the form's `confirm`
// box. Without JavaScript (or <dialog>) the inline confirm box and button still work.
(function () {
  "use strict";
  var dialog = document.getElementById("submit-dialog");
  if (!dialog || typeof dialog.showModal !== "function") return;
  var form = dialog.closest("form");
  var confirmBox = form.querySelector("#confirm");
  var dialogBox = dialog.querySelector("#confirm-dialog");
  var send = dialog.querySelector("[data-submit-confirm]");
  form.classList.add("js-submit-dialog");

  function filled(field) {
    if (field.type === "checkbox" || field.type === "radio") {
      return Array.prototype.some.call(form.querySelectorAll('[name="' + field.name + '"]'), function (f) { return f.checked; });
    }
    return field.value.trim() !== "";
  }

  function check(name, ok, text) {
    var row = dialog.querySelector('[data-check="' + name + '"]');
    row.classList.toggle("is-missing", !ok);
    row.querySelector("small").textContent = text;
  }

  function update() {
    var seen = {};
    var required = Array.prototype.filter.call(form.querySelectorAll("[required]"), function (f) {
      if (f === confirmBox || f.closest("dialog") || seen[f.name]) return false;
      seen[f.name] = true;
      return true;
    });
    var done = required.filter(filled).length;
    check("required", done === required.length, done + " of " + required.length);
    var docs = form.querySelectorAll('input[name="documents"]:checked').length;
    check("documents", true, docs ? docs + " file" + (docs === 1 ? "" : "s") : "None");
    var org = form.querySelector('[name="administrating_organisation"]');
    var orgName = "";
    if (org && org.value) {
      var option = org.tagName === "SELECT" ? org.options[org.selectedIndex] : null;
      orgName = option ? option.text : org.value;
    }
    check("organisation", true, orgName ? orgName + " signs after you submit" : "None named");
  }

  form.querySelector("[data-submit-open]").addEventListener("click", function (event) {
    event.preventDefault();
    update();
    dialogBox.checked = false;
    send.disabled = true;
    dialog.showModal();
  });
  dialogBox.addEventListener("change", function () {
    send.disabled = !dialogBox.checked;
    confirmBox.checked = dialogBox.checked;
  });
  dialog.querySelector("[data-submit-close]").addEventListener("click", function () { dialog.close(); });
  dialog.addEventListener("close", function () { confirmBox.checked = false; });
})();
