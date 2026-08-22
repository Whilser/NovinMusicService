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
  "updatedAt": "2026-08-22T18:09:09+05:00",
  "finishedAt": "2026-08-22T18:09:09+05:00",
  "stages": [
    { "id": "preflight", "status": "done", "startedAt": "2026-08-22T15:58:24+05:00", "finishedAt": "2026-08-22T15:59:15+05:00" },
    { "id": "manifest",  "status": "done", "startedAt": "2026-08-22T15:59:15+05:00", "finishedAt": "2026-08-22T15:59:51+05:00" },
    { "id": "briefing",  "status": "done", "startedAt": "2026-08-22T15:59:51+05:00", "finishedAt": "2026-08-22T16:06:45+05:00" },
    { "id": "spec",      "status": "done", "startedAt": "2026-08-22T16:06:45+05:00", "finishedAt": "2026-08-22T16:09:44+05:00" },
    { "id": "plan",      "status": "done", "startedAt": "2026-08-22T16:09:44+05:00", "finishedAt": "2026-08-22T16:12:03+05:00", "note": "5 тасков, ярус T2" },
    { "id": "build",     "status": "done", "startedAt": "2026-08-22T16:12:03+05:00", "finishedAt": "2026-08-22T18:01:17+05:00", "note": "5 из 5 тасков готовы" },
    { "id": "review",    "status": "done", "startedAt": "2026-08-22T16:19:39+05:00", "finishedAt": "2026-08-22T18:01:17+05:00", "note": "проверены 5 из 5" },
    { "id": "final",     "status": "done", "startedAt": "2026-08-22T18:01:17+05:00", "finishedAt": "2026-08-22T18:09:09+05:00", "note": "слепая приёмка завершена" }
  ],
  "requirements": {
    "total": 26, "done": 20, "inTicket": 0, "inSpec": 0,
    "placeholder": 6, "deferred": 0, "dropped": 0
  },
  "tickets": [
    { "id": "01", "title": "Основа приложения и локальная медиатека", "requirements": ["R02", "R14", "R15", "R16", "R22i", "G01", "G02"], "blockedBy": [], "wave": 1, "zone": ["app/catalog/", "app/api/catalog.py", "app/main.py"], "status": "done", "startedAt": "2026-08-22T16:12:03+05:00", "finishedAt": "2026-08-22T16:28:50+05:00", "retries": 0, "repairs": 2, "tests": { "passed": 10, "failed": 0 }, "commit": "efa54f3", "concerns": ["runtime data/catalog.sqlite3 удалить и игнорировать в T05"] },
    { "id": "02", "title": "SMB-подключение, сканирование и обложки", "requirements": ["R01", "R07", "R08", "R09", "R10", "R11", "R17", "R20i", "R24i"], "blockedBy": ["01"], "wave": 2, "zone": ["app/scanner/", "app/share/", "app/api/scan.py", "app/catalog/catalog.py: SMB allowlist only"], "status": "done", "startedAt": "2026-08-22T16:28:50+05:00", "finishedAt": "2026-08-22T16:57:44+05:00", "retries": 0, "repairs": 2, "tests": { "passed": 35, "failed": 0 }, "commit": "bba3988", "concerns": [] },
    { "id": "03", "title": "MPD-клиент и управление воспроизведением", "requirements": ["R05", "R06", "R12", "R18", "R19", "R21i", "R24i", "G01"], "blockedBy": ["01"], "wave": 2, "zone": ["app/mpd/", "app/api/player.py"], "status": "done", "startedAt": "2026-08-22T16:28:50+05:00", "finishedAt": "2026-08-22T16:46:29+05:00", "retries": 0, "repairs": 2, "tests": { "passed": 30, "failed": 0 }, "commit": "044642d", "concerns": [] },
    { "id": "04", "title": "Apple Music-подобный веб-интерфейс", "requirements": ["R04", "R12", "R13", "R14", "R15", "R16", "R17", "R18", "R19", "R21i", "R23i", "G02"], "blockedBy": ["02", "03"], "wave": 3, "zone": ["app/web/", "app/main.py: static hosting only", "package.json: test-only"], "status": "done", "startedAt": "2026-08-22T16:59:26+05:00", "finishedAt": "2026-08-22T17:42:13+05:00", "retries": 2, "repairs": 2, "tests": { "passed": 37, "failed": 0 }, "commit": "28a2325", "concerns": [] },
    { "id": "05", "title": "Docker-поставка, интеграция и документация", "requirements": ["R02", "R03", "R20i", "R22i", "R24i"], "blockedBy": ["02", "03", "04"], "wave": 4, "zone": ["Dockerfile", "docker-compose.yml", "scripts/", "README.md", ".gitignore", "tests/integration/"], "status": "done", "startedAt": "2026-08-22T17:42:13+05:00", "finishedAt": "2026-08-22T18:01:17+05:00", "retries": 0, "repairs": 2, "tests": { "passed": 49, "failed": 0, "skipped": 2 }, "commit": "5a58c54", "concerns": ["Docker/CIFS runtime smoke требует Linux novin"] }
  ],
  "singlePass": null,
  "tests": { "passed": 49, "failed": 0, "skipped": 2 },
  "debt": { "placeholders": ["R02/R03 — Docker build/up на сервере novin", "R20i — реальное read-only подключение NAS", "R05/R18/R19 — воспроизведение и shuffle на живом MPD"], "assumptions": [], "emptyEnv": ["SMB_USERNAME", "SMB_PASSWORD", "MPD_PASSWORD"] },
  "additions": [],
  "coverage": { "found": 0, "fixed": 0, "deferred": 0, "extra": "только углубления требований и решения реализации" },
  "blind": {
    "agreed": 20,
    "drift": 6,
    "fixed": 0,
    "unresolved": 6,
    "findings": [
      "R02/R03 — Docker-поставка есть, но build/up на novin не выполнены",
      "R20i — CIFS mount реализован без проверки с реальной NAS-шарой",
      "R05 — MPD client/UI реализованы без проверки с живым MPD",
      "R18 — последовательное воспроизведение проверено только на fake MPD",
      "R19 — случайное воспроизведение проверено только на fake MPD"
    ]
  }
}
