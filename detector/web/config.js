// ALIBI GUI configuration. Edit ALIBI_API to point the console at another ALIBI service.
// Local (python -m detector serve on :8600): the API runs on :8601.
// Elsewhere (e.g. https://helppox.com/alibi/): the API sits next to the page at ./api/v1.
(function () {
  if (window.ALIBI_API) return;
  var h = location.hostname;
  var local = location.protocol === "file:" || h === "localhost" || h === "127.0.0.1" || h === "[::1]" || h === "::1" || h === "";
  window.ALIBI_API = local ? "http://127.0.0.1:8601/api/v1" : new URL("api/v1", location.href).href;
  // Optional: sources switched on when a case loads (null = every source the API lists).
  window.ALIBI_DEFAULT_SOURCES = window.ALIBI_DEFAULT_SOURCES || null;
})();
