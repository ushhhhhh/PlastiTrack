// End-to-end tests for integration.js (run by test_frontend_js.py).
//
// Loads the REAL script.js, api.js and integration.js into one sandbox with
// a small fake DOM built from index.html. API calls go to a REAL Flask
// server started by the Python test (argv[3] = its base URL).
//
// Usage: node integration_js_test.js <project_root> <server_base_url>
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = process.argv[2];
const SERVER = process.argv[3];
const read = (f) => fs.readFileSync(path.join(ROOT, f), "utf8");
const HTML = read("index.html");
const SCRIPT_JS = read("script.js");
const API_JS = read("api.js");
const INTEGRATION_JS = read("integration.js");

/* ------------------------------------------------------ fake DOM --- */

class TextNode {
  constructor(text) { this.nodeType = 3; this._text = String(text); this.parentNode = null; }
  get textContent() { return this._text; }
  set textContent(v) { this._text = String(v); }
}

class Element {
  constructor(doc, tag, attrs) {
    this.ownerDocument = doc;
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.className = "";
    this.style = {};
    this.listeners = {};
    this.onclick = null;
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this._html = null;
    this.id = "";
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") this.className = v;
      else if (k === "value") this.value = v;
      else if (k === "disabled") this.disabled = true;
      else if (k === "checked") this.checked = true;
      else if (k === "id") this.id = v;
    }
    const self = this;
    this.classList = {
      add: (c) => { if (!self.classList.contains(c)) self.className = (self.className + " " + c).trim(); },
      remove: (c) => { self.className = self.className.split(/\s+/).filter((x) => x && x !== c).join(" "); },
      contains: (c) => self.className.split(/\s+/).includes(c),
      toggle: (c, on) => { (on ?? !self.classList.contains(c)) ? self.classList.add(c) : self.classList.remove(c); },
    };
  }
  get firstChild() { return this.children[0] || null; }
  get childNodes() { return this.children; }
  get textContent() {
    if (this._html !== null && !this.children.length) return this._html.replace(/<[^>]*>/g, "");
    return this.children.map((c) => c.textContent).join("");
  }
  set textContent(v) {
    this.children.forEach((c) => { c.parentNode = null; });
    this.children = [];
    this._html = null;
    if (String(v)) this.appendChild(new TextNode(v));
  }
  set innerHTML(html) {
    // Only the original script.js is allowed to use innerHTML.
    this.ownerDocument.innerHTMLWrites.push(this);
    this.children = [];
    this._html = String(html);
    for (const m of this._html.matchAll(/<(\w+)([^>]*)>/g)) {
      const attrs = {};
      for (const a of m[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) attrs[a[1]] = a[2] ?? "";
      if (attrs.id) this.ownerDocument.register(new Element(this.ownerDocument, m[1], attrs));
    }
  }
  get innerHTML() { return this._html ?? ""; }
  appendChild(node) {
    if (node.parentNode) node.parentNode.removeChild(node);
    node.parentNode = this;
    this.children.push(node);
    return node;
  }
  removeChild(node) {
    const i = this.children.indexOf(node);
    if (i >= 0) this.children.splice(i, 1);
    node.parentNode = null;
    return node;
  }
  setAttribute(k, v) { if (k === "class") this.className = v; else this[k] = v; }
  getAttribute(k) { return k === "class" ? this.className : this[k]; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  dispatch(type, extra) {
    const evt = Object.assign({ type, target: this, preventDefault() {} }, extra || {});
    if (type === "click" && typeof this.onclick === "function") this.onclick(evt);
    (this.listeners[type] || []).forEach((fn) => fn(evt));
    // bubble (needed for the #inputs "input" listener)
    if (this.parentNode && this.parentNode.dispatchBubble) this.parentNode.dispatchBubble(type, evt);
  }
  dispatchBubble(type, evt) {
    (this.listeners[type] || []).forEach((fn) => fn(evt));
    if (this.parentNode && this.parentNode.dispatchBubble) this.parentNode.dispatchBubble(type, evt);
  }
  click() { if (!this.disabled) this.dispatch("click"); }
  scrollIntoView() {}
  get options() { return this.children.filter((c) => c.tagName === "OPTION"); }
  closestId() {
    for (let n = this; n; n = n.parentNode) if (n.id) return n.id;
    return "";
  }
}

class Document {
  constructor(html) {
    this.byId = {};
    this.innerHTMLWrites = [];
    const opens = [...html.matchAll(/<(\w+)([^>]*\bid="([^"]+)"[^>]*)>/g)];
    for (const m of opens) {
      const tag = m[1];
      const attrs = {};
      for (const a of m[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) attrs[a[1]] = a[2] ?? "";
      this.register(new Element(this, tag, attrs));
    }
    // #inputs rows are appended by script.js; give #inputs a parent for bubbling.
  }
  register(el) {
    this.byId[el.id] = el;
    // inputs created through innerHTML bubble to #inputs
    if (el.id.startsWith("q_") && this.byId.inputs) el.parentNode = this.byId.inputs;
  }
  getElementById(id) { return this.byId[id] || null; }
  createElement(tag) { return new Element(this, tag); }
  createTextNode(text) { return new TextNode(text); }
}

/* ---------------------------------------------------------- page --- */

function makePage(options) {
  options = options || {};
  const doc = new Document(HTML);
  const calls = [];
  let inflight = 0;
  const storage = {};
  const ctx = {
    document: doc,
    location: { protocol: options.protocol || "http:" },
    localStorage: {
      getItem: (k) => (k in storage ? storage[k] : null),
      setItem: (k, v) => { storage[k] = String(v); },
    },
    AbortController,
    setTimeout, clearTimeout, console,
    fetch: (url, opts) => {
      calls.push({ url, method: (opts && opts.method) || "GET",
                   body: opts && opts.body ? JSON.parse(opts.body) : undefined });
      inflight++;
      const p = options.fetch ? options.fetch(url, opts) : fetch(SERVER + url, opts);
      return p.finally(() => { inflight--; });
    },
  };
  ctx.window = ctx;
  if (options.storedId) storage["plastitrack.userId"] = options.storedId;
  vm.createContext(ctx);
  vm.runInContext(SCRIPT_JS, ctx, { filename: "script.js" });
  if (!options.originalOnly) {
    vm.runInContext(API_JS, ctx, { filename: "api.js" });
    vm.runInContext(INTEGRATION_JS, ctx, { filename: "integration.js" });
  }
  const $ = (id) => doc.getElementById(id);
  async function settle() {
    for (let idle = 0; idle < 3;) {
      await new Promise((r) => setTimeout(r, 15));
      idle = inflight === 0 ? idle + 1 : 0;
    }
  }
  function setInputs(values) {
    for (const [id, v] of Object.entries(values)) $("q_" + id).value = String(v);
  }
  function edit(id, v) {
    $("q_" + id).value = String(v);
    $("q_" + id).dispatch("input");
  }
  function useId(raw) { $("pt-user").value = raw; $("pt-user-set").click(); }
  function text(id) { return $(id).textContent; }
  function originalOutputs() {
    return ["sW", "sY", "sC", "sS", "rP", "rC", "top"].map((id) => text(id))
      .concat([$("bars").innerHTML, $("alts").innerHTML]);
  }
  function findAll(root, pred, out = []) {
    for (const c of root.children || []) {
      if (c.nodeType === 1) { if (pred(c)) out.push(c); findAll(c, pred, out); }
    }
    return out;
  }
  return { ctx, doc, $, calls, settle, setInputs, edit, useId, text, originalOutputs, findAll };
}

const DEFAULTS = { bottle: 7, bag: 5, straw: 3, cutlery: 2, box: 2, cup: 4, wrap: 6 };
const LOWER = { bottle: 2, bag: 1, straw: 0, cutlery: 0, box: 0, cup: 1, wrap: 0 };
let uid = 0;
const freshId = (p) => (p || "user") + "_" + Date.now().toString(36) + (uid++);
const posts = (page, url) => page.calls.filter((c) => c.method === "POST" && c.url === url);

/* --------------------------------------------------------- tests --- */

const tests = [];
const test = (name, fn) => tests.push({ name, fn });

test("original calculator output is identical with integration loaded", async () => {
  for (const values of [DEFAULTS, LOWER, { bottle: 14, cup: 9, wrap: 2.5 }, { straw: -3, bag: 4 }]) {
    const plain = makePage({ originalOnly: true });
    plain.setInputs(values); plain.$("go").click();
    const page = makePage();
    await page.settle();
    page.setInputs(values); page.$("go").click();
    await page.settle();
    assert.deepStrictEqual(page.originalOutputs(), plain.originalOutputs(), JSON.stringify(values));
    assert.ok(!page.$("out").classList.contains("hide"));
    assert.ok(!page.$("rec").classList.contains("hide"));
  }
});

test("calculate never saves automatically", async () => {
  const page = makePage({ storedId: freshId() });
  await page.settle();
  for (let i = 0; i < 3; i++) { page.$("go").click(); await page.settle(); }
  assert.strictEqual(posts(page, "/api/history").length, 0);
  assert.ok(posts(page, "/api/calculate").length >= 1, "server check uses /api/calculate");
});

test("connected banner shown when server is up", async () => {
  const page = makePage();
  await page.settle();
  assert.match(page.$("pt-server").className, /pt-ok/);
  assert.match(page.text("pt-server"), /Connected/);
});

test("file:// page: calculator works, banner explains, no requests", async () => {
  const page = makePage({ protocol: "file:" });
  await page.settle();
  page.$("go").click();
  await page.settle();
  assert.strictEqual(page.text("sW"), "212");
  assert.match(page.$("pt-server").className, /pt-warn/);
  assert.match(page.text("pt-server"), /opened from a file/);
  assert.match(page.text("pt-server"), /calculator above still works/);
  assert.strictEqual(page.calls.length, 0);
  assert.strictEqual(page.$("pt-save").disabled, true);
});

test("server down: calculator works, banner shows how to start server", async () => {
  const page = makePage({ fetch: () => Promise.reject(new TypeError("Failed to fetch")) });
  await page.settle();
  page.$("go").click();
  assert.strictEqual(page.text("sS"), "79");
  assert.match(page.text("pt-server"), /Cannot reach the PlastiTrack server/);
  assert.match(page.text("pt-server"), /127\.0\.0\.1:5000/);
  assert.match(page.text("pt-history"), /Server not available/);
  assert.match(page.text("pt-save-msg"), /Start the PlastiTrack server/);
});

test("ID is trimmed + lowercased before every request; reserved ids refused", async () => {
  const page = makePage();
  await page.settle();
  const id = freshId("Mixed");
  page.useId("  " + id.toUpperCase() + "  ");
  await page.settle();
  assert.strictEqual(page.ctx.PlastiIntegration.state.userId, id.toLowerCase());
  assert.strictEqual(page.$("pt-user").value, id.toLowerCase());
  assert.match(page.text("pt-user-msg"), /lowercase/);
  const userCalls = page.calls.filter((c) => /user_id=/.test(c.url));
  assert.ok(userCalls.length > 0);
  assert.ok(userCalls.every((c) => c.url.includes("user_id=" + id.toLowerCase())), JSON.stringify(userCalls));
  page.useId("sample_demo");
  assert.match(page.text("pt-user-msg"), /reserved/);
  assert.strictEqual(page.ctx.PlastiIntegration.state.userId, id.toLowerCase());
  page.useId("a b");
  assert.match(page.$("pt-user-msg").className, /pt-error/);
});

test("explicit save: once per calculation, then history + trend update", async () => {
  const id = freshId();
  const page = makePage({ storedId: id });
  await page.settle();
  assert.strictEqual(page.$("pt-save").disabled, true, "disabled before calculate");
  page.$("go").click();
  await page.settle();
  assert.strictEqual(page.$("pt-save").disabled, false);
  assert.match(page.text("pt-save-msg"), /Server check: results match/);
  page.$("pt-save").click();
  page.$("pt-save").click();                  // double click while saving
  await page.settle();
  assert.strictEqual(posts(page, "/api/history").length, 1);
  assert.deepStrictEqual(posts(page, "/api/history")[0].body,
    { user_id: id, quantities: DEFAULTS });
  assert.strictEqual(page.$("pt-save").disabled, true, "disabled after save");
  assert.match(page.text("pt-save-msg"), /Saved for/);
  assert.match(page.text("pt-save-msg"), /212 g plastic\/week, eco score 79/);
  page.$("pt-save").click();
  await page.settle();
  assert.strictEqual(posts(page, "/api/history").length, 1, "no duplicate save");
  assert.match(page.text("pt-history"), /1 saved week\./);

  page.setInputs(LOWER); page.$("go").click(); await page.settle();
  page.$("pt-save").click(); await page.settle();
  assert.strictEqual(posts(page, "/api/history").length, 2);
  assert.match(page.text("pt-trend"), /went down/);
  assert.match(page.text("pt-trend"), /-172 g/);
  assert.match(page.text("pt-history"), /2 saved weeks\./);
});

test("editing inputs after Calculate blocks saving until recalculated", async () => {
  const page = makePage({ storedId: freshId() });
  await page.settle();
  page.$("go").click(); await page.settle();
  page.edit("bottle", 1);
  assert.strictEqual(page.$("pt-save").disabled, true);
  assert.match(page.text("pt-save-msg"), /changed a value/);
  page.$("pt-save").click(); await page.settle();
  assert.strictEqual(posts(page, "/api/history").length, 0);
  page.$("go").click(); await page.settle();
  assert.strictEqual(page.$("pt-save").disabled, false);
});

test("negative and >10000 values: original display unchanged, saving blocked", async () => {
  const page = makePage({ storedId: freshId() });
  await page.settle();
  page.setInputs({ straw: -4, cup: 10001 });
  page.$("go").click(); await page.settle();
  assert.ok(page.text("sS").length > 0, "original results still shown");
  assert.strictEqual(page.$("pt-save").disabled, true);
  const msg = page.text("pt-save-msg");
  assert.match(msg, /Plastic straw: must not be negative/);
  assert.match(msg, /Disposable plastic\/coated cup: must not exceed 10000/);
  assert.strictEqual(posts(page, "/api/history").length, 0);
  assert.strictEqual(posts(page, "/api/calculate").length, 0, "invalid values never sent");
});

test("no ID: saving explains what to do", async () => {
  const page = makePage();
  await page.settle();
  page.$("go").click(); await page.settle();
  assert.strictEqual(page.$("pt-save").disabled, true);
  assert.match(page.text("pt-save-msg"), /Choose your PlastiTrack ID/);
});

test("only script.js ever uses innerHTML (new sections use safe text)", async () => {
  const page = makePage({ storedId: freshId() });
  await page.settle();
  page.$("go").click(); await page.settle();
  page.$("pt-save").click(); await page.settle();
  const bad = page.doc.innerHTMLWrites.filter((e) => e.closestId().startsWith("pt-"));
  assert.deepStrictEqual(bad.map((e) => e.closestId()), []);
});

/* ---------------------------------------- stage 6: challenges --- */

function buttonsIn(page, id, label) {
  return page.findAll(page.$(id), (e) => e.tagName === "BUTTON" && e.textContent === label);
}

test("challenges: listed without ID, no buttons until ID chosen", async () => {
  const page = makePage();
  await page.settle();
  assert.match(page.text("pt-challenge-list"), /Avoid plastic water bottles for seven days/);
  assert.match(page.text("pt-challenge-list"), /Choose an ID above to join/);
  assert.strictEqual(page.findAll(page.$("pt-challenge-list"), (e) => e.tagName === "BUTTON").length, 0);
});

test("challenges: join -> complete -> badge, all through the buttons", async () => {
  const id = freshId();
  const page = makePage({ storedId: id });
  await page.settle();
  assert.strictEqual(buttonsIn(page, "pt-challenge-list", "Join challenge").length, 5);
  buttonsIn(page, "pt-challenge-list", "Join challenge")[0].click();
  await page.settle();
  assert.deepStrictEqual(posts(page, "/api/challenges/join")[0].body, { user_id: id, challenge_id: 1 });
  assert.match(page.text("pt-challenge-list"), /Joined "Avoid plastic water bottles/);
  assert.match(page.text("pt-challenge-list"), /In progress/);
  buttonsIn(page, "pt-challenge-list", "Mark as completed")[0].click();
  await page.settle();
  assert.strictEqual(posts(page, "/api/challenges/complete").length, 1);
  assert.match(page.text("pt-challenge-list"), /self-reported/);
  assert.match(page.text("pt-challenge-list"), /does not change your measured footprint/);
  assert.match(page.text("pt-badges"), /First Step/);
  assert.match(page.text("pt-badges"), /Self-reported/);
  assert.strictEqual(buttonsIn(page, "pt-challenge-list", "Mark as completed").length, 0);
  assert.strictEqual(buttonsIn(page, "pt-challenge-list", "Join challenge").length, 4);
});

test("challenges: server conflict message is shown, not swallowed", async () => {
  const id = freshId();
  const page = makePage({ storedId: id });
  await page.settle();
  // Complete in "another tab" first, then click the stale button here.
  await fetch(SERVER + "/api/challenges/join", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: id, challenge_id: 2 }) });
  await fetch(SERVER + "/api/challenges/complete", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: id, challenge_id: 2 }) });
  buttonsIn(page, "pt-challenge-list", "Join challenge")[1].click();
  await page.settle();
  assert.match(page.text("pt-challenge-list"), /already completed/);
});

test("passport: new user gets a friendly message, not an error", async () => {
  const page = makePage({ storedId: freshId() });
  await page.settle();
  assert.match(page.text("pt-passport"), /No passport yet/);
  assert.doesNotMatch(page.text("pt-passport"), /unavailable/);
});

test("passport: measured and self-reported sections, estimate explained", async () => {
  const id = freshId();
  const page = makePage({ storedId: id });
  await page.settle();
  page.$("go").click(); await page.settle();
  page.$("pt-save").click(); await page.settle();
  let text = page.text("pt-passport");
  assert.match(text, /1saved footprints/);
  assert.match(text, /79latest eco score/);
  assert.match(text, /Not enough data for a reduction estimate/);
  page.setInputs(LOWER); page.$("go").click(); await page.settle();
  page.$("pt-save").click(); await page.settle();
  buttonsIn(page, "pt-challenge-list", "Join challenge")[0].click(); await page.settle();
  buttonsIn(page, "pt-challenge-list", "Mark as completed")[0].click(); await page.settle();
  text = page.text("pt-passport");
  assert.match(text, /2saved footprints/);
  assert.match(text, /1challenges completed/);
  assert.match(text, /-172 gchange \/ week since first save/);
  assert.match(text, /Estimated plastic avoided since your first save/);
  assert.match(text, /less than one week/);           // honest note for same-day saves
  assert.match(text, /Self-reported actions/);
  assert.match(text, /Completed: Avoid plastic water bottles/);
  assert.match(text, /approximate project assumption/);
  assert.match(text, /Team: not in a campus team yet/);
  assert.match(page.text("pt-badges"), /Measured Reducer/);
  assert.match(page.text("pt-badges"), /Measured/);
});

test("switching ID never shows the previous user's data", async () => {
  const a = freshId("alpha"), b = freshId("beta");
  const page = makePage({ storedId: a });
  await page.settle();
  page.$("go").click(); await page.settle();
  page.$("pt-save").click(); await page.settle();
  assert.match(page.text("pt-history"), /1 saved week/);
  page.useId(b);
  await page.settle();
  assert.match(page.text("pt-history"), /No saved weeks yet for "beta_/);
  assert.match(page.text("pt-passport"), /No passport yet/);
  assert.doesNotMatch(page.text("pt-passport"), new RegExp(a));
});

/* -------------------------------------------- stage 7: campus --- */

async function api(method, url, body) {
  const r = await fetch(SERVER + url, { method, headers: { "Content-Type": "application/json" },
                                        body: body ? JSON.stringify(body) : undefined });
  return r.json();
}

test("campus: register team, join it, appear on leaderboard after 2 saves", async () => {
  const id = freshId();
  const team = "Team " + freshId("t");
  const page = makePage({ storedId: id });
  await page.settle();
  assert.match(page.text("pt-team-status"), /not in a team yet/);
  page.$("pt-team-name").value = "  " + team + "  ";
  page.$("pt-team-create").click(); await page.settle();
  assert.deepStrictEqual(posts(page, "/api/campus/teams")[0].body, { name: team });
  assert.match(page.text("pt-team-msg"), /registered/);
  const option = page.$("pt-team-select").options.find((o) => o.textContent.startsWith(team));
  assert.ok(option, "new team offered in the dropdown");
  assert.strictEqual(page.$("pt-team-select").value, option.value, "new team pre-selected");
  page.$("pt-team-join").click(); await page.settle();
  assert.deepStrictEqual(posts(page, "/api/campus/join")[0].body, { user_id: id, team_id: Number(option.value) });
  assert.match(page.text("pt-team-status"), new RegExp("Your team: " + team));
  assert.strictEqual(page.$("pt-team-join").disabled, true, "one team per student");
  assert.match(page.text("pt-leaderboard"), new RegExp("Not ranked yet.*" + team));

  page.$("go").click(); await page.settle(); page.$("pt-save").click(); await page.settle();
  page.setInputs(LOWER); page.$("go").click(); await page.settle(); page.$("pt-save").click(); await page.settle();
  const rows = page.findAll(page.$("pt-leaderboard"), (e) => e.tagName === "TR");
  const row = rows.find((r) => r.textContent.includes(team));
  assert.ok(row, "team ranked after two saves");
  assert.match(row.textContent, /81\.1% less/);
  assert.match(row.textContent, /1 of 1/);
  assert.match(page.text("pt-leaderboard"), /How ranking works/);
  assert.match(page.text("pt-summary"), /saved footprints/);
});

test("campus: duplicate team and reserved [SAMPLE] names give clear messages", async () => {
  const page = makePage({ storedId: freshId() });
  await page.settle();
  const team = "Dup " + freshId("d");
  page.$("pt-team-name").value = team; page.$("pt-team-create").click(); await page.settle();
  page.$("pt-team-name").value = team.toUpperCase(); page.$("pt-team-create").click(); await page.settle();
  assert.match(page.text("pt-team-msg"), /already exists/);
  page.$("pt-team-name").value = "[Sample] Fake"; page.$("pt-team-create").click(); await page.settle();
  assert.match(page.text("pt-team-msg"), /reserved/);
  assert.strictEqual(posts(page, "/api/campus/teams").length, 2, "reserved name never sent");
  page.$("pt-team-name").value = "x"; page.$("pt-team-create").click();
  assert.match(page.text("pt-team-msg"), /2-60 characters/);
});

test("campus: join without ID or team selection explains what to do", async () => {
  const page = makePage();
  await page.settle();
  assert.strictEqual(page.$("pt-team-join").disabled, true);
  assert.match(page.text("pt-team-status"), /Choose an ID/);
});

test("XSS: a team name with HTML is shown as plain text everywhere", async () => {
  const evil = '<img src=x onerror="alert(1)"> ' + freshId("x");
  const owner = freshId();
  await api("POST", "/api/campus/teams", { name: evil });
  const page = makePage({ storedId: owner });
  await page.settle();
  const option = page.$("pt-team-select").options.find((o) => o.textContent.includes("<img"));
  assert.ok(option, "name shown literally in dropdown");
  page.$("pt-team-select").value = option.value;
  page.$("pt-team-join").click(); await page.settle();
  assert.ok(page.text("pt-team-status").includes(evil));
  assert.ok(page.text("pt-leaderboard").includes(evil));
  const imgs = page.findAll(page.doc.getElementById("pt-campus"), (e) => e.tagName === "IMG");
  assert.strictEqual(imgs.length, 0, "no <img> element was created");
  const bad = page.doc.innerHTMLWrites.filter((e) => e.closestId().startsWith("pt-"));
  assert.strictEqual(bad.length, 0);
});

test("sample data: hidden by default, labelled when shown, never joinable", async () => {
  // Create sample data exactly like the seed script does (sample-only path).
  const { execFileSync } = require("child_process");
  const page = makePage({ storedId: freshId() });
  await page.settle();
  assert.strictEqual(page.$("pt-show-sample").checked, false);
  const initial = page.calls.filter((c) => /campus\/(summary|leaderboard)/.test(c.url));
  assert.ok(initial.length >= 2 && initial.every((c) => c.url.endsWith("include_sample=false")));
  assert.doesNotMatch(page.text("pt-leaderboard"), /\[SAMPLE\]/);

  // Seed via the real script into the same database the server uses.
  execFileSync(process.env.PT_PYTHON, ["-m", "backend.seed_sample_data"],
               { cwd: ROOT, env: Object.assign({}, process.env, { PLASTITRACK_DB: process.env.PT_DB }) });
  page.ctx.PlastiIntegration.refreshAll(); await page.settle();
  assert.doesNotMatch(page.text("pt-leaderboard"), /\[SAMPLE\]/, "still hidden after seeding");
  assert.doesNotMatch(page.text("pt-summary"), /SAMPLE demo data/);
  assert.ok(!page.$("pt-team-select").options.some((o) => /\[SAMPLE\]/.test(o.textContent)),
            "sample teams never offered for joining");

  page.$("pt-show-sample").checked = true; page.$("pt-show-sample").dispatch("change"); await page.settle();
  assert.match(page.text("pt-leaderboard"), /\[SAMPLE\] Green Warriors/);
  assert.match(page.text("pt-leaderboard"), /not real student participation/);
  assert.match(page.text("pt-summary"), /not real student participation/);
  const sampleRows = page.findAll(page.$("pt-leaderboard"), (e) => e.tagName === "TR")
    .filter((r) => r.textContent.includes("[SAMPLE]"));
  assert.ok(sampleRows.length >= 1 && sampleRows.every((r) => /Sample/.test(r.textContent.replace("[SAMPLE]", ""))),
            "every sample row carries the Sample tag");

  page.$("pt-show-sample").checked = false; page.$("pt-show-sample").dispatch("change"); await page.settle();
  assert.doesNotMatch(page.text("pt-leaderboard"), /\[SAMPLE\]/);
  execFileSync(process.env.PT_PYTHON, ["-m", "backend.seed_sample_data", "--remove"],
               { cwd: ROOT, env: Object.assign({}, process.env, { PLASTITRACK_DB: process.env.PT_DB }) });
});

(async () => {
  let failed = 0;
  for (const t of tests) {
    try { await t.fn(); console.log("ok   " + t.name); }
    catch (e) { failed++; console.log("FAIL " + t.name + "\n     " + (e && e.stack || e)); }
  }
  console.log(`${tests.length - failed}/${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
