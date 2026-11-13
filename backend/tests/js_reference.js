// Runs the ORIGINAL, unmodified frontend script.js inside Node with a tiny
// fake DOM, clicks "Calculate", and prints what the page would display.
// Used by test_calculations.py to prove the backend matches the frontend.
//
// Usage: node js_reference.js <path-to-script.js> '<json quantities>'
const fs = require("fs");
const vm = require("vm");

const [scriptPath, quantitiesJson] = process.argv.slice(2);
const quantities = JSON.parse(quantitiesJson);

const elements = {};
function el(id) {
  if (!elements[id]) {
    elements[id] = {
      id, value: "", textContent: "", innerHTML: "", className: "",
      classList: { remove() {}, add() {} },
      appendChild() {}, scrollIntoView() {}, onclick: null,
    };
  }
  return elements[id];
}
const document = {
  getElementById: el,
  createElement: () => ({ className: "", innerHTML: "" }),
};

vm.runInNewContext(fs.readFileSync(scriptPath, "utf8"), { document });

for (const [id, value] of Object.entries(quantities)) {
  el("q_" + id).value = String(value);
}
el("go").onclick();

// Per-category "<name></span><span>123 g/wk" pairs from the bar chart HTML.
const bars = {};
const re = /<span>([^<]+)<\/span><span>([^<]+) g\/wk<\/span>/g;
let m;
while ((m = re.exec(el("bars").innerHTML)) !== null) bars[m[1]] = m[2];

// Recommendation names in display order.
const recs = [];
const reRec = /<div class="alt[^"]*"><b>([^<]+)<\/b>/g;
while ((m = reRec.exec(el("alts").innerHTML)) !== null) recs.push(m[1]);

console.log(JSON.stringify({
  weekly: el("sW").textContent, yearly: el("sY").textContent,
  co2: el("sC").textContent, score: String(el("sS").textContent),
  savedKg: el("rP").textContent, savedCo2: el("rC").textContent,
  top: el("top").textContent, bars, recs,
}));
