"use strict";

// Runs inside the active tab to extract the job offer's metadata.
// Prefers a schema.org JobPosting (JSON-LD), falls back to Open Graph / title.
function extractFromPage() {
  function meta(prop) {
    var el = document.querySelector(
      'meta[property="' + prop + '"], meta[name="' + prop + '"]'
    );
    return el ? (el.getAttribute("content") || "") : "";
  }

  var entreprise = "";
  var poste = "";

  var scripts = document.querySelectorAll('script[type="application/ld+json"]');
  for (var i = 0; i < scripts.length; i++) {
    try {
      var parsed = JSON.parse(scripts[i].textContent);
      var nodes = Array.isArray(parsed) ? parsed : [parsed];
      if (parsed && parsed["@graph"]) nodes = nodes.concat(parsed["@graph"]);
      for (var j = 0; j < nodes.length; j++) {
        var node = nodes[j];
        if (!node) continue;
        var type = node["@type"];
        var isJob = type === "JobPosting" ||
          (Array.isArray(type) && type.indexOf("JobPosting") >= 0);
        if (isJob) {
          if (!poste && node.title) poste = String(node.title);
          if (!entreprise && node.hiringOrganization && node.hiringOrganization.name) {
            entreprise = String(node.hiringOrganization.name);
          }
        }
      }
    } catch (e) { /* ignore malformed JSON-LD */ }
  }

  if (!poste) poste = meta("og:title") || document.title || "";
  if (!entreprise) entreprise = meta("og:site_name") || "";

  return { url: location.href, entreprise: entreprise.trim(), poste: poste.trim() };
}

function sourceFromUrl(url) {
  var host;
  try { host = new URL(url).hostname; } catch (e) { return "autre"; }
  if (host.indexOf("linkedin") >= 0) return "linkedin";
  if (host.indexOf("indeed") >= 0) return "indeed";
  if (host.indexOf("monster") >= 0) return "monster";
  if (host.indexOf("cadremploi") >= 0) return "cadremploi";
  if (host.indexOf("apec") >= 0) return "apec";
  if (host.indexOf("francetravail") >= 0 || host.indexOf("pole-emploi") >= 0) return "france_travail";
  return "autre";
}

function setStatus(message, kind) {
  var el = document.getElementById("status");
  el.textContent = "";
  el.className = "status" + (kind ? " " + kind : "");
  if (kind === "ok" && message && message.link) {
    el.appendChild(document.createTextNode("Ajouté ✓ "));
    var a = document.createElement("a");
    a.href = message.link; a.target = "_blank"; a.textContent = "voir";
    el.appendChild(a);
  } else {
    el.textContent = message;
  }
}

function getConfig() {
  return new Promise(function (resolve) {
    chrome.storage.sync.get({ baseUrl: "http://127.0.0.1:8000", token: "" }, resolve);
  });
}

var current = { url: "", source: "autre" };

document.addEventListener("DOMContentLoaded", function () {
  // Pre-fill from the active tab.
  chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
    var tab = tabs[0];
    if (!tab) return;
    current.url = tab.url || "";
    current.source = sourceFromUrl(current.url);
    document.getElementById("source").textContent = current.source;
    document.getElementById("url").value = current.url;
    chrome.scripting.executeScript(
      { target: { tabId: tab.id }, func: extractFromPage },
      function (results) {
        if (chrome.runtime.lastError || !results || !results[0]) return;
        var data = results[0].result || {};
        if (data.entreprise) document.getElementById("entreprise").value = data.entreprise;
        if (data.poste) document.getElementById("poste").value = data.poste;
        if (data.url) document.getElementById("url").value = data.url;
      }
    );
  });

  document.getElementById("add").addEventListener("click", function () {
    var btn = this;
    getConfig().then(function (cfg) {
      if (!cfg.token) {
        setStatus("Configurez l'URL et le jeton dans les options de l'extension.", "err");
        return;
      }
      var payload = {
        url: document.getElementById("url").value.trim(),
        entreprise: document.getElementById("entreprise").value.trim(),
        poste: document.getElementById("poste").value.trim(),
        source: current.source
      };
      btn.disabled = true;
      setStatus("Envoi…", null);
      fetch(cfg.baseUrl.replace(/\/+$/, "") + "/api/candidatures/", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Api-Token": cfg.token },
        body: JSON.stringify(payload)
      }).then(function (r) {
        return r.json().then(function (body) { return { ok: r.ok, body: body }; });
      }).then(function (res) {
        if (res.ok) {
          setStatus({ link: res.body.url }, "ok");
        } else {
          setStatus("Erreur : " + (res.body.error || "envoi impossible"), "err");
          btn.disabled = false;
        }
      }).catch(function (e) {
        setStatus("Erreur réseau : " + e.message, "err");
        btn.disabled = false;
      });
    });
  });
});
