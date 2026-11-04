// ORCID import loader: polls the import's status URL (data-orcid-import) and moves the
// progress bar, stage text and percentage. When the runner has staged the record (or the
// import stopped) the page reloads and the server shows the review or the error.
(function () {
  "use strict";
  var dialog = document.querySelector("[data-orcid-import]");
  if (!dialog) return;
  var url = dialog.dataset.orcidImport;
  var bar = dialog.querySelector("[data-bar]");
  var track = dialog.querySelector("[data-progressbar]");
  var stage = dialog.querySelector("[data-stage]");
  var percent = dialog.querySelector("[data-percent]");
  var failures = 0;

  function show(data) {
    bar.style.width = data.progress + "%";
    track.setAttribute("aria-valuenow", data.progress);
    percent.textContent = data.progress + "%";
    if (stage.textContent !== data.stage) stage.textContent = data.stage;
  }

  function poll() {
    fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (data) {
        failures = 0;
        show(data);
        if (data.status === "queued" || data.status === "running") {
          setTimeout(poll, 700);
        } else {
          // Let the bar reach its end before the review replaces the loader.
          setTimeout(function () { location.reload(); }, data.status === "review" ? 500 : 0);
        }
      })
      .catch(function () {
        failures += 1;
        setTimeout(failures > 5 ? function () { location.reload(); } : poll, 1500);
      });
  }
  setTimeout(poll, 400);
})();
