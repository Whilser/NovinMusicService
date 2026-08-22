import assert from "node:assert/strict";
import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join } from "node:path";
import { createRequire } from "node:module";

const { chromium } = createRequire(import.meta.url)("playwright");

const webRoot = join(process.cwd(), "app", "web");
const hostile = '<img data-attack="yes" src=x onerror="window.hacked=true">';
const baseTracks = [
  { id: 3, path: "new.flac", title: hostile, artist: "Artist A", album: "Same", album_artist: "Artist A", duration: 180, cover_url: "/api/covers/cover-a", rating: 4, favorite: true },
  { id: 2, path: "other.flac", title: "Other", artist: "Artist B", album: "Same", album_artist: "Artist B", duration: 160, cover_url: null, rating: 0, favorite: false },
  { id: 1, path: "old.flac", title: "Old", artist: "Artist A", album: "First", album_artist: "Artist A", duration: 140, cover_url: null, rating: 2, favorite: true }
];
let tracks = structuredClone(baseTracks);
let playlists = [];
let nextPlaylist = 1;
let failTracks = false;
let trackDelay = 180;
let player = { online: false, state: "offline", song: null, message: "offline" };
const requests = [];

function json(response, status, body) {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(body));
}

async function waitFor(condition, timeout = 3000) {
  const started = Date.now();
  while (!condition()) {
    if (Date.now() - started > timeout) throw new Error("timed out waiting for browser-side request");
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
}

async function waitForRoute(page, hash, title, readySelector) {
  await page.waitForURL((url) => url.hash === hash);
  await page.waitForFunction(
    ({ expectedHash, expectedTitle, selector }) =>
      location.hash === expectedHash &&
      document.querySelector("#page-title")?.textContent === expectedTitle &&
      document.querySelector("#content")?.getAttribute("aria-busy") === "false" &&
      Boolean(document.querySelector(selector)),
    { expectedHash: hash, expectedTitle: title, selector: readySelector }
  );
}

async function body(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : {};
}

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, "http://127.0.0.1");
  if (!url.pathname.startsWith("/api/")) {
    const relative = url.pathname.startsWith("/assets/") ? url.pathname.slice(1) : "index.html";
    try {
      const data = await readFile(join(webRoot, relative));
      const type = extname(relative) === ".css" ? "text/css" : extname(relative) === ".js" ? "text/javascript" : "text/html";
      response.writeHead(200, { "content-type": `${type}; charset=utf-8` }); response.end(data);
    } catch { response.writeHead(404); response.end(); }
    return;
  }
  if (url.pathname === "/api/tracks") {
    if (trackDelay) await new Promise((resolve) => setTimeout(resolve, trackDelay));
    if (failTracks) return json(response, 500, { error: { code: "catalog_failed", message: "Catalog failed safely" } });
    const search = (url.searchParams.get("search") || "").toLowerCase();
    const favorite = url.searchParams.get("favorite");
    let found = tracks.filter((item) => !search || [item.title, item.artist, item.album].some((value) => value.toLowerCase().includes(search)));
    if (favorite === "true") found = found.filter((item) => item.favorite);
    const offset = Number(url.searchParams.get("offset") || 0); const limit = Number(url.searchParams.get("limit") || 50);
    return json(response, 200, { items: found.slice(offset, offset + limit), total: found.length, offset, limit });
  }
  if (url.pathname === "/api/albums") return json(response, 200, { items: [{ name: "Same", album_artist: "Artist A", track_count: 1 }, { name: "Same", album_artist: "Artist B", track_count: 1 }, { name: "First", album_artist: "Artist A", track_count: 1 }], total: 3 });
  if (url.pathname === "/api/artists") return json(response, 200, { items: [{ name: "Artist A", track_count: 2 }, { name: "Artist B", track_count: 1 }], total: 2 });
  if (url.pathname === "/api/playlists" && request.method === "GET") return json(response, 200, playlists.map((item) => ({ ...item, track_count: item.tracks.length })));
  if (url.pathname === "/api/playlists" && request.method === "POST") { const input = await body(request); requests.push({ method: request.method, path: url.pathname, body: input }); const item = { id: nextPlaylist++, name: input.name, tracks: [] }; playlists.push(item); return json(response, 201, item); }
  const playlistMatch = url.pathname.match(/^\/api\/playlists\/(\d+)$/);
  if (playlistMatch) {
    const item = playlists.find((candidate) => candidate.id === Number(playlistMatch[1]));
    if (!item) return json(response, 404, { error: { code: "not_found", message: "Not found" } });
    if (request.method === "GET") return json(response, 200, item);
    if (request.method === "PATCH") { const input = await body(request); requests.push({ method: request.method, path: url.pathname, body: input }); item.name = input.name; return json(response, 200, item); }
    if (request.method === "DELETE") { requests.push({ method: request.method, path: url.pathname }); playlists = playlists.filter((candidate) => candidate.id !== item.id); response.writeHead(204); response.end(); return; }
  }
  const playlistTracks = url.pathname.match(/^\/api\/playlists\/(\d+)\/tracks(?:\/(\d+))?$/);
  if (playlistTracks) {
    const item = playlists.find((candidate) => candidate.id === Number(playlistTracks[1]));
    if (!item) return json(response, 404, { error: { code: "not_found", message: "Not found" } });
    if (request.method === "POST") { const input = await body(request); requests.push({ method: request.method, path: url.pathname, body: input }); const track = tracks.find((candidate) => candidate.id === input.track_id); if (!item.tracks.some((candidate) => candidate.id === track.id)) item.tracks.push(track); return json(response, 201, item); }
    if (request.method === "DELETE") { requests.push({ method: request.method, path: url.pathname }); item.tracks = item.tracks.filter((candidate) => candidate.id !== Number(playlistTracks[2])); return json(response, 200, item); }
    if (request.method === "PUT") { const input = await body(request); requests.push({ method: request.method, path: url.pathname, body: input }); item.tracks = input.track_ids.map((id) => tracks.find((candidate) => candidate.id === id)); return json(response, 200, item); }
  }
  if (/^\/api\/tracks\/\d+\/preference$/.test(url.pathname)) { const input = await body(request); requests.push({ method: request.method, path: url.pathname, body: input }); const item = tracks.find((candidate) => String(candidate.id) === url.pathname.split("/")[3]); Object.assign(item, input); return json(response, 200, item); }
  if (url.pathname === "/api/player/status") return json(response, 200, player);
  if (url.pathname === "/api/player/command" || url.pathname === "/api/player/play") { const input = await body(request); requests.push({ method: request.method, path: url.pathname, body: input }); return json(response, 200, player); }
  if (url.pathname.startsWith("/api/covers/")) { response.writeHead(200, { "content-type": "image/svg+xml" }); response.end('<svg xmlns="http://www.w3.org/2000/svg"/>'); return; }
  if (url.pathname === "/api/settings") return json(response, 200, {});
  if (url.pathname === "/api/share/status") return json(response, 200, { state: "not_configured" });
  if (url.pathname === "/api/scan/status") return json(response, 200, { state: "idle", counters: {} });
  json(response, 404, { error: { code: "not_found", message: "Not found" } });
});

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}) });

try {
  const desktop = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await desktop.goto(`${origin}/#/songs`);
  await waitForRoute(desktop, "#/songs", "Песни", ".track-row");
  const routeBeforeSkip = new URL(await desktop.url()).hash;
  await desktop.keyboard.press("Tab");
  assert.equal(await desktop.evaluate(() => document.activeElement?.matches("[data-skip-link]")), true);
  assert.equal(await desktop.evaluate(() => getComputedStyle(document.activeElement).outlineStyle), "solid");
  await desktop.keyboard.press("Enter");
  assert.equal(await desktop.evaluate(() => document.activeElement?.id), "main");
  assert.equal(new URL(await desktop.url()).hash, routeBeforeSkip);
  await desktop.goto(`${origin}/#/albums?name=Same&album_artist=Artist%20A`);
  await desktop.waitForFunction(() => Boolean(document.querySelector('[data-action="back-group"]')));
  await desktop.getByRole("button", { name: "Назад к списку: альбомы" }).click();
  await waitForRoute(desktop, "#/albums", "Альбомы", '[data-action="select-group"][data-type="album"]');
  await desktop.goto(`${origin}/#/songs`);
  await waitForRoute(desktop, "#/songs", "Песни", ".track-row");
  assert.equal(await desktop.locator('[data-attack="yes"]').count(), 0);
  assert.equal(await desktop.getByText(hostile, { exact: true }).count(), 1);
  assert.notEqual(await desktop.evaluate(() => window.hacked), true);
  assert.equal(await desktop.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  assert.match(await desktop.locator("link[href='/assets/styles.css']").evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--accent")), /fa2d48/);

  const routeReadiness = {
    home: ["Главная", ".section-heading h2"],
    albums: ["Альбомы", '[data-action="select-group"][data-type="album"]'],
    artists: ["Исполнители", '[data-action="select-group"][data-type="artist"]'],
    songs: ["Песни", ".track-row"],
    playlists: ["Плейлисты", '[data-action="create-playlist"]'],
    favorites: ["Избранное", ".track-row"],
    settings: ["Настройки", '[data-form="smb"]']
  };
  for (const route of Object.keys(routeReadiness)) {
    await desktop.locator(`#sidebar-nav [data-route="${route}"]`).click();
    await waitForRoute(desktop, `#/${route}`, ...routeReadiness[route]);
    assert.equal(new URL(await desktop.url()).hash, `#/${route}`);
  }
  assert.equal(await desktop.getByRole("status", { name: "SMB: не настроено" }).count(), 1);
  assert.equal(await desktop.getByRole("status", { name: "MPD: не настроен" }).count(), 1);
  await desktop.goto(`${origin}/#/artists?name=Artist+A`);
  await waitForRoute(desktop, "#/artists?name=Artist+A", "Artist A", '[data-track-id="1"]');
  await desktop.reload();
  await waitForRoute(desktop, "#/artists?name=Artist+A", "Artist A", '[data-track-id="1"]');
  await desktop.goBack(); await desktop.goForward();
  await waitForRoute(desktop, "#/artists?name=Artist+A", "Artist A", '[data-track-id="1"]');
  assert.match(await desktop.url(), /#\/artists\?name=Artist\+A/);

  await desktop.goto(`${origin}/#/playlists`);
  await waitForRoute(desktop, "#/playlists", "Плейлисты", '[data-action="create-playlist"]');
  await desktop.locator('[data-action="create-playlist"]').click();
  await desktop.locator("#playlist-dialog").waitFor({ state: "visible" });
  await desktop.getByLabel("Название").fill("Road"); await desktop.getByRole("button", { name: "Сохранить" }).click();
  await waitFor(() => requests.some((item) => item.method === "POST" && item.path === "/api/playlists"));
  await desktop.locator("#playlist-dialog").waitFor({ state: "hidden" });
  await waitForRoute(desktop, "#/playlists", "Плейлисты", '[data-action="open-playlist"][aria-label="Открыть Road"]');
  assert.deepEqual(requests.find((item) => item.path === "/api/playlists"), { method: "POST", path: "/api/playlists", body: { name: "Road" } });

  await desktop.goto(`${origin}/#/songs`); await waitForRoute(desktop, "#/songs", "Песни", ".track-row");
  await desktop.evaluate(() => { window.prompt = () => "1"; });
  for (const [index, trackId] of [3, 2].entries()) {
    await desktop.locator(`[data-track-id="${trackId}"]`).getByRole("button", { name: "Добавить в плейлист" }).click();
    await waitFor(() => playlists[0].tracks.length === index + 1);
  }
  assert.deepEqual(playlists[0].tracks.map((item) => item.id), [3, 2]);
  assert.deepEqual(requests.filter((item) => item.method === "POST" && item.path.includes("/tracks")), [
    { method: "POST", path: "/api/playlists/1/tracks", body: { track_id: 3 } },
    { method: "POST", path: "/api/playlists/1/tracks", body: { track_id: 2 } }
  ]);

  await desktop.goto(`${origin}/#/playlists/1`); await waitForRoute(desktop, "#/playlists/1", "Road", ".track-row");
  assert.deepEqual(await desktop.locator(".track-row .track-title strong").allTextContents(), [hostile, "Other"]);
  await desktop.locator('[data-track-id="3"]').getByRole("button", { name: "Ниже" }).click();
  await waitFor(() => requests.some((item) => item.method === "PUT" && item.path.endsWith("/tracks")));
  await desktop.waitForFunction((expected) => JSON.stringify([...document.querySelectorAll(".track-row .track-title strong")].map((node) => node.textContent)) === JSON.stringify(expected), ["Other", hostile]);
  assert.deepEqual(playlists[0].tracks.map((item) => item.id), [2, 3]);
  assert.deepEqual(requests.find((item) => item.method === "PUT" && item.path.endsWith("/tracks")), { method: "PUT", path: "/api/playlists/1/tracks", body: { track_ids: [2, 3] } });
  await desktop.locator('[data-track-id="2"]').getByRole("button", { name: "Удалить из плейлиста" }).click();
  await waitFor(() => requests.some((item) => item.method === "DELETE" && item.path.includes("/tracks/")));
  await desktop.locator('[data-track-id="2"]').waitFor({ state: "detached" });
  assert.deepEqual(playlists[0].tracks.map((item) => item.id), [3]);
  assert.deepEqual(requests.find((item) => item.method === "DELETE" && item.path.includes("/tracks/")), { method: "DELETE", path: "/api/playlists/1/tracks/2" });

  await desktop.goto(`${origin}/#/songs`); await waitForRoute(desktop, "#/songs", "Песни", '[data-track-id="3"]');
  await desktop.locator('[data-track-id="3"]').getByRole("button", { name: "5 из 5" }).click();
  await waitFor(() => requests.filter((item) => item.path === "/api/tracks/3/preference").length === 1);
  await desktop.locator('[data-track-id="3"] button[data-action="rate"][data-value="5"].active').waitFor();
  await desktop.locator('[data-track-id="3"]').getByRole("button", { name: "Убрать из избранного" }).click();
  await waitFor(() => requests.filter((item) => item.path === "/api/tracks/3/preference").length === 2);
  await desktop.locator('[data-track-id="3"]').getByRole("button", { name: "Добавить в избранное" }).waitFor();
  assert.deepEqual(requests.filter((item) => item.path === "/api/tracks/3/preference").map((item) => item.body), [{ rating: 5 }, { favorite: false }]);

  await desktop.goto(`${origin}/#/playlists/1`); await waitForRoute(desktop, "#/playlists/1", "Road", '[data-action="rename-playlist"]');
  await desktop.getByRole("button", { name: "Переименовать" }).click();
  await desktop.locator("#playlist-dialog").waitFor({ state: "visible" });
  await desktop.getByLabel("Название").fill("Night"); await desktop.getByRole("button", { name: "Сохранить" }).click();
  await waitFor(() => requests.some((item) => item.method === "PATCH" && item.path === "/api/playlists/1"));
  await desktop.locator("#playlist-dialog").waitFor({ state: "hidden" });
  await waitForRoute(desktop, "#/playlists/1", "Night", '[data-action="delete-playlist"]');
  assert.equal(playlists[0].name, "Night");
  assert.deepEqual(requests.find((item) => item.method === "PATCH"), { method: "PATCH", path: "/api/playlists/1", body: { name: "Night" } });
  desktop.once("dialog", (dialog) => dialog.accept());
  await desktop.getByRole("button", { name: "Удалить", exact: true }).click();
  await waitFor(() => requests.some((item) => item.method === "DELETE" && item.path === "/api/playlists/1"));
  await waitForRoute(desktop, "#/playlists", "Плейлисты", ".empty");
  await desktop.getByText("Пока нет плейлистов").waitFor();
  assert.equal(playlists.length, 0);
  assert.deepEqual(requests.find((item) => item.method === "DELETE" && item.path === "/api/playlists/1"), { method: "DELETE", path: "/api/playlists/1" });

  await desktop.goto(`${origin}/#/home`); await waitForRoute(desktop, "#/home", "Главная", ".section-heading h2");
  tracks = []; await desktop.reload(); await waitForRoute(desktop, "#/home", "Главная", ".empty"); await desktop.getByText("Ваша медиатека пока пуста").waitFor();
  tracks = structuredClone(baseTracks); failTracks = true; await desktop.reload(); await waitForRoute(desktop, "#/home", "Главная", ".error-state"); await desktop.getByText("Catalog failed safely").waitFor(); failTracks = false; trackDelay = 0;

  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await mobile.goto(`${origin}/#/songs`); await waitForRoute(mobile, "#/songs", "Песни", ".track-row");
  assert.equal(await mobile.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  for (const label of ["Исполнители", "Избранное"]) assert.equal(await mobile.getByRole("link", { name: new RegExp(label) }).isVisible(), true);
  assert.equal(await mobile.getByRole("button", { name: "4 из 5" }).first().isVisible(), true);
  assert.equal(await mobile.getByLabel("Позиция воспроизведения", { exact: true }).isVisible(), true);
  assert.equal(await mobile.getByLabel("Громкость", { exact: true }).isVisible(), true);
  assert.equal(await mobile.locator("#player").getByLabel("Воспроизвести").isDisabled(), true);
  assert.equal(await mobile.getByLabel("Позиция воспроизведения", { exact: true }).getAttribute("aria-disabled"), "true");
  player = { online: true, state: "play", elapsed: 12, duration: 180, volume: 35, song: { id: 1, file: "new.flac", title: hostile, artist: "Artist A" } };
  await mobile.waitForFunction(() => !document.querySelector('#player [data-command="pause"]')?.disabled && Boolean(document.querySelector("#player-cover img[src='/api/covers/cover-a']")));
  assert.equal(await mobile.locator("#player").getByLabel("Пауза").isDisabled(), false);
  assert.equal(await mobile.locator("#player-cover img[src='/api/covers/cover-a']").count(), 1);
  await mobile.locator("#player-cover").click();
  assert.equal(await mobile.locator("#fullscreen-player").isVisible(), true);
  assert.equal(await mobile.locator("#fullscreen-cover img[src='/api/covers/cover-a']").count(), 1);
  await mobile.keyboard.press("Escape");
  assert.equal(await mobile.locator("#fullscreen-player").isVisible(), false);
  await mobile.locator('[data-track-id="3"]').getByRole("button", { name: "Воспроизвести" }).click(); await waitFor(() => requests.filter((item) => item.path === "/api/player/play").length === 1);
  await mobile.getByRole("button", { name: "Воспроизвести все" }).click(); await waitFor(() => requests.filter((item) => item.path === "/api/player/play").length === 2);
  await mobile.getByRole("button", { name: "Перемешать" }).click(); await waitFor(() => requests.filter((item) => item.path === "/api/player/play").length === 3);
  await mobile.locator("#player").getByRole("button", { name: "Предыдущий трек" }).click(); await waitFor(() => requests.filter((item) => item.path === "/api/player/command").length === 1);
  await mobile.locator("#player").getByRole("button", { name: "Следующий трек" }).click(); await waitFor(() => requests.filter((item) => item.path === "/api/player/command").length === 2);
  await mobile.locator("#player").getByRole("button", { name: "Пауза" }).click(); await waitFor(() => requests.filter((item) => item.path === "/api/player/command").length === 3);
  await mobile.getByLabel("Позиция воспроизведения", { exact: true }).fill("42");
  await mobile.getByLabel("Громкость", { exact: true }).fill("55");
  await waitFor(() => requests.filter((item) => item.path === "/api/player/command").length === 5);
  assert.deepEqual(requests.filter((item) => item.path === "/api/player/play").map((item) => item.body), [
    { track_ids: [3], shuffle: false },
    { track_ids: [3, 2, 1], shuffle: false },
    { track_ids: [3, 2, 1], shuffle: true }
  ]);
  assert.deepEqual(requests.filter((item) => item.path === "/api/player/command").map((item) => item.body), [
    { command: "previous", params: {} }, { command: "next", params: {} },
    { command: "pause", params: {} }, { command: "seek", params: { position: 42 } },
    { command: "volume", params: { volume: 55 } }
  ]);
  console.log("browser smoke: routes/crud/states/player/security/responsive/a11y OK");
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
