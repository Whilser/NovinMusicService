window.STATE =
{
  "slug": "apple-music-ui-refresh",
  "title": "Интерфейс ближе к Apple Music",
  "mode": "semi",
  "depth": "normal",
  "polish": null,
  "tier": "T0",
  "briefFile": "2026-08-22-brief.md",
  "memoryFile": "AGENTS.md",
  "startedAt": "2026-08-22T18:42:56+05:00",
  "updatedAt": "2026-08-22T18:55:11+05:00",
  "finishedAt": null,
  "stages": [
    { "id": "preflight", "status": "done", "startedAt": "2026-08-22T18:42:56+05:00", "finishedAt": "2026-08-22T18:43:35+05:00" },
    { "id": "manifest", "status": "done", "startedAt": "2026-08-22T18:43:35+05:00", "finishedAt": "2026-08-22T18:44:03+05:00" },
    { "id": "briefing", "status": "skipped", "startedAt": "2026-08-22T18:44:03+05:00", "finishedAt": "2026-08-22T18:44:03+05:00", "note": "вопросов не потребовалось — референс задан" },
    { "id": "spec", "status": "done", "startedAt": "2026-08-22T18:44:03+05:00", "finishedAt": "2026-08-22T18:45:36+05:00" },
    { "id": "plan", "status": "skipped", "startedAt": "2026-08-22T18:45:36+05:00", "finishedAt": "2026-08-22T18:45:36+05:00", "note": "ярус T0 — один web-слой, без разбивки" },
    { "id": "build", "status": "done", "startedAt": "2026-08-22T18:45:36+05:00", "finishedAt": "2026-08-22T18:55:11+05:00", "note": "Apple Music-подобный web presentation реализован" },
    { "id": "review", "status": "done", "startedAt": "2026-08-22T18:52:00+05:00", "finishedAt": "2026-08-22T18:55:11+05:00", "note": "manifest/spec/craft clean; desktop и mobile проверены визуально" },
    { "id": "final", "status": "pending" }
  ],
  "requirements": {
    "total": 3, "done": 3, "inTicket": 0, "inSpec": 0,
    "placeholder": 0, "deferred": 0, "dropped": 0
  },
  "tickets": [],
  "singlePass": {
    "status": "done",
    "startedAt": "2026-08-22T18:45:36+05:00",
    "finishedAt": "2026-08-22T18:55:11+05:00",
    "files": ["app/web/index.html", "app/web/assets/app.js", "app/web/assets/apple.css", "tests/web/test_web.py", "tests/web/browser_smoke.mjs"],
    "tests": "52 tests OK (2 Docker-only skipped); browser smoke OK; node --check OK; git diff --check OK",
    "commit": "feat: refresh interface with Apple Music styling"
  },
  "tests": { "status": "green", "passed": 52, "skipped": 2, "browserSmoke": "green" },
  "debt": { "placeholders": [], "assumptions": [], "emptyEnv": [] },
  "additions": [],
  "coverage": { "found": 0, "fixed": 0, "deferred": 0, "extra": "только углубления R01–R03i" },
  "blind": null
}
