/* Exchange a fragment-only launcher token for a session cookie. */
(function () {
  "use strict";
  var token = window.location.hash.slice(1);
  var message = document.getElementById("bootstrap-status");
  if (!token) {
    message.textContent = "This launch link has expired. Start the dashboard again.";
    return;
  }

  fetch("/_auth/bootstrap", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: token })
  }).then(function (response) {
    if (!response.ok) throw new Error("bootstrap rejected");
    window.location.replace("/");
  }).catch(function () {
    message.textContent = "This launch link has expired. Start the dashboard again.";
  });
}());
