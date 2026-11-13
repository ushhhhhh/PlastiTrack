/*
 * PlastiTrack frontend <-> backend integration (sections 4-7).
 *
 * - The original calculator in script.js is NOT modified. This file only
 *   adds an extra click listener to the existing "Calculate" button; the
 *   original handler always runs first and works with or without a server.
 * - All dynamic content is built with createElement + textContent (never
 *   innerHTML), so user-entered text such as team names is always shown as
 *   plain text and can never run as code.
 * - There is no login: a PlastiTrack ID is a nickname, not a password.
 * - All calculations are rule-based (see script.js and the backend); there
 *   is no AI or machine learning here.
 */
(function () {
  "use strict";

  var API = window.PlastiAPI;
  var STORAGE_KEY = "plastitrack.userId";

  var state = {
    online: false,        // server reachable?
    userId: "",           // normalised (lowercase) id, "" if none
    snapshot: null,       // {raw, check} captured when Calculate is clicked
    stale: false,         // inputs edited after the last Calculate
    saving: false,
    showSample: false     // sample data hidden by default
  };

  // Loaders are registered by each section below.
  var userLoaders = [];     // need a user id
  var globalLoaders = [];   // campus-wide data

  /* ------------------------------------------------------- helpers --- */

  function $(id) { return document.getElementById(id); }

  /* Safe element builder: text is always set with textContent. */
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }

  function append(parent) {
    for (var i = 1; i < arguments.length; i++) {
      var child = arguments[i];
      if (child === null || child === undefined || child === false) { continue; }
      parent.appendChild(typeof child === "string"
        ? document.createTextNode(child) : child);
    }
    return parent;
  }

  function clear(node) {
    while (node && node.firstChild) { node.removeChild(node.firstChild); }
    return node;
  }

  function note(text) { return el("p", "note", text); }

  function setMsg(node, text, kind, lines) {
    if (!node) { return; }
    clear(node);
    node.className = "pt-msg" + (kind ? " pt-" + kind : "");
    if (text) { append(node, text); }
    if (lines && lines.length) {
      var ul = el("ul");
      lines.forEach(function (line) { append(ul, el("li", null, line)); });
      append(node, ul);
    }
  }

  function showIn(container) {
    clear(container);
    for (var i = 1; i < arguments.length; i++) { append(container, arguments[i]); }
  }

  function storageGet() {
    try { return window.localStorage.getItem(STORAGE_KEY) || ""; }
    catch (e) { return ""; }
  }
  function storageSet(value) {
    try { window.localStorage.setItem(STORAGE_KEY, value); } catch (e) { /* ignore */ }
  }

  function itemNames() {
    var names = {};
    (window.ITEMS || []).forEach(function (item) { names[item.id] = item.name; });
    return names;
  }

  function readRawInputs() {
    var raw = {};
    (window.ITEMS || []).forEach(function (item) {
      var input = $("q_" + item.id);
      raw[item.id] = input ? input.value : "";
    });
    return raw;
  }

  function fmt(value, digits) {
    var n = Number(value);
    return isFinite(n) ? n.toFixed(digits === undefined ? 1 : digits) : "–";
  }

  function signed(value, digits, unit) {
    var n = Number(value);
    if (!isFinite(n)) { return "–"; }
    return (n > 0 ? "+" : "") + n.toFixed(digits) + (unit || "");
  }

  function fmtDate(iso) {
    if (!iso) { return "–"; }
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) { return String(iso); }
      return d.toLocaleString(undefined, { day: "numeric", month: "short",
        year: "numeric", hour: "2-digit", minute: "2-digit" });
    } catch (e) { return String(iso); }
  }

  function errorText(err) {
    return (err && err.message) ? err.message : "Something went wrong. Please try again.";
  }

  function errorLines(err) {
    return API.describeFieldErrors(err && err.details, itemNames());
  }

  function stat(value, label) {
    var box = el("div", "stat");
    append(box, el("b", null, value), el("span", null, label));
    return box;
  }

  function table(headers, rows, numericCols) {
    var wrap = el("div", "pt-table-wrap");
    var t = el("table", "pt-table");
    var thead = el("thead"), tr = el("tr");
    headers.forEach(function (h, i) {
      append(tr, el("th", numericCols && numericCols[i] ? "pt-num" : null, h));
    });
    append(thead, tr);
    var tbody = el("tbody");
    rows.forEach(function (cells) {
      var row = el("tr");
      cells.forEach(function (cell, i) {
        var td = el("td", numericCols && numericCols[i] ? "pt-num" : null);
        append(td, cell);
        append(row, td);
      });
      append(tbody, row);
    });
    append(t, thead, tbody);
    return append(wrap, t);
  }

  function sampleTag() { return el("span", "pt-sample", "Sample"); }

  /* Ignore responses that arrive after the user switched to another ID. */
  function forUser(userId, fn) {
    return function (data) { if (state.userId === userId) { fn(data); } };
  }

  /* -------------------------------------------- server connection --- */

  function setBanner(kind, text) {
    var banner = $("pt-server");
    if (!banner) { return; }
    banner.className = "pt-status" + (kind ? " pt-" + kind : "");
    banner.textContent = text;
  }

  function checkServer() {
    return API.health().then(function (health) {
      if (!health || health.database !== "ok") {
        throw new API.ApiError("http", "The server is running but its database is not ready.");
      }
      state.online = true;
      setBanner("ok", "Connected to the PlastiTrack server. Saving, challenges, " +
        "passport and campus features are available.");
      refreshAll();
    }).catch(function (err) {
      state.online = false;
      setBanner("warn", errorText(err) + " The calculator above still works without the server.");
      showOffline();
    }).then(updateSaveButton);
  }

  function showOffline() {
    ["pt-history", "pt-challenge-list", "pt-badges", "pt-passport",
     "pt-team-status", "pt-summary", "pt-leaderboard"].forEach(function (id) {
      var node = $(id);
      if (node) { showIn(node, note("Server not available.")); }
    });
    var trend = $("pt-trend");
    if (trend) { clear(trend); }
  }

  function refreshUser() {
    if (!state.online) { return; }
    userLoaders.forEach(function (load) { load(state.userId); });
  }

  function refreshGlobal() {
    if (!state.online) { return; }
    globalLoaders.forEach(function (load) { load(); });
  }

  function refreshAll() { refreshUser(); refreshGlobal(); }

  /* --------------------------------------------------- user id --- */

  function applyUserId(raw, announce) {
    var msg = $("pt-user-msg");
    var result = API.normaliseUserId(raw);
    if (!result.ok) {
      setMsg(msg, result.error, "error");
      return false;
    }
    var changed = String(raw).trim() !== result.value;
    state.userId = result.value;
    $("pt-user").value = result.value;
    storageSet(result.value);
    if (announce) {
      setMsg(msg, "Using ID \"" + result.value + "\"" +
        (changed ? " (IDs are stored in lowercase)." : "."), "success");
    }
    updateSaveButton();
    refreshUser();
    return true;
  }

  /* ------------------------------------- 4. save & track progress --- */

  function onCalculate() {
    // Runs AFTER the original script.js handler, which has already shown
    // the results. We only take a snapshot of the inputs for saving.
    var raw = readRawInputs();
    state.snapshot = { raw: raw, check: API.validateQuantities(raw), verified: null };
    state.stale = false;
    updateSaveButton();
    verifyWithServer(state.snapshot);
  }

  /* Optional consistency check: POST /api/calculate must agree with the
     numbers the original calculator just displayed. */
  function verifyWithServer(snapshot) {
    if (!state.online || !snapshot.check.ok) { return; }
    API.calculate(snapshot.check.quantities).then(function (result) {
      if (state.snapshot !== snapshot) { return; }
      var shownGrams = ($("sW") || {}).textContent;
      var shownScore = ($("sS") || {}).textContent;
      snapshot.verified = fmt(result.weekly_grams, 0) === String(shownGrams) &&
                          String(result.eco_score) === String(shownScore);
      updateSaveButton();
    }).catch(function () { /* the save itself will report problems */ });
  }

  function updateSaveButton() {
    var button = $("pt-save"), msg = $("pt-save-msg");
    if (!button) { return; }
    var snap = state.snapshot;
    var canSave = false;
    if (state.saving) {
      setMsg(msg, "Saving…");
    } else if (!snap) {
      setMsg(msg, "Calculate your footprint first, then save it here.");
    } else if (state.stale) {
      setMsg(msg, "You changed a value after calculating. Click \"Calculate my footprint\" again before saving.", "error");
    } else if (!snap.check.ok) {
      setMsg(msg, "These values can't be saved:", "error",
        API.describeFieldErrors(snap.check.errors, itemNames()).concat([
          "Saved records must use numbers from 0 to " + API.MAX_WEEKLY_QUANTITY +
          ". (The calculator above treats negative or empty boxes as 0.)"]));
    } else if (!state.online) {
      setMsg(msg, "Start the PlastiTrack server to save your footprint.", "error");
    } else if (!state.userId) {
      setMsg(msg, "Choose your PlastiTrack ID above to save this footprint.");
    } else {
      canSave = true;
      var check = snap.verified === true ? " Server check: results match."
        : snap.verified === false ? " Warning: the server calculated different numbers. Please recalculate." : "";
      setMsg(msg, "Ready to save this week's footprint for \"" + state.userId + "\"." + check,
             snap.verified === false ? "error" : null);
    }
    button.disabled = !canSave;
  }

  function onSave() {
    var snap = state.snapshot;
    if (!snap || state.stale || !snap.check.ok || !state.online ||
        !state.userId || state.saving) { return; }
    state.saving = true;
    updateSaveButton();
    var userId = state.userId;
    API.saveFootprint(userId, snap.check.quantities).then(function (res) {
      state.saving = false;
      state.snapshot = null;     // one save per calculation: no duplicates
      updateSaveButton();
      var rec = res.record;
      setMsg($("pt-save-msg"), "Saved for \"" + userId + "\" on " + fmtDate(rec.recorded_at) +
        ": " + fmt(rec.weekly_grams, 0) + " g plastic/week, eco score " + rec.eco_score + ".", "success");
      refreshAll();
    }).catch(function (err) {
      state.saving = false;
      updateSaveButton();
      setMsg($("pt-save-msg"), "Not saved: " + errorText(err), "error", errorLines(err));
    });
  }

  function loadTrend(userId) {
    var box = $("pt-trend");
    if (!box) { return; }
    if (!userId) { clear(box); return; }
    API.getComparison(userId).then(forUser(userId, function (cmp) {
      clear(box);
      if (cmp.trend === "insufficient_data") {
        if (cmp.total_records) {
          append(box, note("Save another week to see whether your plastic use is going up or down."));
        }
        return;
      }
      var cls = cmp.trend === "decreasing" ? "pt-down" : cmp.trend === "increasing" ? "pt-up" : "";
      var heading = el("p", "pt-trend " + cls);
      append(heading, el("b", null, cmp.message));
      append(heading, " Compared with your previous save on " + fmtDate(cmp.previous.recorded_at) + ".");
      var stats = el("div", "stats");
      append(stats,
        stat(signed(cmp.change.weekly_grams, 0, " g"), "change in plastic / week"),
        stat(cmp.change.weekly_percent === null ? "–" : signed(cmp.change.weekly_percent, 1, "%"),
             "change since last save"),
        stat(signed(cmp.change.eco_score, 0), "change in eco score"));
      append(box, heading, stats);
    })).catch(function (err) { showIn(box, note("Trend unavailable: " + errorText(err))); });
  }

  function loadHistory(userId) {
    var box = $("pt-history");
    if (!box) { return; }
    if (!userId) { showIn(box, note("Choose an ID to see your saved weeks.")); return; }
    showIn(box, note("Loading…"));
    API.getHistory(userId, 20).then(forUser(userId, function (data) {
      if (!data.total_records) {
        showIn(box, note("No saved weeks yet for \"" + userId + "\"."));
        return;
      }
      var rows = data.records.map(function (r) {
        return [fmtDate(r.recorded_at), fmt(r.weekly_grams, 0), fmt(r.annual_kg, 1),
                fmt(r.annual_co2e_kg, 1), String(r.eco_score)];
      });
      showIn(box,
        table(["Saved on", "g / week", "kg / year", "kg CO₂e / year", "Eco score"],
              rows, [false, true, true, true, true]),
        note(data.total_records > data.returned
          ? "Showing your latest " + data.returned + " of " + data.total_records + " saved weeks."
          : data.total_records + " saved week" + (data.total_records === 1 ? "" : "s") + "."));
    })).catch(function (err) { showIn(box, note("History unavailable: " + errorText(err))); });
  }

  userLoaders.push(loadTrend, loadHistory);

  /* ------------------------------------------------ 5. challenges --- */

  var challengeMsg = { text: "", kind: null };

  function challengeCard(c, userId) {
    var card = el("div", "alt");
    var head = el("div", "pt-challenge-head");
    var stateLabel = { not_joined: "Not joined", joined: "In progress", completed: "Completed" };
    append(head, el("b", null, c.title));
    if (userId && c.status) {
      append(head, el("span", "pt-state pt-state-" + c.status, stateLabel[c.status] || c.status));
    }
    append(card, head, el("div", null, c.description));
    var itemName = itemNames()[c.related_item];
    append(card, el("small", null,
      (itemName ? "Replaces: " + itemName + " · " : "") + c.duration_days + " days"));

    if (userId) {
      var actions = el("div", "pt-actions");
      if (c.status === "not_joined") {
        actions.appendChild(challengeButton("Join challenge", userId, c, "join"));
      } else if (c.status === "joined") {
        actions.appendChild(challengeButton("Mark as completed", userId, c, "complete"));
      } else if (c.status === "completed") {
        append(actions, el("small", null, "Completed on " + fmtDate(c.completed_at) + " (self-reported)."));
      }
      append(card, actions);
    }
    return card;
  }

  function challengeButton(label, userId, c, action) {
    var button = el("button", "pt-btn", label);
    button.type = "button";
    button.addEventListener("click", function () {
      button.disabled = true;
      var call = action === "join" ? API.joinChallenge : API.completeChallenge;
      call(userId, c.id).then(function () {
        challengeMsg = action === "join"
          ? { text: "Joined \"" + c.title + "\". Mark it as completed when you have done it.", kind: "success" }
          : { text: "Marked \"" + c.title + "\" as completed (self-reported). This earns badges but does not change your measured footprint.", kind: "success" };
        refreshUser();
      }).catch(function (err) {
        challengeMsg = { text: errorText(err), kind: "error" };
        refreshUser();
      });
    });
    return button;
  }

  function loadChallenges(userId) {
    var box = $("pt-challenge-list");
    if (!box) { return; }
    API.getChallenges(userId || undefined).then(function (data) {
      if (state.userId !== userId) { return; }
      clear(box);
      if (challengeMsg.text) {
        var msg = el("p");
        setMsg(msg, challengeMsg.text, challengeMsg.kind);
        append(box, msg);
        challengeMsg = { text: "", kind: null };
      }
      if (!userId) { append(box, note("Choose an ID above to join challenges.")); }
      data.challenges.forEach(function (c) { append(box, challengeCard(c, userId)); });
    }).catch(function (err) { showIn(box, note("Challenges unavailable: " + errorText(err))); });
  }

  function loadBadges(userId) {
    var box = $("pt-badges");
    if (!box) { return; }
    if (!userId) { showIn(box, note("Choose an ID to see your badges.")); return; }
    API.getProgress(userId).then(forUser(userId, function (data) {
      if (!data.badges.length) {
        showIn(box, note("No badges yet. Complete a challenge, or save three weeks, to earn one."));
        return;
      }
      var chips = el("div", "pt-chips");
      data.badges.forEach(function (b) {
        var chip = el("div", "pt-chip");
        append(chip, el("b", null, b.name), el("span", null, b.description),
               el("small", null, " " + (b.basis === "measured" ? "Measured" : "Self-reported") +
                 " · earned " + fmtDate(b.earned_at)));
        append(chips, chip);
      });
      showIn(box, chips, note("\"Self-reported\" badges come from challenges you marked as done. " +
        "\"Measured\" badges come from your saved footprints."));
    })).catch(function (err) { showIn(box, note("Badges unavailable: " + errorText(err))); });
  }

  userLoaders.push(loadChallenges, loadBadges);

  /* ------------------------------------------------- 6. passport --- */

  var passportListeners = [];   // e.g. campus team status (section 7)

  function loadPassport(userId) {
    var box = $("pt-passport");
    if (!box) { return; }
    if (!userId) {
      showIn(box, note("Choose an ID to see your passport."));
      passportListeners.forEach(function (fn) { fn(null, userId); });
      return;
    }
    API.getPassport(userId).then(forUser(userId, function (p) {
      passportListeners.forEach(function (fn) { fn(p, userId); });
      if (!p) {
        showIn(box, note("No passport yet for \"" + userId + "\". Save a footprint or join a challenge to start one."));
        return;
      }
      var m = p.measured_footprint, s = p.self_reported_actions;
      var change = m.change_since_baseline;
      var stats = el("div", "stats");
      append(stats,
        stat(String(m.total_records), "saved footprints"),
        stat(m.latest_eco_score === null ? "–" : String(m.latest_eco_score), "latest eco score"),
        stat(String(s.completed_challenges), "challenges completed"),
        stat(change.trend === "insufficient_data" ? "–" : signed(change.weekly_grams, 0, " g"),
             "change / week since first save"));

      var measured = el("div", "alt");
      append(measured, el("b", null, "Measured footprint"));
      var est = m.estimated_cumulative_reduction;
      if (est.sufficient_data) {
        var kg = Number(est.estimated_kg);
        append(measured, el("div", null, kg >= 0
          ? "Estimated plastic avoided since your first save: " + fmt(kg, 2) + " kg (about " +
            fmt(est.estimated_co2e_kg, 2) + " kg CO₂e) over " + fmt(est.weeks_covered, 1) + " weeks."
          : "Estimated extra plastic used compared with your first save: " + fmt(-kg, 2) +
            " kg over " + fmt(est.weeks_covered, 1) + " weeks."));
        if (est.note) { append(measured, el("small", null, est.note)); }
      } else {
        append(measured, el("div", null, "Not enough data for a reduction estimate yet: " +
          (est.reason || "save at least two footprints.")));
      }
      if (change.trend !== "insufficient_data") {
        append(measured, el("small", null, "If your latest weekly use continued for a year, you would use " +
          fmt(Math.abs(change.annualised_reduction_kg_if_sustained), 2) + " kg " +
          (change.annualised_reduction_kg_if_sustained >= 0 ? "less" : "more") +
          " plastic than at your first save (a yearly rate, not added to the estimate above)."));
      }

      var reported = el("div", "alt");
      append(reported, el("b", null, "Self-reported actions"),
        el("div", null, s.completed_challenges
          ? "Completed: " + s.completed.map(function (c) { return c.title; }).join("; ") + "."
          : "No challenges completed yet."),
        el("small", null, s.note));

      var teamLine = note(p.team
        ? "Team: " + p.team.team_name + (p.team.team_is_sample ? " (sample)" : "")
        : "Team: not in a campus team yet.");

      showIn(box, stats, measured, reported, teamLine,
        note("How the estimate works: " + est.method),
        note("CO₂e uses an approximate project assumption (3.0 kg CO₂e per kg of plastic), not a scientific constant."));
    })).catch(function (err) { showIn(box, note("Passport unavailable: " + errorText(err))); });
  }

  userLoaders.push(loadPassport);

  /* ------------------------------------------ 7. campus challenge --- */

  state.team = null;
  state.preferredTeamId = "";
  var SAMPLE_TEAM_PREFIX = "[sample]";

  function renderTeamStatus(passport, userId) {
    var box = $("pt-team-status"), join = $("pt-team-join");
    if (!box) { return; }
    state.team = passport && passport.team ? passport.team : null;
    if (!userId) {
      showIn(box, note("Choose an ID above to join a team."));
    } else if (!state.team) {
      showIn(box, note("\"" + userId + "\" is not in a team yet. Each student can join one team."));
    } else {
      var p = el("p", "note");
      append(p, "Your team: ", el("b", null, state.team.team_name),
             state.team.team_is_sample ? sampleTag() : null,
             " (joined " + fmtDate(state.team.joined_at) + "). Switching teams isn't supported yet.");
      showIn(box, p);
    }
    if (join) { join.disabled = !userId || !!state.team; }
  }
  passportListeners.push(renderTeamStatus);

  function loadTeams() {
    var select = $("pt-team-select");
    if (!select) { return; }
    API.getTeams().then(function (data) {
      // Decide the selection when the response arrives, so overlapping
      // reloads cannot undo the pre-selection of a newly created team.
      var previous = state.preferredTeamId || select.value;
      // Sample teams only accept sample users, so they are never offered here.
      var teams = data.teams.filter(function (t) { return !t.is_sample; });
      clear(select);
      var first = el("option", null, teams.length ? "Choose a team…" : "No teams yet. Register one below.");
      first.value = "";
      append(select, first);
      teams.forEach(function (t) {
        var option = el("option", null, t.name + " (" + t.member_count + " member" +
                        (t.member_count === 1 ? "" : "s") + ")");
        option.value = String(t.id);
        append(select, option);
      });
      var stillThere = teams.some(function (t) { return String(t.id) === previous; });
      select.value = stillThere ? previous : "";
      if (stillThere && previous === state.preferredTeamId) { state.preferredTeamId = ""; }
    }).catch(function (err) {
      clear(select);
      var option = el("option", null, "Teams unavailable");
      option.value = "";
      append(select, option);
      setMsg($("pt-team-msg"), "Teams unavailable: " + errorText(err), "error");
    });
  }

  function onJoinTeam() {
    var msg = $("pt-team-msg"), select = $("pt-team-select"), button = $("pt-team-join");
    if (!state.online) { setMsg(msg, "Start the PlastiTrack server to join a team.", "error"); return; }
    if (!state.userId) { setMsg(msg, "Choose your PlastiTrack ID above first.", "error"); return; }
    if (!select.value) { setMsg(msg, "Choose a team from the list first.", "error"); return; }
    button.disabled = true;
    API.joinTeam(state.userId, Number(select.value)).then(function (m) {
      setMsg(msg, "\"" + m.user_id + "\" joined " + m.team_name + ".", "success");
      refreshAll();
    }).catch(function (err) {
      setMsg(msg, "Could not join: " + errorText(err), "error");
      button.disabled = false;
    });
  }

  function onCreateTeam() {
    var msg = $("pt-team-msg"), input = $("pt-team-name"), button = $("pt-team-create");
    var name = String(input.value || "").trim();
    if (!state.online) { setMsg(msg, "Start the PlastiTrack server to register a team.", "error"); return; }
    if (name.length < 2 || name.length > 60) {
      setMsg(msg, "Team names must be 2-60 characters.", "error"); return;
    }
    if (name.toLowerCase().indexOf(SAMPLE_TEAM_PREFIX) === 0) {
      setMsg(msg, "Names starting with \"[SAMPLE]\" are reserved for demo data.", "error"); return;
    }
    button.disabled = true;
    API.createTeam(name).then(function (team) {
      button.disabled = false;
      input.value = "";
      setMsg(msg, "Team \"" + team.name + "\" registered. It is selected above: click \"Join team\" to join it.", "success");
      state.preferredTeamId = String(team.id);
      refreshGlobal();   // reloads the team list (and selects the new team)
    }).catch(function (err) {
      button.disabled = false;
      setMsg(msg, "Could not register team: " + errorText(err), "error");
    });
  }

  function sampleBanner() {
    return el("div", "pt-sample-banner",
      "Includes SAMPLE demo data for testing. Rows tagged \"Sample\" are not real student participation.");
  }

  function loadSummary() {
    var box = $("pt-summary");
    if (!box) { return; }
    var include = state.showSample;
    API.getSummary(include).then(function (data) {
      if (state.showSample !== include) { return; }
      var t = data.totals;
      var stats = el("div", "stats");
      append(stats,
        stat(String(t.teams), "teams"),
        stat(String(t.participants), "participants"),
        stat(String(t.participants_with_comparable_data), "with 2+ saved weeks"),
        stat(String(t.footprint_records), "saved footprints"),
        stat(fmt(t.total_measured_weekly_reduction_grams, 0) + " g", "measured reduction / week"),
        stat(String(t.self_reported_challenges_completed), "challenges completed (self-reported)"));
      showIn(box, data.contains_sample_data ? sampleBanner() : null, stats);
    }).catch(function (err) { showIn(box, note("Summary unavailable: " + errorText(err))); });
  }

  function loadLeaderboard() {
    var box = $("pt-leaderboard");
    if (!box) { return; }
    var include = state.showSample;
    API.getLeaderboard(include).then(function (data) {
      if (state.showSample !== include) { return; }
      clear(box);
      if (data.contains_sample_data) { append(box, sampleBanner()); }
      if (!data.leaderboard.length) {
        append(box, note("No team is ranked yet. A team is ranked once a member has saved at least two weeks."));
      } else {
        var rows = data.leaderboard.map(function (e) {
          var name = el("span");
          append(name, el("b", null, e.team_name), e.is_sample ? sampleTag() : null);
          var pct = Number(e.average_reduction_percent);
          return [String(e.rank), name,
                  fmt(Math.abs(pct), 1) + "% " + (pct >= 0 ? "less" : "more"),
                  e.members_with_comparable_data + " of " + e.member_count];
        });
        append(box, table(["Rank", "Team", "Avg. change in plastic", "Members with 2+ saves"],
                          rows, [true, false, true, true]));
      }
      if (data.unranked.length) {
        var p = el("p", "note");
        append(p, "Not ranked yet (need a member with two saved weeks): ");
        data.unranked.forEach(function (t, i) {
          append(p, i ? ", " : "", el("span", null, t.team_name), t.is_sample ? sampleTag() : null);
        });
        append(box, p);
      }
      append(box, note("How ranking works: " + data.method));
    }).catch(function (err) { showIn(box, note("Leaderboard unavailable: " + errorText(err))); });
  }

  globalLoaders.push(loadTeams, loadSummary, loadLeaderboard);

  /* ----------------------------------------------------- start up --- */

  function init() {
    if (!API) { return; }   // api.js failed to load: original page still works

    var go = $("go");
    if (go) { go.addEventListener("click", onCalculate); }

    var inputs = $("inputs");
    if (inputs) {
      inputs.addEventListener("input", function () {
        if (state.snapshot) { state.stale = true; updateSaveButton(); }
      });
    }

    var save = $("pt-save");
    if (save) { save.addEventListener("click", onSave); }

    var userInput = $("pt-user"), userSet = $("pt-user-set");
    if (userSet) { userSet.addEventListener("click", function () { applyUserId(userInput.value, true); }); }
    if (userInput) {
      userInput.addEventListener("keydown", function (e) {
        if (e.key === "Enter") { e.preventDefault(); applyUserId(userInput.value, true); }
      });
    }
    var teamJoin = $("pt-team-join"), teamCreate = $("pt-team-create"), teamName = $("pt-team-name");
    if (teamJoin) { teamJoin.disabled = true; teamJoin.addEventListener("click", onJoinTeam); }
    if (teamCreate) { teamCreate.addEventListener("click", onCreateTeam); }
    if (teamName) {
      teamName.addEventListener("keydown", function (e) {
        if (e.key === "Enter") { e.preventDefault(); onCreateTeam(); }
      });
    }
    var showSample = $("pt-show-sample");
    if (showSample) {
      showSample.checked = false;          // sample data hidden by default
      showSample.addEventListener("change", function () {
        state.showSample = !!showSample.checked;
        loadSummary();
        loadLeaderboard();
      });
    }

    var stored = storageGet();
    if (stored && API.normaliseUserId(stored).ok) {
      state.userId = API.normaliseUserId(stored).value;
      if (userInput) { userInput.value = state.userId; }
    }

    updateSaveButton();
    checkServer();
  }

  // Exposed only for automated tests; not used by the page itself.
  window.PlastiIntegration = { state: state, refreshAll: refreshAll };

  init();
})();
