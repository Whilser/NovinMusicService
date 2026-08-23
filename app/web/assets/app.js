const API = "/api";
const DEFAULT_PAGE_SIZE = 21;
const CATALOG_ALPHABET = [..."АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"];

const routes = [
  ["home", "Главная", "home"], ["radio", "Радио", "radio"], ["albums", "Альбомы", "albums"],
  ["artists", "Исполнители", "artists"], ["songs", "Песни", "music"],
  ["playlists", "Плейлисты", "playlist"], ["favorites", "Избранное", "heart"],
  ["settings", "Настройки", "settings"]
];
const mobileRoutes = routes;
const initialLocation = locationFromHash();
const state = { route: initialLocation.route, page: initialLocation.page, search: "", tracks: [], catalogTracks: [], playlists: [], selected: initialLocation.selected, player: null, catalogPageSize: DEFAULT_PAGE_SIZE, catalogPageSizeLoaded: false, radioGenre: "All" };
const fullscreenPaletteCache = new Map();
const legacyRadioFavorites = (() => {
  try { const saved = JSON.parse(localStorage.getItem("novin-radio-favorites") || "{}"); return saved && !Array.isArray(saved) ? new Map(Object.entries(saved)) : new Map(); }
  catch { return new Map(); }
})();
const radioFavoriteStations = new Map();
const radioFavorites = new Set(radioFavoriteStations.keys());
const radioStations = new Map();
if (!location.hash) history.replaceState(null, "", "#/home");
const dom = {
  content: document.querySelector("#content"), title: document.querySelector("#page-title"),
  search: document.querySelector("#search"), notice: document.querySelector("#notice"),
  player: document.querySelector("#player"), playerTitle: document.querySelector("#player-title"),
  playerArtist: document.querySelector("#player-artist"), playerCover: document.querySelector("#player-cover"),
  playerState: document.querySelector("#player-state"), elapsed: document.querySelector("#elapsed"),
  duration: document.querySelector("#duration"), seek: document.querySelector("#seek"),
  volume: document.querySelector("#volume"), dialog: document.querySelector("#playlist-dialog"),
  dialogTitle: document.querySelector("#dialog-title"), playlistName: document.querySelector("#playlist-name"), fullscreen: document.querySelector("#fullscreen-player"),
  fullscreenBackdrop: document.querySelector("#fullscreen-backdrop"), fullscreenCover: document.querySelector("#fullscreen-cover"), fullscreenTitle: document.querySelector("#fullscreen-title"),
  fullscreenArtist: document.querySelector("#fullscreen-artist"), fullscreenElapsed: document.querySelector("#fullscreen-elapsed"), fullscreenDuration: document.querySelector("#fullscreen-duration"),
  fullscreenSeek: document.querySelector("#fullscreen-seek"), fullscreenVolume: document.querySelector("#fullscreen-volume"), fullscreenPlay: document.querySelector("#fullscreen-play"),
  playlistSave: document.querySelector("#playlist-save")
};

function element(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(options)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key === "attrs") for (const [name, attr] of Object.entries(value)) node.setAttribute(name, attr);
    else node[key] = value;
  }
  for (const child of children.flat()) if (child) node.append(child);
  return node;
}

function replace(target, ...children) { target.replaceChildren(...children.flat().filter(Boolean)); }
const ICON_PATHS = {
  home: [["path", { d: "M3 10.5 12 3l9 7.5" }], ["path", { d: "M5 9.5V21h14V9.5M9 21v-7h6v7" }]],
  albums: [["rect", { x: "4", y: "3", width: "16", height: "18", rx: "2.5" }], ["path", { d: "M8 8h8M8 12h8M8 16h5" }]],
  artists: [["circle", { cx: "12", cy: "8", r: "4" }], ["path", { d: "M4.5 21c.7-4.2 3.2-6.3 7.5-6.3s6.8 2.1 7.5 6.3" }]],
  radio: [["circle", { cx: "12", cy: "12", r: "2", fill: "currentColor", stroke: "none" }], ["path", { d: "M7.7 7.7a6 6 0 0 0 0 8.6M16.3 7.7a6 6 0 0 1 0 8.6M4.8 4.8a10 10 0 0 0 0 14.4M19.2 4.8a10 10 0 0 1 0 14.4" }]],
  music: [["path", { d: "M9 18V5l10-2v13" }], ["circle", { cx: "6", cy: "18", r: "3" }], ["circle", { cx: "16", cy: "16", r: "3" }]],
  playlist: [["path", { d: "M4 6h10M4 11h10M4 16h7M18 13v7" }], ["circle", { cx: "15.5", cy: "20", r: "2.5" }]],
  heart: [["path", { d: "M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8l1.1 1.1L12 21l7.8-7.5 1.1-1.1a5.5 5.5 0 0 0-.1-7.8Z" }]],
  settings: [["path", { d: "M4 6h10M18 6h2M4 12h2M10 12h10M4 18h7M15 18h5" }], ["circle", { cx: "16", cy: "6", r: "2" }], ["circle", { cx: "8", cy: "12", r: "2" }], ["circle", { cx: "13", cy: "18", r: "2" }]],
  search: [["circle", { cx: "10.5", cy: "10.5", r: "6.5" }], ["path", { d: "m16 16 4.5 4.5" }]],
  play: [["path", { d: "m8 5 11 7-11 7Z", fill: "currentColor", stroke: "none" }]],
  pause: [["path", { d: "M9 5v14M15 5v14", "stroke-width": "3" }]],
  previous: [["path", { d: "M6 5v14M19 6l-10 6 10 6Z", fill: "currentColor", stroke: "none" }]],
  next: [["path", { d: "M18 5v14M5 6l10 6-10 6Z", fill: "currentColor", stroke: "none" }]],
  shuffle: [["path", { d: "M16 3h5v5M4 6h3c5 0 5 12 10 12h4M18 16l3 2-3 3M4 18h3c2.2 0 3.5-2.3 4.7-4.8M14 6.8C15 6.3 16 6 17 6h4" }]],
  volume: [["path", { d: "M11 5 6.5 9H3v6h3.5L11 19ZM15 9a5 5 0 0 1 0 6M17.5 6.5a8.5 8.5 0 0 1 0 11" }]],
  plus: [["path", { d: "M12 5v14M5 12h14" }]],
  close: [["path", { d: "m6 6 12 12M18 6 6 18" }]],
  up: [["path", { d: "m6 15 6-6 6 6" }]],
  down: [["path", { d: "m6 9 6 6 6-6" }]],
  back: [["path", { d: "m14.5 5-7 7 7 7" }]],
  star: [["path", { d: "m12 3 2.8 5.8 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.7l6.2-.9Z" }]],
  more: [["circle", { cx: "5", cy: "12", r: "1.4", fill: "currentColor", stroke: "none" }], ["circle", { cx: "12", cy: "12", r: "1.4", fill: "currentColor", stroke: "none" }], ["circle", { cx: "19", cy: "12", r: "1.4", fill: "currentColor", stroke: "none" }]]
};
function icon(name, size = 18, filled = false, strokeWidth = 1.8) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [key, value] of Object.entries({ viewBox: "0 0 24 24", width: size, height: size, fill: filled ? "currentColor" : "none", stroke: "currentColor", "stroke-width": strokeWidth, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", focusable: "false" })) svg.setAttribute(key, String(value));
  for (const [tag, attrs] of ICON_PATHS[name] || ICON_PATHS.music) { const part = document.createElementNS("http://www.w3.org/2000/svg", tag); for (const [key, value] of Object.entries(attrs)) part.setAttribute(key, value); svg.append(part); }
  return svg;
}
function labeledIcon(name, label) { return [icon(name), element("span", { text: label })]; }
function iconButton(label, iconName, action, data = {}, active = false) { return element("button", { class: `icon-button${active ? " active" : ""}`, dataset: { action, ...data }, attrs: { type: "button", "aria-label": label } }, [icon(iconName, 18, active && iconName === "heart")]); }
replace(document.querySelector(".brand-mark"), icon("music", 18, false, 1.35));
replace(document.querySelector(".search > span[aria-hidden]"), icon("search", 17));
replace(document.querySelector('[data-command="previous"]'), icon("previous", 18));
replace(document.querySelector('[data-command="next"]'), icon("next", 18));
replace(document.querySelector('[data-command="play"]'), icon("play", 17));
replace(document.querySelector(".volume > span[aria-hidden]"), icon("volume", 18));
replace(document.querySelector(".fullscreen-volume > span[aria-hidden]"), icon("volume", 20));
async function withButtonBusy(button, operation) {
  if (!button || button.dataset.busy === "true") return;
  const wasDisabled = button.disabled;
  button.dataset.busy = "true"; button.classList.add("is-busy"); button.disabled = true;
  button.setAttribute("aria-disabled", "true"); button.setAttribute("aria-busy", "true");
  try { return await operation(); }
  finally {
    if (button.isConnected) {
      delete button.dataset.busy; button.classList.remove("is-busy"); button.disabled = wasDisabled;
      button.setAttribute("aria-disabled", String(wasDisabled)); button.removeAttribute("aria-busy");
    }
  }
}
function locationFromHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, queryString = ""] = raw.split("?");
  const parts = path.split("/").filter(Boolean);
  const route = routes.some(([id]) => id === parts[0]) ? parts[0] : "home";
  const query = new URLSearchParams(queryString);
  let selected = null;
  if (route === "playlists" && /^\d+$/.test(parts[1] || "")) selected = { id: Number(parts[1]) };
  const page = Math.max(1, Number(query.get("page")) || 1);
  if ((route === "albums" || route === "artists") && query.get("name")) selected = { type: route === "albums" ? "album" : "artist", name: query.get("name"), albumArtist: query.get("album_artist") || "", returnPage: Math.max(1, Number(query.get("return_page")) || 1) };
  return { route, selected, page };
}
function routePath(route, page = 1) { const query = page > 1 ? `?${new URLSearchParams({ page: String(page) })}` : ""; return `#/${route}${query}`; }
function selectedPath(type, name, albumArtist = "", returnPage = 1) { const query = new URLSearchParams({ name, return_page: String(returnPage) }); if (albumArtist) query.set("album_artist", albumArtist); return `#/${type === "album" ? "albums" : "artists"}?${query}`; }
function formatTime(value) { const seconds = Math.max(0, Number(value) || 0); return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`; }
function pageSize() { return state.catalogPageSize || DEFAULT_PAGE_SIZE; }
async function ensureCatalogPageSize() {
  if (state.catalogPageSizeLoaded) return;
  const settings = await request("/settings").catch(() => ({}));
  state.catalogPageSize = [7, 14, 21, 28, 35, 42, 49].includes(Number(settings.catalog_page_size)) ? Number(settings.catalog_page_size) : DEFAULT_PAGE_SIZE;
  state.catalogPageSizeLoaded = true;
}
function coverUrl(item) { return item.cover_url || (item.cover_id ? `${API}/covers/${encodeURIComponent(item.cover_id)}` : ""); }
function apiMessage(error) { return error?.error?.message || error?.message || "Не удалось выполнить запрос"; }

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  if (response.status === 204) return null;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(apiMessage(body));
  return body;
}

async function fetchAllTracks({ search = "", favorite = "" } = {}) {
  const items = [];
  for (let offset = 0, total = 1; offset < total; offset += 200) {
    const query = new URLSearchParams({ limit: "200", offset: String(offset), search });
    if (favorite) query.set("favorite", favorite);
    const page = await request(`/tracks?${query}`);
    items.push(...page.items); total = page.total;
  }
  return items;
}

async function fetchAllGroups(type) {
  const items = [];
  for (let page = 1, total = 1; items.length < total; page += 1) {
    const result = await request(`/${type}?page=${page}&page_size=200`);
    items.push(...result.items); total = result.total;
  }
  return items;
}

function buildNavigation(target, items) {
  const children = [];
  for (const [id, label, iconName] of items) {
    if (target.id === "sidebar-nav" && id === "home") children.push(element("p", { class: "nav-section-label", text: "Медиатека" }));
    if (target.id === "sidebar-nav" && id === "playlists") children.push(element("p", { class: "nav-section-label", text: "Коллекция" }));
    if (target.id === "sidebar-nav" && id === "settings") children.push(element("p", { class: "nav-section-label", text: "Сервис" }));
    children.push(element("a", {
      class: "nav-item", href: routePath(id), dataset: { route: id }, attrs: state.route === id ? { "aria-current": "page" } : {}
    }, [element("span", { class: "nav-icon", attrs: { "aria-hidden": "true" } }, [icon(iconName, 18)]), element("span", { text: label })]));
  }
  replace(target, children);
}

function loading() { replace(dom.content, element("div", { class: "loading" }, [element("div", { class: "skeleton", attrs: { "aria-label": "Загрузка" } })])); dom.content.setAttribute("aria-busy", "true"); }
function empty(title, text, action) {
  const children = [element("div", { class: "empty-icon", attrs: { "aria-hidden": "true" } }, [icon("music", 44)]), element("h2", { text: title }), element("p", { text })];
  if (action) children.push(element("a", { class: "primary", text: action.label, href: action.href, dataset: { route: action.route } }));
  return element("div", { class: "empty" }, children);
}
function errorView(error) { replace(dom.content, element("div", { class: "error-state" }, [element("h2", { text: "Не удалось загрузить" }), element("p", { text: apiMessage(error) }), element("button", { class: "primary", text: "Повторить", dataset: { action: "retry" }, attrs: { type: "button" } })])); }
function actionError(error) { errorView(error); dom.content.setAttribute("aria-busy", "false"); }
function notify(message) { dom.notice.textContent = message; dom.notice.hidden = false; clearTimeout(notify.timer); notify.timer = setTimeout(() => { dom.notice.hidden = true; }, 4500); }
function section(title, body, actions = []) { return element("section", {}, [element("div", { class: "section-heading" }, [element("h2", { text: title }), ...actions]), body]); }

function cover(item, className = "cover") {
  const box = element("div", { class: className });
  const url = coverUrl(item);
  if (url) box.append(element("img", { src: url, alt: "", loading: "lazy" }));
  else box.append(element("span", { class: "cover-placeholder", attrs: { "aria-hidden": "true" } }, [icon("music", className === "row-cover" ? 20 : 42)]));
  if (!url && item.artist_image) {
    deferArtistArtwork(box, item.artist_image, item.artist_image_status);
  }
  return box;
}

function artistCollageUrl(artist) {
  return `${API}/artists/collage?${new URLSearchParams({ name: artist })}`;
}

function deferArtistArtwork(box, artist, imageStatus) {
  const runWhenIdle = window.requestIdleCallback || ((callback) => window.setTimeout(callback, 0));
  runWhenIdle(() => {
    if (!box.isConnected) return;
    if (imageStatus === "missing") {
      box.replaceChildren(element("img", { src: artistCollageUrl(artist), alt: "", loading: "lazy" }));
      return;
    }
    queueArtistImage(box, artist);
  }, { timeout: 1200 });
}

const artistImageQueue = [];
let artistImageRequests = 0;
function queueArtistImage(box, artist) {
  artistImageQueue.push(async () => {
    if (!box.isConnected) return;
    try {
      const response = await fetch(`${API}/artists/image?${new URLSearchParams({ name: artist })}`);
      if (response.status === 204) {
        if (box.isConnected) box.replaceChildren(element("img", { src: artistCollageUrl(artist), alt: "", loading: "lazy" }));
        return;
      }
      if (!response.ok || !response.headers.get("content-type")?.startsWith("image/")) return;
      const image = element("img", { src: URL.createObjectURL(await response.blob()), alt: "", loading: "lazy" });
      box.replaceChildren(image);
    } catch (_) { /* The placeholder remains when Wikimedia is unavailable. */ }
  });
  runArtistImageQueue();
}
function runArtistImageQueue() {
  while (artistImageRequests < 2 && artistImageQueue.length) {
    artistImageRequests += 1;
    artistImageQueue.shift()().finally(() => { artistImageRequests -= 1; runArtistImageQueue(); });
  }
}

function albumCard(item, type = "album") {
  const name = item.name || item.album || "Без названия";
  const albumArtist = item.album_artist || "";
  const cardItem = type === "artist" ? { ...item, artist_image: item.name } : item;
  return element("article", { class: "card" }, [
    element("button", { class: "cover-button", dataset: { action: "select-group", type, name, albumArtist, returnPage: String(state.page) }, attrs: { type: "button", "aria-label": `Открыть ${name}`, style: "display:block;width:100%;padding:0;border:0;background:transparent;text-align:left;cursor:pointer" } }, [cover(cardItem)]),
    element("h3", { text: name }), element("p", { text: item.artist || item.album_artist || `${item.track_count || 0} треков` })
  ]);
}

function isPlayingTrack(track) {
  const file = state.player?.song?.file;
  return state.player?.state === "play" && Boolean(file) && (file === track.path || file.endsWith(`/${track.path}`));
}

function trackRow(track, options = {}) {
  const row = element("article", { class: `track-row${options.compact ? " compact" : ""}`, dataset: { trackId: String(track.id) } });
  const image = cover(track, "row-cover");
  const playing = isPlayingTrack(track);
  const playOne = iconButton(playing ? "Пауза" : "Воспроизвести", playing ? "pause" : "play", playing ? "pause-track" : "play-one", { id: String(track.id) }); playOne.classList.add("track-play");
  const info = element("div", { class: "track-title" }, [element("strong", { text: track.title || "Без названия" }), element("span", { text: track.artist || "Неизвестный исполнитель" })]);
  row.append(image, playOne, info, element("span", { class: "track-album", text: track.album || "Неизвестный альбом" }));
  const rating = element("div", { class: "rating", attrs: { "aria-label": `Оценка ${track.title}` } });
  for (let value = 1; value <= 5; value += 1) rating.append(element("button", { class: value <= (track.rating || 0) ? "active" : "", dataset: { action: "rate", value: String(value), id: String(track.id) }, attrs: { type: "button", "aria-label": `${value} из 5` } }, [icon("star", 14, value <= (track.rating || 0))]));
  row.append(rating, iconButton(track.favorite ? "Убрать из избранного" : "Добавить в избранное", "heart", "favorite", { id: String(track.id), active: String(!track.favorite) }, Boolean(track.favorite)));
  const actions = element("div", { class: "reorder" });
  if (options.playlistId) {
    actions.append(iconButton("Выше", "up", "move-track", { id: String(track.id), direction: "up" }), iconButton("Ниже", "down", "move-track", { id: String(track.id), direction: "down" }), iconButton("Удалить из плейлиста", "close", "remove-track", { id: String(track.id), playlistId: String(options.playlistId) }));
  } else actions.append(iconButton("Добавить в плейлист", "plus", "add-to-playlist", { id: String(track.id) }));
  row.append(actions);
  return row;
}

function trackList(items, options = {}) { return element("div", { class: `track-list${options.compact ? " compact" : ""}` }, items.map((track) => trackRow(track, options))); }
function playButtons(items) {
  if (!items.length) return [];
  const ids = items.map((item) => item.id).join(",");
  return [element("button", { class: "media-action", dataset: { action: "play-list", ids }, attrs: { type: "button", "aria-label": "Воспроизвести все" } }, labeledIcon("play", "Воспроизвести")), element("button", { class: "secondary media-action", dataset: { action: "shuffle-list", ids }, attrs: { type: "button" } }, labeledIcon("shuffle", "Перемешать"))];
}
function pagination(total) {
  const pages = Math.max(1, Math.ceil(total / pageSize()));
  if (pages === 1) return null;
  const visible = pages <= 7 ? Array.from({ length: pages }, (_, index) => index + 1) : state.page <= 4 ? [1, 2, 3, 4, "…", pages] : state.page >= pages - 3 ? [1, "…", pages - 3, pages - 2, pages - 1, pages] : [1, "…", state.page - 1, state.page, state.page + 1, "…", pages];
  const pageLinks = visible.map((page) => page === "…" ? element("span", { class: "pagination-ellipsis", text: "…", attrs: { "aria-hidden": "true" } }) : element("button", { class: `page-number${page === state.page ? " active" : ""}`, text: String(page), disabled: page === state.page, dataset: { action: "page", page: String(page) }, attrs: { type: "button", "aria-label": `Страница ${page}`, "aria-current": page === state.page ? "page" : null } }));
  return element("nav", { class: "pagination", attrs: { "aria-label": "Страницы" } }, [
    element("button", { text: "Назад", disabled: state.page <= 1, dataset: { action: "page", page: String(state.page - 1) }, attrs: { type: "button" } }), ...pageLinks,
    element("button", { text: "Дальше", disabled: state.page >= pages, dataset: { action: "page", page: String(state.page + 1) }, attrs: { type: "button" } })
  ]);
}

function alphabetIndex(items, field, pages = {}) {
  const available = new Set(items.map((item) => alphabetLetter(item[field])));
  const letters = CATALOG_ALPHABET.filter((letter) => available.has(letter));
  if (!letters.length) return null;
  return element("nav", { class: "alphabet-index", attrs: { "aria-label": "Быстрый переход по алфавиту" } }, letters.map((letter) => element("button", {
    text: letter, dataset: { action: "alphabet-jump", letter, page: String(pages[letter] || "") }, attrs: { type: "button", "aria-label": `Перейти к букве ${letter}` }
  })));
}

function alphabetLetter(value) { return String(value || "").trim().charAt(0).toUpperCase(); }

async function alphabetItems() {
  const favorite = state.route === "favorites" ? "true" : "";
  if (state.route === "albums" || state.route === "artists") return fetchAllGroups(state.route);
  return fetchAllTracks({ search: state.search, favorite });
}

async function loadTracks(extra = "") {
  const offset = (state.page - 1) * pageSize();
  const query = new URLSearchParams({ limit: String(pageSize()), offset: String(offset), search: state.search });
  if (extra) query.set("favorite", extra);
  return request(`/tracks?${query}`);
}

async function renderHome() {
  const allTracks = await fetchAllTracks();
  const albums = await request("/albums/recent?limit=7");
  state.catalogTracks = allTracks; state.tracks = [...allTracks].sort((left, right) => Number(right.id) - Number(left.id)).slice(0, 12);
  if (!allTracks.length) { replace(dom.content, empty("Ваша медиатека пока пуста", "Настройте сетевую папку и запустите первое сканирование.", { label: "Открыть настройки", href: routePath("settings"), route: "settings" })); return; }
  const favorites = allTracks.filter((item) => item.favorite);
  replace(dom.content,
    section("Недавно добавлено", trackList(state.tracks), playButtons(state.tracks)),
    albums.length ? section("Альбомы", element("div", { class: "grid" }, albums.map((item) => albumCard(item)))) : null,
    favorites.length ? section("Избранное", trackList(favorites)) : null
  );
}

async function renderGroups(type) {
  await ensureCatalogPageSize();
  const title = type === "albums" ? "Альбомы" : "Исполнители";
  const groupsQuery = new URLSearchParams({ page: String(state.page), page_size: String(pageSize()), search: state.search });
  const initialsQuery = new URLSearchParams({ kind: type, search: state.search, page_size: String(pageSize()) });
  const [result, initials] = await Promise.all([request(`/${type}?${groupsQuery}`), request(`/catalog/initials?${initialsQuery}`)]);
  if (!result.items.length) replace(dom.content, empty(state.search ? "Ничего не найдено" : `Нет данных: ${title.toLowerCase()}`, state.search ? "Попробуйте изменить запрос." : "Запустите сканирование в настройках."));
  else replace(dom.content, element("div", { class: "grid catalog-grid" }, result.items.map((item) => albumCard(item, type === "albums" ? "album" : "artist"))), pagination(result.total), alphabetIndex(initials.items.map((letter) => ({ letter })), "letter", initials.pages));
}

function radioCard(station, index) {
  const palettes = ["rose", "gold", "blue", "teal", "violet", "coral"];
  return element("article", { class: `radio-card radio-card--${palettes[index % palettes.length]}` }, [
    element("button", { dataset: { action: "play-radio", id: station.id }, attrs: { type: "button", "aria-label": `Воспроизвести ${station.name}` } }, [
      element("span", { class: "radio-card-label", text: station.genre || "Shoutcast" }),
      element("strong", { text: station.name }),
      element("span", { class: "radio-card-now", text: station.now_playing || "Shoutcast Radio" }),
      element("span", { class: "radio-card-play" }, [icon("play", 20)])
    ]),
    element("div", { class: "radio-card-footer" }, [element("p", { text: `${station.listeners ? `${station.listeners.toLocaleString("ru-RU")} слушателей` : "Онлайн-станция"}${station.bitrate ? ` · ${station.bitrate} kbps` : ""}` }), iconButton(radioFavorites.has(station.id) ? "Убрать из избранного" : "В избранное", "heart", "radio-favorite", { id: station.id }, radioFavorites.has(station.id))])
  ]);
}

async function loadRadioFavorites() {
  if (legacyRadioFavorites.size) {
    await Promise.all([...legacyRadioFavorites.values()].filter((station) => station?.id && station?.name && station?.stream_url).map((station) => request(`/radio/stations/${encodeURIComponent(station.id)}/favorite`, { method: "PUT", body: JSON.stringify({ station, favorite: true }) }).catch(() => null)));
    legacyRadioFavorites.clear(); localStorage.removeItem("novin-radio-favorites");
  }
  const saved = await request("/radio/favorites").catch(() => []);
  radioFavorites.clear(); radioFavoriteStations.clear();
  saved.forEach((station) => { radioFavorites.add(station.id); radioFavoriteStations.set(station.id, station); radioStations.set(station.id, station); });
  return saved;
}

async function renderRadio(refresh = false) {
  const query = new URLSearchParams({ genre: state.radioGenre, limit: "24" });
  if (refresh) query.set("refresh", "true");
  if (state.search) query.set("search", state.search);
  const [result] = await Promise.all([request(`/radio?${query}`), loadRadioFavorites()]);
  result.stations.forEach((station) => radioStations.set(station.id, station));
  const sourceLabel = result.source === "shoutcast" ? "SHOUTCAST · PARTNER API" : result.source === "local" ? "ЛОКАЛЬНЫЙ КАТАЛОГ · СОХРАНЁННЫЕ СТАНЦИИ" : "RADIO BROWSER · ОТКРЫТЫЙ КАТАЛОГ";
  const genres = element("div", { class: "radio-genres", attrs: { "aria-label": "Жанры радио" } }, result.genres.map((genre) => element("button", {
    class: genre === result.genre ? "active" : "", text: genre === "All" ? "Все" : genre === "Russian" ? "Русские" : genre, dataset: { action: "radio-genre", genre }, attrs: { type: "button" }
  })));
  const intro = element("section", { class: "radio-hero" }, [
    element("p", { text: sourceLabel }), element("h2", { text: state.search ? `Результаты поиска: ${state.search}` : "Радио" }),
    element("span", { text: "Выберите станцию — она будет загружена во временную очередь MPD." })
  ]);
  const sectionTitle = result.genre === "All" ? "Все станции" : `Станции: ${result.genre}`;
  replace(dom.content, intro, genres, result.stations.length ? element("section", { class: "radio-section" }, [element("h2", { text: state.search ? "Станции" : sectionTitle }), element("div", { class: "radio-grid" }, result.stations.map(radioCard))]) : empty("Станции не найдены", "Выберите другой жанр или измените запрос."));
}

async function renderSongs(favorite = false) {
  const result = await loadTracks(favorite ? "true" : "");
  state.tracks = result.items;
  if (!result.items.length) replace(dom.content, empty(state.search ? "Ничего не найдено" : favorite ? "Избранное пока пусто" : "В медиатеке нет песен", favorite ? "Отмечайте любимые треки сердцем — они появятся здесь." : "Запустите сканирование в настройках."));
  else {
    const query = new URLSearchParams({ kind: "songs", search: state.search });
    if (favorite) query.set("favorite", "true");
    const initials = await request(`/catalog/initials?${query}`);
    replace(dom.content, element("div", { class: "page-actions" }, [element("span", { text: `${result.total} треков` }), ...playButtons(result.items)]), trackList(result.items), pagination(result.total), alphabetIndex(initials.items.map((letter) => ({ letter })), "letter"));
  }
}

async function renderFavorites() {
  const result = await loadTracks(true); state.tracks = result.items;
  const stations = await loadRadioFavorites();
  replace(dom.content,
    stations.length ? section("Радиостанции", element("div", { class: "radio-grid" }, stations.map(radioCard))) : null,
    result.items.length ? section("Песни", trackList(result.items)) : null,
    !stations.length && !result.items.length ? empty("Избранное пока пусто", "Добавляйте любимые песни сердцем или сохраняйте радиостанции.") : null
  );
}

async function renderSelectedGroup(type, name, albumArtist = "") {
  const allMatches = await fetchAllTracks({ search: name });
  const key = type === "album" ? "album" : "artist";
  const items = allMatches.filter((item) => item[key] === name);
  state.tracks = items; state.selected = { type, name, albumArtist, returnPage: state.selected?.returnPage || 1 };
  dom.title.textContent = name;
  const representative = items[0] || { album: name, artist: albumArtist };
  const subtitle = type === "album" ? (albumArtist || representative.artist || "Неизвестный исполнитель") : "Исполнитель";
  const listRoute = type === "album" ? "albums" : "artists";
  const detail = element("section", { class: "detail-hero" }, [
    cover(representative, "detail-cover"),
    element("div", { class: "detail-copy" }, [
      element("p", { class: "detail-kind", text: type === "album" ? "Альбом" : "Исполнитель" }),
      element("h2", { text: name }),
      element("p", { class: "detail-artist", text: subtitle }),
      element("p", { class: "detail-meta", text: `${items.length} ${items.length === 1 ? "песня" : "песен"}` }),
      element("div", { class: "detail-actions" }, playButtons(items))
    ])
  ]);
  const back = element("button", { class: "detail-back", dataset: { action: "back-group", route: listRoute, page: String(state.selected?.returnPage || 1) }, attrs: { type: "button", "aria-label": `Назад к списку: ${listRoute === "albums" ? "альбомы" : "исполнители"}` } }, [icon("back", 26)]);
  const topbar = dom.title.closest(".topbar");
  topbar.classList.add("has-detail-back");
  topbar.insertBefore(back, dom.title.parentElement);
  replace(dom.content, detail, items.length ? trackList(items, { compact: true }) : empty("Треки не найдены", "Вернитесь к медиатеке и попробуйте снова."));
}

async function renderPlaylists() {
  state.playlists = await request("/playlists");
  const create = element("button", { text: "+ Новый плейлист", dataset: { action: "create-playlist" }, attrs: { type: "button" } });
  if (!state.playlists.length) replace(dom.content, element("div", { class: "page-actions" }, [element("span", { text: "Локальные плейлисты" }), create]), empty("Пока нет плейлистов", "Создайте подборку и добавляйте в неё треки из медиатеки."));
  else replace(dom.content, element("div", { class: "page-actions" }, [element("span", { text: `${state.playlists.length} плейлистов` }), create]), element("div", { class: "grid" }, state.playlists.map((item) => element("article", { class: "card" }, [element("button", { class: "cover-button", dataset: { action: "open-playlist", id: String(item.id) }, attrs: { type: "button", "aria-label": `Открыть ${item.name}`, style: "display:block;width:100%;padding:0;border:0;background:transparent;text-align:left;cursor:pointer" } }, [cover(item)]), element("h3", { text: item.name }), element("p", { text: `${item.track_count || 0} треков` })]))));
}

async function renderPlaylist(id) {
  const playlist = await request(`/playlists/${id}`);
  state.selected = playlist; state.tracks = playlist.tracks || [];
  dom.title.textContent = playlist.name;
  const actions = element("div", { class: "page-actions" }, [element("div", {}, playButtons(state.tracks)), element("div", {}, [element("button", { class: "secondary", text: "Переименовать", dataset: { action: "rename-playlist", id: String(id), name: playlist.name }, attrs: { type: "button" } }), element("button", { class: "secondary", text: "Удалить", dataset: { action: "delete-playlist", id: String(id) }, attrs: { type: "button" } })])]);
  replace(dom.content, actions, state.tracks.length ? trackList(state.tracks, { playlistId: id }) : empty("Плейлист пуст", "Добавьте песни кнопкой «+» в медиатеке."));
}

function field(name, label, value, type = "text") { return element("label", {}, [element("span", { text: label }), element("input", { name, value: value || "", type, autocomplete: "off" })]); }
function selectField(name, label, value, options) {
  const select = element("select", { name }, options.map((option) => element("option", { value: String(option), text: `${option} обложки` })));
  select.value = value || String(DEFAULT_PAGE_SIZE);
  return element("label", {}, [element("span", { text: label }), select]);
}
function serviceHeading(title, tone, statusText) {
  return element("h2", { class: "service-heading" }, [element("span", { text: title }), element("span", { class: `service-status service-status--${tone}`, attrs: { role: "status", "aria-label": statusText } })]);
}
async function renderSettings() {
  const settings = await request("/settings");
  state.catalogPageSize = [7, 14, 21, 28, 35, 42, 49].includes(Number(settings.catalog_page_size)) ? Number(settings.catalog_page_size) : DEFAULT_PAGE_SIZE;
  state.catalogPageSizeLoaded = true;
  const share = await request("/share/status").catch(() => ({ state: "error" }));
  const player = await request("/player/status").catch(() => ({ online: false }));
  const scan = await request("/scan/status");
  const authentication = share.authentication === "credentials" ? "логин и пароль из .env" : share.authentication === "guest" ? "guest" : "ещё не проверялась";
  const smbTone = share.state === "connected" ? "green" : share.state === "not_configured" ? "red" : "yellow";
  const mpdTone = player.online ? "green" : (settings.mpd_host || settings.mpd_port ? "yellow" : "red");
  const smb = element("form", { class: "settings-card", dataset: { form: "smb" } }, [serviceHeading("Сетевая папка SMB", smbTone, `SMB: ${share.state === "connected" ? "подключено" : share.state === "not_configured" ? "не настроено" : "оффлайн"}`), element("p", { text: `Статус: ${share.state || "не настроено"} · Авторизация: ${authentication}` }), element("div", { class: "field-grid" }, [field("smb_host", "Адрес NAS", settings.smb_host), field("smb_share", "Имя шары", settings.smb_share), field("smb_domain", "Домен (необязательно)", settings.smb_domain), field("smb_options", "Дополнительные опции", settings.smb_options)]), element("div", { class: "button-row" }, [element("button", { class: "primary", text: "Применить и проверить", type: "submit" })])]);
  const mpd = element("form", { class: "settings-card", dataset: { form: "mpd" } }, [serviceHeading("MPD", mpdTone, `MPD: ${player.online ? "подключён" : mpdTone === "red" ? "не настроен" : "оффлайн"}`), element("p", { text: "Пароль, если нужен, задаётся только переменной MPD_PASSWORD." }), element("div", { class: "field-grid" }, [field("mpd_host", "Host", settings.mpd_host || "host.docker.internal"), field("mpd_port", "Port", settings.mpd_port || "6600", "number"), field("mpd_uri_prefix", "URI-префикс", settings.mpd_uri_prefix)]), element("div", { class: "button-row" }, [element("button", { class: "primary", text: "Сохранить и проверить", type: "submit" })])]);
  const counters = scan.counters || {}; const progress = scan.state === "running" ? Math.min(95, (counters.discovered || 0) ? 55 + (counters.indexed || 0) / counters.discovered * 40 : 15) : scan.state === "completed" ? 100 : 0;
  const appearance = element("form", { class: "settings-card", dataset: { form: "appearance" } }, [element("h2", { text: "Отображение" }), element("p", { text: "Количество карточек на одной странице разделов «Альбомы» и «Исполнители»." }), element("div", { class: "field-grid" }, [selectField("catalog_page_size", "Обложек на странице", String(state.catalogPageSize), [7, 14, 21, 28, 35, 42, 49])]), element("div", { class: "button-row" }, [element("button", { class: "primary", text: "Сохранить", type: "submit" })])]);
  const scanner = element("section", { class: "settings-card" }, [element("h2", { text: "Сканирование медиатеки" }), element("p", { text: scan.error?.message || `Статус: ${scan.state || "не запускалось"}` }), element("div", { class: "scan-progress", attrs: { role: "progressbar", "aria-valuenow": String(Math.round(progress)), "aria-valuemin": "0", "aria-valuemax": "100" } }, [element("span", { attrs: { style: `width:${progress}%` } })]), element("p", { text: `Найдено ${counters.discovered || 0} · добавлено ${counters.indexed || 0} · пропущено ${(counters.unreadable || 0) + (counters.unsupported || 0)}` }), element("button", { class: scan.state === "running" ? "primary is-busy" : "primary", text: scan.state === "running" ? "Сканирование…" : "Пересканировать", disabled: scan.state === "running", dataset: { action: "scan", ...(scan.state === "running" ? { busy: "true" } : {}) }, attrs: { type: "button", ...(scan.state === "running" ? { "aria-busy": "true", "aria-disabled": "true" } : {}) } })]);
  replace(dom.content, element("div", { class: "settings-grid" }, [smb, mpd, appearance, scanner]));
  clearTimeout(renderSettings.pollTimer);
  if (scan.state === "running") renderSettings.pollTimer = setTimeout(() => { if (state.route === "settings") renderSettings().catch(errorView); }, 1000);
}

async function render() {
  loading(); const topbar = dom.title.closest(".topbar"); topbar.querySelector(".detail-back")?.remove(); topbar.classList.remove("has-detail-back"); dom.title.textContent = routes.find(([id]) => id === state.route)?.[1] || "Медиатека"; dom.search.hidden = state.route === "settings"; dom.content.setAttribute("aria-busy", "true");
  buildNavigation(document.querySelector("#sidebar-nav"), routes); buildNavigation(document.querySelector("#mobile-nav"), mobileRoutes);
  try {
    if (state.route === "home") await renderHome();
    else if (state.route === "radio") await renderRadio();
    else if ((state.route === "albums" || state.route === "artists") && state.selected?.type) await renderSelectedGroup(state.selected.type, state.selected.name, state.selected.albumArtist);
    else if (state.route === "albums" || state.route === "artists") await renderGroups(state.route);
    else if (state.route === "songs") await renderSongs(false);
    else if (state.route === "favorites") await renderFavorites();
    else if (state.route === "playlists" && state.selected?.id) await renderPlaylist(state.selected.id);
    else if (state.route === "playlists") await renderPlaylists();
    else if (state.route === "settings") await renderSettings();
  } catch (error) { errorView(error); }
  dom.content.setAttribute("aria-busy", "false");
}

async function setPreference(id, change) {
  const item = state.tracks.find((track) => track.id === Number(id)); if (!item) return;
  const previous = { rating: item.rating, favorite: item.favorite }; Object.assign(item, change);
  try { Object.assign(item, await request(`/tracks/${id}/preference`, { method: "PUT", body: JSON.stringify(change) })); }
  catch (error) { Object.assign(item, previous); notify(apiMessage(error)); }
  if (state.selected?.tracks) state.selected.tracks = state.tracks; await redrawCurrent();
}
async function redrawCurrent() {
  if (state.selected?.id && state.route === "playlists") await renderPlaylist(state.selected.id);
  else if (state.selected?.type) await renderSelectedGroup(state.selected.type, state.selected.name, state.selected.albumArtist);
  else if (state.route === "songs") await renderSongs(false); else if (state.route === "favorites") await renderFavorites(); else await render();
}
async function play(ids, shuffle = false) { try { await request("/player/play", { method: "POST", body: JSON.stringify({ track_ids: ids.map(Number), shuffle }) }); await pollPlayer(); } catch (error) { notify(apiMessage(error)); } }
async function playFromTrack(id) {
  const trackId = Number(id);
  if (!state.selected || !["album", "artist"].includes(state.selected.type)) return play([trackId]);
  const index = state.tracks.findIndex((track) => track.id === trackId);
  return play((index < 0 ? [trackId] : state.tracks.slice(index).map((track) => track.id)));
}
async function command(name, params = {}) { try { await request("/player/command", { method: "POST", body: JSON.stringify({ command: name, params }) }); await pollPlayer(); } catch (error) { notify(apiMessage(error)); } }

function syncTrackPlayButtons() {
  document.querySelectorAll(".track-play").forEach((button) => {
    const track = state.tracks.find((item) => item.id === Number(button.dataset.id));
    const playing = track && isPlayingTrack(track);
    button.dataset.action = playing ? "pause-track" : "play-one";
    button.setAttribute("aria-label", playing ? "Пауза" : "Воспроизвести");
    replace(button, icon(playing ? "pause" : "play", 18));
  });
}

function openPlaylistDialog(mode, data = {}) { dom.dialog.dataset.mode = mode; dom.dialog.dataset.id = data.id || ""; dom.dialogTitle.textContent = mode === "rename" ? "Переименовать плейлист" : "Новый плейлист"; dom.playlistName.value = data.name || ""; dom.dialog.showModal(); dom.playlistName.focus(); }
async function savePlaylist(event) { event.preventDefault(); const name = dom.playlistName.value.trim(); if (!name) return; await withButtonBusy(event.submitter || dom.playlistSave, async () => { try { if (dom.dialog.dataset.mode === "rename") { const id = Number(dom.dialog.dataset.id); await request(`/playlists/${id}`, { method: "PATCH", body: JSON.stringify({ name }) }); dom.dialog.close(); state.selected = { id }; await renderPlaylist(id); } else { await request("/playlists", { method: "POST", body: JSON.stringify({ name }) }); dom.dialog.close(); state.selected = null; await render(); } } catch (error) { notify(apiMessage(error)); } }); }

document.addEventListener("click", async (event) => {
  const routeLink = event.target.closest("[data-route]:not([data-action])");
  if (routeLink) { event.preventDefault(); const next = routePath(routeLink.dataset.route); if (location.hash === next) { state.selected = null; state.page = 1; await render(); } else location.hash = next; return; }
  const button = event.target.closest("[data-action]"); if (!button) return;
  await withButtonBusy(button, async () => { const action = button.dataset.action;
  if (action === "retry") await render();
  else if (action === "page") { state.page = Number(button.dataset.page); await render(); document.querySelector("#main").focus({ focusVisible: false }); }
  else if (action === "alphabet-jump") {
    const page = Number(button.dataset.page);
    if (page > 0) { state.page = page; await render(); document.querySelector("#main").focus({ focusVisible: false }); return; }
    const items = await alphabetItems();
    const field = state.route === "songs" || state.route === "favorites" ? "artist" : "name";
    const index = items.findIndex((item) => alphabetLetter(item[field]) === button.dataset.letter);
    if (index < 0) notify(`Для буквы «${button.dataset.letter}» ничего не найдено`);
    else { state.page = Math.floor(index / pageSize()) + 1; await render(); document.querySelector("#main").focus({ focusVisible: false }); }
  }
  else if (action === "back-group") { state.selected = null; const next = routePath(button.dataset.route, Number(button.dataset.page) || 1); if (location.hash === next) await render(); else location.hash = next; }
  else if (action === "select-group") { const next = selectedPath(button.dataset.type, button.dataset.name, button.dataset.albumArtist, Number(button.dataset.returnPage) || 1); if (location.hash === next) await renderSelectedGroup(button.dataset.type, button.dataset.name, button.dataset.albumArtist); else location.hash = next; }
  else if (action === "favorite") await setPreference(button.dataset.id, { favorite: button.dataset.active === "true" });
  else if (action === "rate") { const item = state.tracks.find((track) => track.id === Number(button.dataset.id)); await setPreference(button.dataset.id, { rating: item?.rating === Number(button.dataset.value) ? 0 : Number(button.dataset.value) }); }
  else if (action === "play-one") await playFromTrack(button.dataset.id);
  else if (action === "radio-genre") { state.radioGenre = button.dataset.genre; await renderRadio(true); }
  else if (action === "radio-favorite") { const station = radioStations.get(button.dataset.id); if (!station) { notify("Станция не найдена в локальном каталоге"); return; } try { await request(`/radio/stations/${encodeURIComponent(station.id)}/favorite`, { method: "PUT", body: JSON.stringify({ station, favorite: !radioFavorites.has(station.id) }) }); await (state.route === "favorites" ? renderFavorites() : renderRadio()); } catch (error) { notify(apiMessage(error)); } }
  else if (action === "play-radio") { try { await request("/radio/play", { method: "POST", body: JSON.stringify({ station_id: button.dataset.id }) }); await pollPlayer(); notify("Станция загружена в MPD"); } catch (error) { notify(apiMessage(error)); } }
  else if (action === "pause-track") await command("pause");
  else if (action === "play-list" || action === "shuffle-list") await play(button.dataset.ids.split(","), action === "shuffle-list");
  else if (action === "create-playlist") openPlaylistDialog("create");
  else if (action === "rename-playlist") openPlaylistDialog("rename", button.dataset);
  else if (action === "open-playlist") { const next = `#/playlists/${button.dataset.id}`; if (location.hash === next) { state.selected = { id: Number(button.dataset.id) }; await renderPlaylist(Number(button.dataset.id)); } else location.hash = next; }
  else if (action === "delete-playlist") { if (confirm("Удалить этот плейлист?")) { try { await request(`/playlists/${button.dataset.id}`, { method: "DELETE" }); location.hash = "#/playlists"; } catch (error) { actionError(error); } } }
  else if (action === "remove-track") { try { await request(`/playlists/${button.dataset.playlistId}/tracks/${button.dataset.id}`, { method: "DELETE" }); await renderPlaylist(Number(button.dataset.playlistId)); } catch (error) { actionError(error); } }
  else if (action === "move-track") { const index = state.tracks.findIndex((track) => track.id === Number(button.dataset.id)); const target = index + (button.dataset.direction === "up" ? -1 : 1); if (target >= 0 && target < state.tracks.length) { const order = state.tracks.map((track) => track.id); [order[index], order[target]] = [order[target], order[index]]; try { await request(`/playlists/${state.selected.id}/tracks`, { method: "PUT", body: JSON.stringify({ track_ids: order }) }); await renderPlaylist(state.selected.id); } catch (error) { actionError(error); } } }
  else if (action === "add-to-playlist") { try { const playlists = await request("/playlists"); if (!playlists.length) { notify("Сначала создайте плейлист"); return; } const names = playlists.map((item, index) => `${index + 1}. ${item.name}`).join("\n"); const choice = Number(prompt(`Выберите номер плейлиста:\n${names}`)); const selected = playlists[choice - 1]; if (selected) { await request(`/playlists/${selected.id}/tracks`, { method: "POST", body: JSON.stringify({ track_id: Number(button.dataset.id) }) }); notify(`Добавлено в «${selected.name}»`); } } catch (error) { actionError(error); } }
  else if (action === "scan") { try { await request("/scan", { method: "POST" }); notify("Сканирование запущено"); await renderSettings(); } catch (error) { notify(apiMessage(error)); } }
  });
});

document.addEventListener("submit", async (event) => {
  const form = event.target.closest("[data-form]"); if (!form) return; event.preventDefault(); const values = Object.fromEntries(new FormData(form));
  await withButtonBusy(event.submitter || form.querySelector('button[type="submit"]'), async () => { try {
    if (form.dataset.form === "smb") { await request("/share", { method: "POST", body: JSON.stringify({ host: values.smb_host, share: values.smb_share, domain: values.smb_domain, options: values.smb_options }) }); notify("SMB подключён"); }
    else if (form.dataset.form === "appearance") { await request("/settings", { method: "PATCH", body: JSON.stringify(values) }); state.catalogPageSize = Number(values.catalog_page_size); state.catalogPageSizeLoaded = true; state.page = 1; notify("Количество обложек сохранено"); }
    else { await request("/settings", { method: "PATCH", body: JSON.stringify(values) }); const result = await request("/settings/test-mpd", { method: "POST" }); notify(result.online ? "MPD доступен" : "MPD не отвечает"); }
    await renderSettings();
  } catch (error) { notify(apiMessage(error)); } });
});

dom.dialog.querySelector("form").addEventListener("submit", savePlaylist);
document.querySelector("#playlist-cancel").addEventListener("click", () => dom.dialog.close());
document.querySelector("[data-skip-link]").addEventListener("click", (event) => { event.preventDefault(); document.querySelector("#main").focus(); });
dom.search.addEventListener("input", () => { clearTimeout(dom.search.timer); dom.search.timer = setTimeout(async () => { state.search = dom.search.value.trim(); state.page = 1; state.selected = null; await render(); }, 280); });
window.addEventListener("hashchange", async () => { const next = locationFromHash(); state.route = next.route; state.selected = next.selected; state.page = next.page; await render(); });
document.querySelector(".transport").addEventListener("click", async (event) => { const button = event.target.closest("[data-command]"); if (!button) return; await withButtonBusy(button, async () => { const name = button.dataset.command === "play" && state.player?.state === "play" ? "pause" : button.dataset.command; await command(name); }); });
dom.seek.addEventListener("change", () => command("seek", { position: Number(dom.seek.value) }));
dom.volume.addEventListener("change", () => command("volume", { volume: Number(dom.volume.value) }));
dom.playerCover.addEventListener("click", openFullscreenPlayer);
document.querySelector("#fullscreen-close").addEventListener("click", closeFullscreenPlayer);
dom.fullscreenBackdrop.addEventListener("click", closeFullscreenPlayer);
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !dom.fullscreen.hidden) closeFullscreenPlayer(); });
dom.fullscreen.querySelector(".fullscreen-controls").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-fullscreen-command]"); if (!button) return;
  await withButtonBusy(button, async () => { const name = button.dataset.fullscreenCommand === "play" && state.player?.state === "play" ? "pause" : button.dataset.fullscreenCommand; await command(name); });
});
dom.fullscreenSeek.addEventListener("change", () => command("seek", { position: Number(dom.fullscreenSeek.value) }));
dom.fullscreenVolume.addEventListener("change", () => command("volume", { volume: Number(dom.fullscreenVolume.value) }));

async function resolvePlayerTrack(song) {
  if (!song) return null;
  if (/^https?:\/\//i.test(song.file || "")) return null;
  if (!state.catalogTracks.length) state.catalogTracks = await fetchAllTracks();
  return state.catalogTracks.find((track) => track.path === song.file)
    || state.catalogTracks.find((track) => song.file && song.file.endsWith(`/${track.path}`))
    || null;
}

function setFullscreenCover(url) {
  replace(dom.fullscreenCover); replace(dom.fullscreenBackdrop);
  if (!url) { dom.fullscreenCover.append(icon("music", 88)); dom.fullscreen.style.removeProperty("--fullscreen-primary"); dom.fullscreen.style.removeProperty("--fullscreen-secondary"); return; }
  const cover = element("img", { src: url, alt: "" });
  dom.fullscreenCover.append(cover);
  dom.fullscreenBackdrop.append(element("img", { src: url, alt: "" }));
  applyFullscreenPalette(url, cover);
}

function applyFullscreenPalette(url, image) {
  const apply = (palette) => { dom.fullscreen.style.setProperty("--fullscreen-primary", palette[0]); dom.fullscreen.style.setProperty("--fullscreen-secondary", palette[1]); };
  if (fullscreenPaletteCache.has(url)) { apply(fullscreenPaletteCache.get(url)); return; }
  image.addEventListener("load", () => {
    try {
      const canvas = document.createElement("canvas"); canvas.width = canvas.height = 32;
      const context = canvas.getContext("2d", { willReadFrequently: true }); context.drawImage(image, 0, 0, 32, 32);
      const buckets = new Map(); const pixels = context.getImageData(0, 0, 32, 32).data;
      for (let index = 0; index < pixels.length; index += 16) {
        const [red, green, blue] = [pixels[index], pixels[index + 1], pixels[index + 2]];
        const key = `${Math.round(red / 32) * 32},${Math.round(green / 32) * 32},${Math.round(blue / 32) * 32}`;
        buckets.set(key, (buckets.get(key) || 0) + 1);
      }
      const colors = [...buckets.entries()].sort((left, right) => right[1] - left[1]).slice(0, 2).map(([key]) => `rgb(${key})`);
      const palette = [colors[0] || "#242424", colors[1] || colors[0] || "#111"];
      fullscreenPaletteCache.set(url, palette); apply(palette);
    } catch (_) { /* A cover may be unavailable while its player state is still valid. */ }
  }, { once: true });
}
function updateFullscreenPlayer(player, track) {
  const song = player?.song; const online = Boolean(player?.online); const elapsed = Number(player?.elapsed || 0); const duration = Number(player?.duration || song?.duration || 0);
  dom.fullscreenTitle.textContent = song?.title || song?.file || "Ничего не играет";
  dom.fullscreenArtist.textContent = song?.artist || (online ? "MPD подключён" : "MPD offline");
  dom.fullscreenElapsed.textContent = formatTime(elapsed); dom.fullscreenDuration.textContent = formatTime(duration);
  dom.fullscreenSeek.max = String(Math.max(1, duration)); dom.fullscreenSeek.value = String(Math.min(elapsed, duration || 1)); dom.fullscreenVolume.value = String(Number(player?.volume || 0));
  replace(dom.fullscreenPlay, icon(player?.state === "play" ? "pause" : "play", 28)); dom.fullscreenPlay.setAttribute("aria-label", player?.state === "play" ? "Пауза" : "Воспроизвести");
  for (const control of [...dom.fullscreen.querySelectorAll("[data-fullscreen-command]"), dom.fullscreenSeek, dom.fullscreenVolume]) control.disabled = !online;
  setFullscreenCover(track ? coverUrl(track) : "");
}
function openFullscreenPlayer() { dom.fullscreen.hidden = false; document.body.classList.add("fullscreen-open"); document.querySelector("#fullscreen-close").focus(); }
function closeFullscreenPlayer() { dom.fullscreen.hidden = true; document.body.classList.remove("fullscreen-open"); dom.playerCover.focus(); }

async function updatePlayer(player) {
  state.player = player; const online = Boolean(player?.online); dom.player.classList.toggle("online", online); dom.player.classList.toggle("offline", !online); dom.playerState.textContent = online ? (player.state === "play" ? "Играет" : "Пауза") : "Не в сети";
  const song = player?.song; dom.playerTitle.textContent = song?.title || song?.file || "Ничего не играет"; dom.playerArtist.textContent = song?.artist || (online ? "MPD подключён" : "MPD offline");
  const elapsed = Number(player?.elapsed || 0); const duration = Number(player?.duration || song?.duration || 0); dom.elapsed.textContent = formatTime(elapsed); dom.duration.textContent = formatTime(duration); dom.seek.max = String(Math.max(1, duration)); dom.seek.value = String(Math.min(elapsed, duration || 1)); dom.volume.value = String(Number(player?.volume || 0));
  for (const control of [...document.querySelectorAll("[data-command]"), dom.seek, dom.volume]) { const disabled = !online || control.dataset.busy === "true"; control.disabled = disabled; control.setAttribute("aria-disabled", String(disabled)); }
  const toggle = document.querySelector(".play-toggle"); replace(toggle, icon(player?.state === "play" ? "pause" : "play", 17)); toggle.setAttribute("aria-label", player?.state === "play" ? "Пауза" : "Воспроизвести");
  syncTrackPlayButtons();
  replace(dom.playerCover); const track = await resolvePlayerTrack(song).catch(() => null); const url = track ? coverUrl(track) : ""; if (url) dom.playerCover.append(element("img", { src: url, alt: "", attrs: { style: "width:100%;height:100%;object-fit:cover;border-radius:inherit" } })); else dom.playerCover.append(icon("music", 20));
  updateFullscreenPlayer(player, track);
}
async function pollPlayer() { try { await updatePlayer(await request("/player/status")); } catch { await updatePlayer({ online: false }); } }

await render(); await pollPlayer(); setInterval(pollPlayer, 2000);
