window.STATE =
{
  "slug": "novin-music-service",
  "title": "Novin Music Service",
  "mode": "semi",
  "depth": "normal",
  "polish": null,
  "tier": "T2",
  "briefFile": "2026-08-22-brief.md",
  "memoryFile": "AGENTS.md",
  "startedAt": "2026-08-22T15:58:24+05:00",
  "updatedAt": "2026-08-22T16:27:06+05:00",
  "finishedAt": null,
  "stages": [
    { "id": "preflight", "status": "done", "startedAt": "2026-08-22T15:58:24+05:00", "finishedAt": "2026-08-22T15:59:15+05:00" },
    { "id": "manifest",  "status": "done", "startedAt": "2026-08-22T15:59:15+05:00", "finishedAt": "2026-08-22T15:59:51+05:00" },
    { "id": "briefing",  "status": "done", "startedAt": "2026-08-22T15:59:51+05:00", "finishedAt": "2026-08-22T16:06:45+05:00" },
    { "id": "spec",      "status": "done", "startedAt": "2026-08-22T16:06:45+05:00", "finishedAt": "2026-08-22T16:09:44+05:00" },
    { "id": "plan",      "status": "done", "startedAt": "2026-08-22T16:09:44+05:00", "finishedAt": "2026-08-22T16:12:03+05:00", "note": "5 тасков, ярус T2" },
    { "id": "build",     "status": "active", "startedAt": "2026-08-22T16:12:03+05:00", "note": "0 из 5 тасков готовы" },
    { "id": "review",    "status": "active", "startedAt": "2026-08-22T16:19:39+05:00", "note": "проверяется таск 1 из 5" },
    { "id": "final",     "status": "pending" }
  ],
  "requirements": {
    "total": 26, "done": 0, "inTicket": 26, "inSpec": 0,
    "placeholder": 0, "deferred": 0, "dropped": 0
  },
  "tickets": [
    { "id": "01", "title": "Основа приложения и локальная медиатека", "requirements": ["R02", "R14", "R15", "R16", "R22i", "G01", "G02"], "blockedBy": [], "wave": 1, "zone": ["app/catalog/", "app/api/catalog.py", "app/main.py"], "status": "review", "startedAt": "2026-08-22T16:12:03+05:00", "retries": 0, "repairs": 2 },
    { "id": "02", "title": "SMB-подключение, сканирование и обложки", "requirements": ["R01", "R07", "R08", "R09", "R10", "R11", "R17", "R20i", "R24i"], "blockedBy": ["01"], "wave": 2, "zone": ["app/scanner/", "app/share/", "app/api/scan.py"], "status": "pending", "retries": 0, "repairs": 0 },
    { "id": "03", "title": "MPD-клиент и управление воспроизведением", "requirements": ["R05", "R06", "R12", "R18", "R19", "R21i", "R24i", "G01"], "blockedBy": ["01"], "wave": 2, "zone": ["app/mpd/", "app/api/player.py"], "status": "pending", "retries": 0, "repairs": 0 },
    { "id": "04", "title": "Apple Music-подобный веб-интерфейс", "requirements": ["R04", "R13", "R14", "R15", "R16", "R17", "R18", "R19", "R21i", "R23i", "G02"], "blockedBy": ["02", "03"], "wave": 3, "zone": ["app/web/"], "status": "pending", "retries": 0, "repairs": 0 },
    { "id": "05", "title": "Docker-поставка, интеграция и документация", "requirements": ["R02", "R03", "R20i", "R22i", "R24i"], "blockedBy": ["02", "03", "04"], "wave": 4, "zone": ["Dockerfile", "docker-compose.yml", "scripts/", "README.md"], "status": "pending", "retries": 0, "repairs": 0 }
  ],
  "singlePass": null,
  "tests": null,
  "debt": { "placeholders": [], "assumptions": [], "emptyEnv": [] },
  "additions": [],
  "coverage": { "found": 0, "fixed": 0, "deferred": 0, "extra": "только углубления требований и решения реализации" },
  "blind": null
}
