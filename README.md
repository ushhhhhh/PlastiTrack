# PlastiTrack

PlastiTrack is an Environmental Studies (EVS) college project that helps students measure and reduce their **single-use plastic footprint**.

- **Phase 1 (frontend):** a browser-based Single-Use Plastic Footprint Calculator (`index.html`, `style.css`, `script.js`).
- **Phase 2:** a Python/Flask + SQLite **backend** that adds saved history, eco challenges, a personal Plastic Impact Passport and a campus team challenge.
- **Phase 3 (integration):** the website is connected to the backend through four new sections (4–7) at the bottom of the page. The original calculator, layout and design are kept.

The original calculator still works on its own, even if you open `index.html` directly from disk without the server. The new sections need the server and say so clearly when it is not running.

---

## Features

### Original calculator (sections 1–3, preserved)
- Weekly usage inputs for 7 single-use plastic items.
- Weekly grams, annual kg, estimated annual CO₂e and an eco score out of 100.
- Breakdown by item.
- Rule-based recommendations for sustainable alternatives, with estimated annual savings.

`script.js` and `style.css` are unchanged. In `index.html`, three pieces of text were reworded so the page no longer calls the rule-based engine "AI":
- "AI impact score" → "Impact score"
- "3. AI recommendations" → "3. Recommendations"
- The "Planned: ML/LLM" note now reads "Recommendations come from a rule-based engine over a plastic dataset."

Everything else in `index.html` is an addition.

### Website sections connected to the backend (new)
| Section | What you can do |
|---|---|
| **4. Save & track your progress** | Choose a PlastiTrack ID and save the footprint you just calculated, using the explicit **Save** button (Calculate never saves by itself). See whether your plastic use is going up or down, and list your saved weeks. |
| **5. Eco challenges** | Join challenges, mark them completed (self-reported) and see your badges, each labelled *Self-reported* or *Measured*. |
| **6. Plastic Impact Passport** | Your saved records, latest eco score, completed challenges, change since your first save, and the cumulative estimate with its method explained. |
| **7. Campus sustainability challenge** | Register a team, join it (one team per student), and see campus totals and the leaderboard. Sample data is hidden unless you tick **Show sample data**, and every sample row is tagged "Sample". |

A status line at the top of section 4 shows whether the page is connected to the server.

### Backend (new)
| Feature | What it does |
|---|---|
| **Footprint calculation API** | Python port of the exact `script.js` formulas and dataset, with strict input validation. |
| **Weekly footprint history** | Saves calculations per user in SQLite. Lists past records, compares the latest with the previous one and shows whether usage is increasing or decreasing. |
| **Eco challenges** | 5 built-in challenges. Users can join, mark complete, track progress and earn badges. |
| **Plastic Impact Passport** | Personal record: number of saved records, latest eco score, completed challenges, change since the first record, and a transparent cumulative-reduction estimate. |
| **Campus sustainability challenge** | Team registration, participation records, team summaries and a leaderboard based only on measured, comparable footprint data. |

### Calculation rules (identical to `script.js`)
```
weekly grams        = Σ (weekly quantity × grams per item)
annual plastic (kg) = weekly grams × 52 / 1000
annual CO₂e (kg)    = annual plastic kg × 3.0
eco score (0–100)   = max(0, round(100 − weekly grams / 10))
potential saving    = item weekly grams × item reduction fraction
```

> **The 3.0 kg CO₂e per kg of plastic factor is an approximate project assumption, not a universal scientific constant.** Real life-cycle emissions vary by plastic type, manufacturing and disposal.

The recommendations come from a **rule-based** engine over a fixed dataset. No machine learning or AI model is used anywhere in the backend.

### Measured vs. self-reported data
- **Measured:** footprint calculations the user saves. Only these can show a plastic reduction.
- **Self-reported:** challenge completions. They earn badges but **never** add plastic savings to the footprint, passport or leaderboard.
- Every badge is labelled `"basis": "self_reported"` or `"basis": "measured"`.

---

## Technology stack
- **Python 3.10+** (tested on Python 3.13.5, Windows 11)
- **Flask 3**: web framework / REST API
- **SQLite**: built into Python, so there is no database server to install
- **unittest**: built-in test framework (the tests also run under pytest)
- **Plain HTML, CSS and JavaScript** for the website: no framework and no build step
- **Node.js** (optional, testing only): runs the original `script.js` and the frontend tests. The website itself does not need Node.

No paid APIs, cloud services or external network calls are used. After the one-time `pip install`, everything runs offline.

---

## Project structure

```
PlastiTrack/
├── index.html                ← original page + new sections 4–7 (additions only, plus the 3 wording fixes)
├── style.css, script.js      ← original frontend (unchanged)
├── api.js                    ← API helper: requests, timeouts, error messages, input/ID checks
├── integration.js            ← logic for sections 4–7 (safe text rendering, no framework)
├── integration.css           ← styles for sections 4–7 only, using the original colour variables
├── README.md
├── .gitignore
├── database/
│   └── plastitrack.db                 ← created automatically (not committed)
└── backend/
    ├── app.py                 Flask app, error handling, serves the frontend
    ├── database.py            SQLite schema, auto table creation, challenge catalogue
    ├── models.py              data-access helpers (SQL for users and footprints)
    ├── calculations.py        dataset + formulas ported from script.js
    ├── errors.py              error types → HTTP 400 / 404 / 409
    ├── seed_sample_data.py    optional, clearly labelled sample data
    ├── requirements.txt
    ├── routes/                one Flask blueprint per feature
    │   ├── footprint.py   history.py   challenges.py   passport.py   campus.py
    ├── services/              business logic
    │   ├── footprint_service.py   challenge_service.py
    │   ├── passport_service.py    campus_service.py
    └── tests/
        ├── test_calculations.py   test_api.py   test_http.py   test_frontend_js.py
        ├── js_reference.js        runs the original script.js for comparison
        └── js/                    Node tests for api.js and integration.js
```

### How the frontend talks to the backend
- `script.js` is never modified. `integration.js` adds a second click listener to the existing **Calculate** button. That listener runs after the original one and only takes a snapshot of the inputs for saving.
- `api.js` sends every request with an 8-second timeout. It turns server errors, network failures and timeouts into readable messages.
- **User IDs** are trimmed and lowercased before every request. The `sample_` prefix is refused.
- **Before saving**, values are checked with the backend's rules: numbers from 0 to 10,000, and an empty box counts as 0. Negative or too-large values are named in a message and are not saved. The original calculator display is not affected.
- **Safe text:** all new content is built with `textContent`, never `innerHTML`, so text that users type (such as team names) can never run as code.
- The page must be opened at `http://127.0.0.1:5000/` to use sections 4–7. Opened from disk, the calculator works and the status line explains how to start the server.

Differences from the suggested structure, and why:
- `services/passport_service.py` and `services/campus_service.py` were added so each feature's rules live in one place.
- `errors.py` holds shared error types used by every service.
- `seed_sample_data.py` loads optional demo data.
- `tests/js_reference.js` runs the untouched `script.js` in Node for the comparison test.

### Architecture
```
Browser / API client
      │  HTTP + JSON
      ▼
routes/*.py      (parse request, return JSON + status code)
      ▼
services/*.py    (rules: comparisons, badges, passport, leaderboard)
      ▼
calculations.py  (pure formulas)      models.py (SQL)
                                            ▼
                                   database/plastitrack.db (SQLite)
```

The Flask app also serves the website from the project root, through an allow-list of exactly six files: `index.html`, `style.css`, `script.js`, `api.js`, `integration.js` and `integration.css`. The database and source code are never served.

---

## Installation (Windows, PowerShell)

Open PowerShell in the project folder (the one that contains `index.html`):

```powershell
cd "$HOME\OneDrive\Desktop\PlastiTrack"

# 1. Create a virtual environment (one time)
python -m venv .venv

# 2. Install dependencies (one time; needs internet)
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

> Tip: the commands call `.venv\Scripts\python.exe` directly, so you do not need to activate the environment or change PowerShell's execution policy. If you prefer activating it, run `.\.venv\Scripts\Activate.ps1`. If that is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

## Running locally

```powershell
.\.venv\Scripts\python.exe -m backend.app
```

- Website: <http://127.0.0.1:5000/>. Open this address, not the file, to use saving, challenges, passport and campus.
- API health check: <http://127.0.0.1:5000/api/health>
- Stop the server with **Ctrl + C**.

The database file `database\plastitrack.db` and all its tables are created automatically on first start. To use a different file, set `$env:PLASTITRACK_DB = "C:\path\to\file.db"` before starting.

### Optional: sample data for testing the campus features
```powershell
.\.venv\Scripts\python.exe -m backend.seed_sample_data            # add
.\.venv\Scripts\python.exe -m backend.seed_sample_data --remove   # remove
```
Sample teams are named `[SAMPLE] …`, sample users start with `sample_`, and both are stored with `is_sample = true`. **This is demo data, not real student participation.** Add `?include_sample=false` to the campus endpoints to hide it.

Sample and real data are kept apart:
- The `sample_` user-id prefix and the `[SAMPLE]` team-name prefix are **reserved**. The API rejects them (400) for real users and teams.
- Sample users can only join sample teams, and real users can only join real teams (409).
- History, comparison and passport responses include `is_sample`.
- If an older database already contains a real user with a sample id, the seed script stops without changing any real data.
- `--remove` deletes only rows flagged `is_sample = 1`.

---

## API documentation

All endpoints return JSON. Request bodies must be JSON with the header `Content-Type: application/json`.

**User identifiers.** A `user_id` is 3–40 characters: letters, digits, `_`, `-` or `.`. Examples: `riya_22`, `student.01`.
- Ids are **case-sensitive**: `Riya_22` and `riya_22` are different users.
- The `sample_` prefix is reserved for sample data.
- A user is created automatically the first time they save a footprint or join something.
- There is no login yet (see *Limitations*).

**Item ids.** The quantity keys are `bottle`, `bag`, `straw`, `cutlery`, `box`, `cup` and `wrap`.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Server and database status |
| GET | `/api/items` | The plastic dataset (weights, alternatives, tips) |
| POST | `/api/calculate` | Calculate a footprint (not saved) |
| POST | `/api/history` | Calculate **and save** a footprint |
| GET | `/api/history?user_id=…&limit=50` | Saved footprints, newest first |
| GET | `/api/history/comparison?user_id=…` | Latest vs. previous footprint and trend |
| GET | `/api/challenges[?user_id=…]` | Challenge list (with the user's status if `user_id` is given) |
| POST | `/api/challenges/join` | Join a challenge |
| POST | `/api/challenges/complete` | Mark a joined challenge as completed |
| GET | `/api/challenges/progress?user_id=…` | Joined and completed challenges, plus badges |
| GET | `/api/passport?user_id=…` | Plastic Impact Passport |
| GET | `/api/campus/teams` | List teams |
| POST | `/api/campus/teams` | Register a team |
| POST | `/api/campus/join` | Register a participant in a team |
| GET | `/api/campus/summary[?include_sample=false]` | Campus totals and per-team summaries |
| GET | `/api/campus/leaderboard[?include_sample=false]` | Team ranking |

### Status codes
| Code | Meaning |
|---|---|
| 200 | OK |
| 201 | Created (footprint saved, challenge joined, team created or joined) |
| 400 | Invalid input. The response `details` lists each bad field. |
| 404 | Unknown user, challenge, team or URL |
| 405 | Wrong HTTP method |
| 409 | Conflict: e.g. completing a challenge you have not joined or already completed, duplicate team name, user already in another team, mixing sample and real teams |
| 413 | Request body larger than 64 KB |
| 500 | Unexpected server error (details are logged in the server console, not sent to the client) |
| 503 | Database busy or missing tables (`/api/health` reports which) |

Error format:
```json
{"error": "Invalid weekly quantities.", "status": 400,
 "details": {"bottle": "must not be negative"}}
```

### Input validation
- Quantities must be finite JSON numbers that are ≥ 0 and ≤ 10 000. Decimals are allowed.
- Numeric strings such as `"5"`, booleans, `NaN` and `Infinity` are rejected.
- Unknown item ids are rejected, so typos are not silently ignored.
- A missing item counts as 0, the same as an empty box in the frontend.
- The server always recalculates results itself. Any result values a client sends are ignored.

> Note: the original frontend silently turns negative numbers into 0. The backend **rejects** them with HTTP 400 instead, as required for this stage.

### Examples (PowerShell)

```powershell
$api = "http://127.0.0.1:5000/api"

# Calculate (not saved)
Invoke-RestMethod -Method Post -Uri "$api/calculate" -ContentType "application/json" `
  -Body '{"quantities":{"bottle":7,"bag":5,"straw":3,"cutlery":2,"box":2,"cup":4,"wrap":6}}'

# Save two weeks and compare
Invoke-RestMethod -Method Post -Uri "$api/history" -ContentType "application/json" `
  -Body '{"user_id":"riya_22","quantities":{"bottle":7,"bag":5,"cup":4}}'
Invoke-RestMethod -Method Post -Uri "$api/history" -ContentType "application/json" `
  -Body '{"user_id":"riya_22","quantities":{"bottle":2,"bag":1,"cup":1}}'
Invoke-RestMethod "$api/history?user_id=riya_22"
Invoke-RestMethod "$api/history/comparison?user_id=riya_22"

# Challenges (challenge_id may be the number or the slug)
Invoke-RestMethod "$api/challenges?user_id=riya_22"
Invoke-RestMethod -Method Post -Uri "$api/challenges/join" -ContentType "application/json" `
  -Body '{"user_id":"riya_22","challenge_id":1}'
Invoke-RestMethod -Method Post -Uri "$api/challenges/complete" -ContentType "application/json" `
  -Body '{"user_id":"riya_22","challenge_id":1}'

# Passport (ConvertTo-Json shows the nested sections)
Invoke-RestMethod "$api/passport?user_id=riya_22" | ConvertTo-Json -Depth 6

# Campus
Invoke-RestMethod -Method Post -Uri "$api/campus/teams" -ContentType "application/json" `
  -Body '{"name":"Green Warriors","description":"FYBSc EVS group"}'
Invoke-RestMethod -Method Post -Uri "$api/campus/join" -ContentType "application/json" `
  -Body '{"user_id":"riya_22","team_id":1}'
Invoke-RestMethod "$api/campus/summary" | ConvertTo-Json -Depth 6
Invoke-RestMethod "$api/campus/leaderboard" | ConvertTo-Json -Depth 6
```

`curl.exe` (built into Windows 10/11) also works, e.g. `curl.exe http://127.0.0.1:5000/api/health`.

### How the estimates work

**History comparison.** The latest record is compared with the previous record made with the same dataset version. A change within ±0.001 g counts as `unchanged`; otherwise the trend is `increasing` or `decreasing`.

**Passport: cumulative reduction estimate.**
- The baseline is the user's first saved footprint.
- Between each pair of consecutive records, weekly usage is assumed to change linearly. The difference from the baseline is multiplied by the weeks in that period (a trapezoidal estimate).
- Each week is counted once against one fixed baseline, so nothing is double-counted.
- Nothing is extrapolated beyond the latest record.
- Challenges are not included.
- A negative value means more plastic was used than at the baseline.
- At least 2 comparable records are required; otherwise the estimate is `null`.

The passport also shows `annualised_reduction_kg_if_sustained`. This is a yearly *rate*, kept separate and labelled so that it is not added to the cumulative figure.

**Campus leaderboard.**
- A member counts as having comparable data when they have at least 2 footprints with the current dataset version.
- Member reduction % = (first − latest) / first × 100.
- Team score = the average of these percentages, so large teams do not win by size alone.
- Ties are broken by the number of members with comparable data, then by team name.
- Teams without comparable data are listed as `unranked`.
- Challenge completions do not affect the ranking.

### Database schema
| Table | Columns |
|---|---|
| `users` | `id` (user identifier, PK), `display_name`, `is_sample`, `created_at` |
| `footprints` | `id` PK, `user_id` → users, `recorded_at` (UTC ISO 8601), `weekly_grams`, `annual_kg`, `annual_co2e_kg`, `eco_score`, `dataset_version` |
| `footprint_items` | `footprint_id` → footprints, `item_id`, `weekly_quantity`, `weekly_grams` (PK: footprint_id + item_id) |
| `challenges` | `id` PK, `slug` (unique), `title`, `description`, `related_item`, `duration_days` |
| `user_challenges` | `user_id` → users, `challenge_id` → challenges, `status` (`joined`/`completed`), `joined_at`, `completed_at` (PK: user_id + challenge_id) |
| `teams` | `id` PK, `name` (unique, case-insensitive), `description`, `is_sample`, `created_at` |
| `team_members` | `user_id` PK → users (one team per user), `team_id` → teams, `joined_at` |

Badges are not stored. They are calculated from the tables above every time, so they can never get out of sync.

---

## Testing

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -t . -v
```

(`.\.venv\Scripts\python.exe -m pytest backend/tests` also works if pytest is installed.)

There are 75 Python tests in four files:
- `test_calculations.py` checks the formulas.
- `test_api.py` uses the Flask test client.
- `test_http.py` starts a real multi-threaded HTTP server on a free port, so it can test concurrent requests and server restarts.
- `test_frontend_js.py` runs the Node.js frontend tests:
  - `js/api_js_test.js` has 14 checks of the API helper.
  - `js/integration_js_test.js` has 22 end-to-end checks. It loads the real `script.js`, `api.js` and `integration.js` into one page and talks to a real Flask server. It proves the original calculator's output is identical with the integration loaded, that saving is explicit and happens once per calculation, that sample data is hidden by default, and that team names containing HTML are shown as plain text.

If Node.js is not installed, the JavaScript tests are skipped.

The tests use temporary database files and never touch `database\plastitrack.db`. They cover:
- **Real HTTP:** persistence after a server restart, creation of a missing database folder, concurrent duplicate requests (joins, completions, team creation, team joins, first saves) never causing a 500 or a double completion, the 413 size limit, and static file content types.
- **Data integrity:** a failed save leaves no partial rows, users cannot see each other's data, sample and real data stay separated, and the seed script refuses to touch real users.
- **Calculations:** hand-calculated results, JavaScript-style rounding, the zero-usage case and the eco-score floor at 0.
- **Comparison with the original frontend:** the dataset is checked against `script.js` text. If Node.js is installed, the **original `script.js` is executed** for 10 input sets and every displayed number must match.
- **Validation:** negative, non-numeric, NaN/Infinity, too-large and unknown inputs, plus malformed request bodies.
- **Database:** automatic table creation, saving and reading history, per-user separation and the `limit` parameter.
- **History comparisons:** increasing, decreasing, unchanged and insufficient data.
- **Challenges:** joining (by id and by slug), completing, error cases (409/404/400) and badges, including proof that completing challenges adds no savings.
- **Passport:** record counts, latest score, change since baseline and the cumulative-reduction estimate (positive and negative).
- **Campus:** team registration rules, leaderboard ranking and averages, unranked teams, summaries, and sample-data flagging and filtering.
- **Error handling:** JSON 404/405/500 responses, and checks that private files are not served.

---

## Reliability notes
- **Connections:** one SQLite connection per request, closed when the request ends. Anything not committed is rolled back, so a request that fails half-way leaves no partial data.
- **Transactions:** each write request commits once, after all of its inserts succeed.
- **Duplicate requests:** joining, completing, team creation and team membership use single atomic SQL statements (`INSERT … ON CONFLICT DO NOTHING`, `INSERT OR IGNORE`, `UPDATE … WHERE status = 'joined'`). Duplicate requests, even simultaneous ones, get 200 or 409, never 500 and never a double completion.
- **Waiting writers:** SQLite waits up to 10 seconds for a concurrent writer before answering 503.
- **SQL safety:** every value is passed as a `?` parameter. No user input is ever placed into SQL text.
- **Missing database:** the database file, its folder and all tables are recreated on start-up if they are missing. `/api/health` returns 503 if tables disappear while the server is running.

## Limitations
- **No authentication. This backend is NOT secure for real users.** A `user_id` is an identifier, not a password or login. Anyone who can reach the server and knows or guesses an id can read that user's history and passport, or add records, challenge completions and team membership in their name. The leaderboard can be influenced the same way. This is acceptable only for a local prototype on your own laptop (the server listens on `127.0.0.1`). A real login system is required before multiple students use it over a network.
- No rate limiting, and no protection against someone creating many fake users or teams.
- User ids are case-sensitive. The frontend integration should normalise them (for example, lowercase) before sending.
- The backend rejects quantities above 10 000 per item per week. The original frontend does not limit this, so the integration step should validate the same way or show the backend's error message.
- The API must be called from the same origin: open the page at `http://127.0.0.1:5000/`, not by double-clicking `index.html`. CORS is not enabled. When opened from disk, the calculator still works and sections 4–7 show how to start the server.
- The browser remembers your PlastiTrack ID in `localStorage` for convenience. On a shared computer, anyone using the same browser will see it.
- For a brand-new ID, the browser console shows one "404 (NOT FOUND)" line for `/api/passport`. This is the backend's normal "no data yet" answer, and the page shows a friendly message instead.
- There is no way yet to leave or switch teams, or to delete a saved week.
- All data is **self-entered**. Weekly quantities are not verified, so even "measured" footprints are estimates from what users report.
- Item weights and the 3.0 CO₂e factor are approximate project assumptions.
- One team per user; there is no endpoint yet for leaving or switching teams.
- Challenge durations (7 days) are informational; the backend does not stop early completion.
- The Flask development server is meant for local use only.
