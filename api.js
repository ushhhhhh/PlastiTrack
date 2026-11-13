/*
 * PlastiTrack API helper (plain JavaScript, no framework, no build step).
 *
 * Talks to the local Flask backend. Everything lives inside one object,
 * window.PlastiAPI, so nothing here can clash with the globals defined by
 * the original script.js (ITEMS, CO2_PER_KG, box, f).
 *
 * NOTE: there is no login. A PlastiTrack ID is a nickname, not a password.
 */
(function (root) {
  "use strict";

  var TIMEOUT_MS = 8000;
  var MAX_WEEKLY_QUANTITY = 10000;          // same limit as the backend
  var USER_ID_PATTERN = /^[a-z0-9_.-]{3,40}$/;
  var SAMPLE_PREFIX = "sample_";            // reserved for demo data

  /* An error that is always safe to show to the user. */
  function ApiError(kind, message, status, details) {
    this.name = "ApiError";
    this.kind = kind;          // "offline" | "network" | "timeout" | "http"
    this.message = message;
    this.status = status || 0;
    this.details = details || null;
  }
  ApiError.prototype = Object.create(Error.prototype);
  ApiError.prototype.constructor = ApiError;

  /* Pages opened straight from disk (file://) cannot reach the server. */
  function isFilePage() {
    return !!(root.location && root.location.protocol === "file:");
  }

  var SERVER_HINT = "Start the server (python -m backend.app) and open " +
                    "http://127.0.0.1:5000/";

  function request(method, path, body) {
    if (isFilePage()) {
      return Promise.reject(new ApiError("offline",
        "This page was opened from a file, so it cannot reach the " +
        "PlastiTrack server. " + SERVER_HINT));
    }
    if (typeof root.fetch !== "function") {
      return Promise.reject(new ApiError("network",
        "This browser cannot make server requests."));
    }
    var controller = typeof root.AbortController === "function"
      ? new root.AbortController() : null;
    var timer = controller
      ? setTimeout(function () { controller.abort(); }, api.TIMEOUT_MS) : null;
    var options = { method: method, headers: { "Accept": "application/json" } };
    if (controller) { options.signal = controller.signal; }
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }

    return root.fetch(path, options).then(function (response) {
      return response.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
        if (response.ok) { return data; }
        var message = (data && data.error) ||
          ("The server returned an error (HTTP " + response.status + ").");
        if (response.status === 503) {
          message = "The server is busy. Please try again in a moment.";
        } else if (response.status >= 500) {
          message = "Something went wrong on the server. Please try again.";
        }
        throw new ApiError("http", message, response.status,
                           data && data.details);
      });
    }, function (err) {
      if (err && err.name === "AbortError") {
        throw new ApiError("timeout",
          "The server took too long to answer. Please try again.");
      }
      throw new ApiError("network",
        "Cannot reach the PlastiTrack server. " + SERVER_HINT);
    }).then(function (data) {
      if (timer) { clearTimeout(timer); }
      return data;
    }, function (err) {
      if (timer) { clearTimeout(timer); }
      throw err;
    });
  }

  function qs(params) {
    var parts = [];
    Object.keys(params).forEach(function (key) {
      var value = params[key];
      if (value !== undefined && value !== null && value !== "") {
        parts.push(encodeURIComponent(key) + "=" +
                   encodeURIComponent(String(value)));
      }
    });
    return parts.length ? "?" + parts.join("&") : "";
  }

  /* ---------------------------------------------------- validation --- */

  /* Lowercase + trim, then apply the same rules as the backend. */
  function normaliseUserId(raw) {
    var value = String(raw === undefined || raw === null ? "" : raw)
      .trim().toLowerCase();
    if (!value) {
      return { ok: false, value: value,
               error: "Enter a PlastiTrack ID first." };
    }
    if (!USER_ID_PATTERN.test(value)) {
      return { ok: false, value: value,
               error: "IDs are 3-40 characters: letters, digits, _ - or ." };
    }
    if (value.indexOf(SAMPLE_PREFIX) === 0) {
      return { ok: false, value: value,
               error: "IDs starting with \"sample_\" are reserved for demo data." };
    }
    return { ok: true, value: value, error: "" };
  }

  /*
   * Check raw input-box strings ({bottle: "7", ...}) with the backend's
   * rules. The ORIGINAL calculator display is not affected: this is only
   * used before saving.
   */
  function validateQuantities(rawById) {
    var quantities = {}, errors = {};
    Object.keys(rawById).forEach(function (id) {
      var raw = rawById[id];
      var text = String(raw === undefined || raw === null ? "" : raw).trim();
      if (text === "") { quantities[id] = 0; return; }   // empty box = 0
      var n = Number(text);
      if (!isFinite(n)) { errors[id] = "must be a number"; }
      else if (n < 0) { errors[id] = "must not be negative"; }
      else if (n > MAX_WEEKLY_QUANTITY) {
        errors[id] = "must not exceed " + MAX_WEEKLY_QUANTITY +
                     " items per week";
      } else { quantities[id] = n; }
    });
    return { ok: Object.keys(errors).length === 0,
             quantities: quantities, errors: errors };
  }

  /* Turn {item_id: problem} into readable lines using item names. */
  function describeFieldErrors(details, namesById) {
    if (!details) { return []; }
    return Object.keys(details).map(function (key) {
      var label = (namesById && namesById[key]) || key;
      return label + ": " + details[key];
    });
  }

  /* --------------------------------------------------------- calls --- */

  var api = {
    TIMEOUT_MS: TIMEOUT_MS,
    MAX_WEEKLY_QUANTITY: MAX_WEEKLY_QUANTITY,
    ApiError: ApiError,
    isFilePage: isFilePage,
    normaliseUserId: normaliseUserId,
    validateQuantities: validateQuantities,
    describeFieldErrors: describeFieldErrors,
    request: request,

    health: function () { return request("GET", "/api/health"); },
    calculate: function (quantities) {
      return request("POST", "/api/calculate", { quantities: quantities });
    },
    saveFootprint: function (userId, quantities) {
      return request("POST", "/api/history",
                     { user_id: userId, quantities: quantities });
    },
    getHistory: function (userId, limit) {
      return request("GET", "/api/history" +
                     qs({ user_id: userId, limit: limit }));
    },
    getComparison: function (userId) {
      return request("GET", "/api/history/comparison" + qs({ user_id: userId }));
    },
    getChallenges: function (userId) {
      return request("GET", "/api/challenges" + qs({ user_id: userId }));
    },
    joinChallenge: function (userId, challengeId) {
      return request("POST", "/api/challenges/join",
                     { user_id: userId, challenge_id: challengeId });
    },
    completeChallenge: function (userId, challengeId) {
      return request("POST", "/api/challenges/complete",
                     { user_id: userId, challenge_id: challengeId });
    },
    getProgress: function (userId) {
      return request("GET", "/api/challenges/progress" + qs({ user_id: userId }));
    },
    /* Resolves to null (not an error) for a user with no data yet. */
    getPassport: function (userId) {
      return request("GET", "/api/passport" + qs({ user_id: userId }))
        .catch(function (err) {
          if (err instanceof ApiError && err.status === 404) { return null; }
          throw err;
        });
    },
    getTeams: function () { return request("GET", "/api/campus/teams"); },
    createTeam: function (name, description) {
      var body = { name: name };
      if (description) { body.description = description; }
      return request("POST", "/api/campus/teams", body);
    },
    joinTeam: function (userId, teamId) {
      return request("POST", "/api/campus/join",
                     { user_id: userId, team_id: teamId });
    },
    getSummary: function (includeSample) {
      return request("GET", "/api/campus/summary" +
                     qs({ include_sample: includeSample ? "true" : "false" }));
    },
    getLeaderboard: function (includeSample) {
      return request("GET", "/api/campus/leaderboard" +
                     qs({ include_sample: includeSample ? "true" : "false" }));
    }
  };

  root.PlastiAPI = api;
})(typeof window !== "undefined" ? window : this);
