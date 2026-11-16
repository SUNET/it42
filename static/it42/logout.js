// A login in another tab rotates Django's CSRF cookie. Refresh only the logout
// form's token at submission so an older open page can still end the session.
(function () {
  "use strict";
  const script = document.currentScript;
  const logoutUrl = new URL(script.dataset.logoutUrl, window.location.href);
  document.querySelectorAll("form").forEach(function (form) {
    if (form.method.toLowerCase() !== "post" || form.action !== logoutUrl.href) return;
    form.addEventListener("submit", function () {
      const field = form.elements.namedItem("csrfmiddlewaretoken");
      if (!field) return;
      const cookie = document.cookie.split(";").map(function (part) {
        return part.trim();
      }).find(function (part) {
        return part.startsWith("csrftoken=");
      });
      if (cookie) field.value = cookie.slice("csrftoken=".length);
      // Missing/invalid cookies still fail Django's normal CSRF validation.
    });
  });
})();
