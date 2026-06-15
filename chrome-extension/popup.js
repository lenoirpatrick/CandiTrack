"use strict";

// Runs inside the active tab to extract the recruiting company name (issue #9).
// The plugin deliberately does NOT capture the job title nor a send date:
// those are filled in later, in CandiTrack.
// Strategy: schema.org JobPosting (JSON-LD) → site-specific DOM → Open Graph.
function extractFromPage() {
  function meta(prop) {
    var el = document.querySelector(
      'meta[property="' + prop + '"], meta[name="' + prop + '"]'
    );
    return el ? (el.getAttribute("content") || "") : "";
  }
  function text(sel) {
    var el = document.querySelector(sel);
    return el ? (el.textContent || "").trim() : "";
  }

  // Compose a readable location string from a schema.org PostalAddress (issue #52).
  function formatAddress(addr) {
    if (!addr) return "";
    if (typeof addr === "string") return addr;
    if (Array.isArray(addr)) return formatAddress(addr[0]);
    if (addr["@type"] === "Place" && addr.address) return formatAddress(addr.address);
    var parts = [addr.streetAddress, addr.postalCode, addr.addressLocality,
      addr.addressRegion, addr.addressCountry];
    return parts
      .map(function (p) { return p && typeof p === "object" ? (p.name || "") : (p || ""); })
      .filter(function (p) { return p; })
      .join(", ");
  }

  var entreprise = "";
  var localisation = "";

  // 1) schema.org JobPosting (JSON-LD) — most reliable when present.
  var scripts = document.querySelectorAll('script[type="application/ld+json"]');
  for (var i = 0; i < scripts.length && !entreprise; i++) {
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
        if (isJob && node.hiringOrganization) {
          var org = node.hiringOrganization;
          var name = typeof org === "string" ? org : org.name;
          if (name) { entreprise = String(name); }
        }
        // Zone géographique de l'offre (issue #52).
        if (isJob && !localisation && node.jobLocation) {
          var loc = Array.isArray(node.jobLocation) ? node.jobLocation[0] : node.jobLocation;
          if (loc) localisation = formatAddress(loc.address || loc);
        }
      }
    } catch (e) { /* ignore malformed JSON-LD */ }
  }

  // 2) Site-specific DOM selectors (pages without JSON-LD, e.g. LinkedIn signed-in).
  if (!entreprise) {
    var selectors = [
      ".topcard__org-name-link",                            // LinkedIn (déconnecté)
      ".topcard__flavor",                                   // LinkedIn (déconnecté, variante)
      ".job-details-jobs-unified-top-card__company-name a", // LinkedIn (connecté, lien société)
      ".job-details-jobs-unified-top-card__company-name",   // LinkedIn (connecté)
      ".jobs-unified-top-card__company-name",               // LinkedIn (ancienne UI)
      '[data-testid="inlineHeader-companyName"]',          // Indeed
      '[data-testid="company-name"]',                      // Indeed (variante)
      ".jobsearch-CompanyInfoContainer a",                 // Indeed (ancienne UI)
      ".company",                                          // génériques (APEC, Monster…)
    ];
    for (var k = 0; k < selectors.length && !entreprise; k++) {
      entreprise = text(selectors[k]);
    }
  }

  // 2bis) Sélecteurs DOM pour la localisation (issue #52).
  if (!localisation) {
    var locSelectors = [
      ".topcard__flavor--bullet",                              // LinkedIn (déconnecté)
      ".job-details-jobs-unified-top-card__bullet",            // LinkedIn (ancienne UI connectée)
      '[data-testid="inlineHeader-companyLocation"]',          // Indeed
      '[data-testid="job-location"]',                          // Indeed (variante)
      '[data-testid="jobsearch-JobInfoHeader-companyLocation"]', // Indeed (ancienne UI)
      ".location",                                             // génériques (APEC, Monster…)
    ];
    for (var m = 0; m < locSelectors.length && !localisation; m++) {
      localisation = text(locSelectors[m]);
    }
  }

  // 2ter) LinkedIn (UI connectée récente, vues /jobs/view et /jobs/collections) :
  // la localisation est le 1er segment (avant « · ») du conteneur de description
  // sous le titre, mêlée à la date de publication et au nombre de candidats.
  if (!localisation) {
    var descSelectors = [
      ".job-details-jobs-unified-top-card__primary-description-container",
      ".job-details-jobs-unified-top-card__tertiary-description-container",
      ".jobs-unified-top-card__primary-description",
    ];
    for (var p = 0; p < descSelectors.length && !localisation; p++) {
      var raw = text(descSelectors[p]);
      if (!raw) continue;
      var segs = raw.split(/[·•|]/)
        .map(function (s) { return s.replace(/\s+/g, " ").trim(); })
        .filter(function (s) { return s; });
      // Ignore un éventuel 1er segment qui répète le nom de l'entreprise.
      if (segs.length && entreprise && segs[0] === entreprise) segs.shift();
      if (segs.length) localisation = segs[0];
    }
  }

  // 3) Open Graph — but ignore generic job-board names (LinkedIn, Indeed…).
  if (!entreprise) {
    var og = meta("og:site_name");
    var generic = /linkedin|indeed|monster|cadr|apec|france.?travail|p[oô]le.?emploi|welcome to the jungle|glassdoor|hellowork/i;
    if (og && !generic.test(og)) entreprise = og;
  }

  return { url: location.href, entreprise: entreprise.trim(), localisation: localisation.trim() };
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
        if (data.url) document.getElementById("url").value = data.url;
        if (data.localisation) document.getElementById("localisation").value = data.localisation;
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
        localisation: document.getElementById("localisation").value.trim(),
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
