"use strict";

var DEFAULTS = { baseUrl: "http://127.0.0.1:8000", token: "" };

document.addEventListener("DOMContentLoaded", function () {
  chrome.storage.sync.get(DEFAULTS, function (cfg) {
    document.getElementById("baseUrl").value = cfg.baseUrl;
    document.getElementById("token").value = cfg.token;
  });

  document.getElementById("save").addEventListener("click", function () {
    var baseUrl = document.getElementById("baseUrl").value.trim() || DEFAULTS.baseUrl;
    var token = document.getElementById("token").value.trim();
    chrome.storage.sync.set({ baseUrl: baseUrl, token: token }, function () {
      var el = document.getElementById("saved");
      el.textContent = "Enregistré ✓";
      setTimeout(function () { el.textContent = ""; }, 2000);
    });
  });
});
