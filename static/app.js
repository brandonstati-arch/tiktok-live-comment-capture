/* ==========================================================================
   Captura de comentarios · TikTok LIVE — lógica de la interfaz
   Los datos llegan por Server-Sent Events desde /api/stream.
   ========================================================================== */

const $ = (id) => document.getElementById(id);

let COLUMNS = [];
let rows = [];
let giftRows = [];
let status = null;
let activeChip = "all";
let query = "";
let autoScroll = true;
let tickTimer = null;

const TAGS = [
  ["es_moderador", "mod", "MOD"],
  ["es_suscriptor", "sub", "SUB"],
  ["es_top_gifter", "top", "TOP"],
  ["es_seguidor", "fol", "SIGUE"],
];

/* ------------------------------ utilidades ------------------------------ */
function fmtDuration(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  const h = String(Math.floor(s / 3600)).padStart(2, "0");
  const m = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const sec = String(s % 60).padStart(2, "0");
  return h === "00" ? `${m}:${sec}` : `${h}:${m}:${sec}`;
}

function cell(className, text) {
  const td = document.createElement("td");
  td.className = className;
  td.textContent = text ?? "";
  return td;
}

function matches(row) {
  if (activeChip === "sub" && row.es_suscriptor !== "Sí") return false;
  if (activeChip === "mod" && row.es_moderador !== "Sí") return false;
  if (activeChip === "mention" && !row.menciones) return false;
  if (query) {
    const haystack = [
      row.usuario, row.nickname, row.comentario, row.user_id,
      row.insignias, row.msg_id, row.menciones,
    ].join(" ").toLowerCase();
    if (!haystack.includes(query)) return false;
  }
  return true;
}

/* ------------------------------- tabla --------------------------------- */
function buildRow(row) {
  const tr = document.createElement("tr");
  tr.className = "row";
  tr.dataset.n = row.n;

  tr.appendChild(cell("c-num", row.n));

  const tdTime = document.createElement("td");
  tdTime.className = "c-time";
  tdTime.textContent = row.hora_ms;
  tdTime.title = `${row.timestamp_iso}  ·  latencia ${row.latencia_ms ?? "?"} ms`;
  tr.appendChild(tdTime);

  const tdUser = document.createElement("td");
  tdUser.className = "c-user";
  if (row.perfil) {
    const a = document.createElement("a");
    a.href = row.perfil;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = row.usuario;
    tdUser.appendChild(a);
  } else {
    tdUser.textContent = row.usuario;
  }
  if (row.nickname) {
    const nick = document.createElement("span");
    nick.className = "nick";
    nick.textContent = row.nickname;
    tdUser.appendChild(nick);
  }
  tr.appendChild(tdUser);

  tr.appendChild(cell("c-msg", row.comentario));
  tr.appendChild(cell("c-id", row.user_id));

  const tdTags = document.createElement("td");
  tdTags.className = "c-tags";
  for (const [key, cls, label] of TAGS) {
    if (row[key] === "Sí") {
      const tag = document.createElement("span");
      tag.className = `tag ${cls}`;
      tag.textContent = label;
      tdTags.appendChild(tag);
    }
  }
  tr.appendChild(tdTags);

  tr.addEventListener("click", () => toggleDetail(tr, row));
  return tr;
}

function toggleDetail(tr, row) {
  const next = tr.nextElementSibling;
  if (next && next.classList.contains("detail")) {
    next.remove();
    return;
  }
  document.querySelectorAll("tr.detail").forEach((el) => el.remove());

  const detail = document.createElement("tr");
  detail.className = "detail";
  const td = document.createElement("td");
  td.colSpan = 6;

  const grid = document.createElement("div");
  grid.className = "detail-grid";
  for (const col of COLUMNS) {
    const item = document.createElement("div");
    item.className = "item";
    const k = document.createElement("div");
    k.className = "k";
    k.textContent = col.header;
    const v = document.createElement("div");
    v.className = "v" + (["user_id", "msg_id", "sec_uid", "unix_ms", "room_id"].includes(col.key) ? " mono" : "");
    v.textContent = row[col.key] === "" || row[col.key] == null ? "—" : String(row[col.key]);
    item.append(k, v);
    grid.appendChild(item);
  }
  td.appendChild(grid);
  detail.appendChild(td);
  tr.after(detail);
}

function renderAll() {
  const tbody = $("tbody");
  tbody.replaceChildren();
  const fragment = document.createDocumentFragment();
  let visible = 0;
  for (const row of rows) {
    if (!matches(row)) continue;
    fragment.appendChild(buildRow(row));
    visible++;
  }
  tbody.appendChild(fragment);
  $("empty").style.display = visible ? "none" : "flex";
  if (!rows.length) {
    $("empty").innerHTML =
      '<div class="icon">💬</div><strong>Todavía no hay comentarios</strong>' +
      "<span>Introduce un usuario que esté en directo y pulsa <em>Iniciar captura</em>. " +
      "También puedes usar <em>Probar con datos de ejemplo</em> para ver cómo funciona.</span>";
  } else if (!visible) {
    $("empty").innerHTML =
      '<div class="icon">🔍</div><strong>Ningún comentario coincide</strong>' +
      "<span>Cambia el filtro o el texto de búsqueda.</span>";
  }
  scrollToBottom();
}

function appendRow(row) {
  if (!matches(row)) return;
  const tbody = $("tbody");
  const tr = buildRow(row);
  tr.classList.add("is-new");
  tbody.appendChild(tr);
  $("empty").style.display = "none";
  setTimeout(() => tr.classList.remove("is-new"), 1200);
  scrollToBottom();
}

function scrollToBottom() {
  if (!autoScroll) return;
  const box = $("tableScroll");
  box.scrollTop = box.scrollHeight;
}

/* ------------------------------- estado -------------------------------- */
const STATE_TEXT = {
  idle: "Inactivo",
  connecting: "Conectando…",
  live: "EN DIRECTO",
  stopping: "Deteniendo…",
  stopped: "Detenido",
  offline: "Directo finalizado",
  error: "Error",
};

function applyStatus(next) {
  status = next;
  const state = next.state || "idle";

  $("pill").dataset.state = state;
  $("pillText").textContent = STATE_TEXT[state] || state;
  $("subtitle").textContent = next.message || "";

  $("sessionInfo").textContent = next.unique_id && next.unique_id !== "sin-sesion"
    ? `@${next.unique_id}${next.room_id ? ` · sala ${next.room_id}` : ""} · ${next.session_id}`
    : "";

  $("stComments").textContent = next.stats.comments.toLocaleString("es-ES");
  $("stUsers").textContent = next.stats.unique_users.toLocaleString("es-ES");
  $("stRate").textContent = next.stats.per_minute.toLocaleString("es-ES");
  $("stTime").textContent = fmtDuration(next.stats.elapsed_s);

  const busy = state === "connecting" || state === "live" || state === "stopping";
  $("btnStart").disabled = busy;
  $("btnStop").disabled = !(state === "connecting" || state === "live");
  $("btnDemo").disabled = busy;
  $("btnExport").disabled = !next.stats.comments;
  $("usuario").disabled = busy;
  $("regalos").disabled = busy;

  const alert = $("alert");
  if (state === "error" && next.error) {
    alert.className = "alert error show";
    alert.textContent = "⚠️ " + next.error;
  } else if (state === "offline") {
    alert.className = "alert warn show";
    alert.textContent = "ℹ️ " + (next.message || "El directo terminó.") +
      (next.xlsx ? " Se ha generado el Excel automáticamente." : "");
  } else if (state === "stopped" && next.stats.comments) {
    alert.className = "alert info show";
    alert.textContent = `✅ Captura finalizada con ${next.stats.comments} comentarios.` +
      (next.xlsx ? " El Excel se ha generado automáticamente." : "");
  } else {
    alert.className = "alert";
  }

  // Cronómetro local mientras la captura está activa.
  clearInterval(tickTimer);
  if (state === "live" || state === "connecting") {
    const base = next.stats.elapsed_s;
    const t0 = Date.now();
    tickTimer = setInterval(() => {
      $("stTime").textContent = fmtDuration(base + (Date.now() - t0) / 1000);
    }, 1000);
  }

  if (state === "stopped" || state === "offline" || state === "error") loadFiles();
}

/* ------------------------------- SSE ----------------------------------- */
function connectStream() {
  const source = new EventSource("/api/stream");

  source.onmessage = (event) => {
    let payload;
    try { payload = JSON.parse(event.data); } catch { return; }

    if (payload.type === "snapshot") {
      COLUMNS = payload.data.columns;
      rows = payload.data.rows;
      giftRows = [];
      renderAll();
      applyStatus(payload.data.status);
      loadFiles();
    } else if (payload.type === "comment") {
      rows.push(payload.row);
      appendRow(payload.row);
      refreshCounters();
    } else if (payload.type === "gift") {
      giftRows.push(payload.row);
      addGift(payload.row);
    } else if (payload.type === "status") {
      applyStatus(payload.status);
    }
  };

  source.onerror = () => {
    $("pill").dataset.state = "error";
    $("pillText").textContent = "Sin conexión con el servidor";
    // EventSource reintenta solo; se muestra el aviso sin cerrar el flujo.
  };
}

function refreshCounters() {
  const users = new Set(rows.map((r) => r.user_id).filter(Boolean));
  $("stComments").textContent = rows.length.toLocaleString("es-ES");
  $("stUsers").textContent = users.size.toLocaleString("es-ES");
  if (status) {
    const elapsed = Math.max(0.001, (Date.now() - new Date(status.started_at || Date.now()).getTime()) / 60000);
    $("stRate").textContent = (rows.length / elapsed).toFixed(1);
  }
}

/* ------------------------------ regalos -------------------------------- */
function addGift(row) {
  const list = $("giftList");
  if (list.querySelector(".note")) list.replaceChildren();

  const item = document.createElement("div");
  item.className = "gift-item";

  const emoji = document.createElement("div");
  emoji.className = "g-emoji";
  emoji.textContent = "🎁";

  const main = document.createElement("div");
  main.className = "g-main";
  const who = document.createElement("b");
  who.textContent = row.usuario;
  const what = document.createElement("span");
  what.textContent = `${row.regalo} × ${row.repeticiones} · ${row.hora_ms}`;
  main.append(who, what);

  const val = document.createElement("div");
  val.className = "g-val";
  val.textContent = `${row.diamantes_totales} 💎`;

  item.append(emoji, main, val);
  list.prepend(item);
  $("giftCount").textContent = giftRows.length;
}

/* ---------------------------- ficheros --------------------------------- */
async function loadFiles() {
  try {
    const response = await fetch("/api/sesiones");
    const data = await response.json();
    const list = $("fileList");
    if (!data.files.length) {
      list.innerHTML = '<div class="note">Aún no se ha generado ningún fichero.</div>';
      return;
    }
    list.replaceChildren();
    for (const file of data.files) {
      const item = document.createElement("div");
      item.className = "file-item";

      const icon = document.createElement("div");
      icon.className = `f-icon ${file.kind}`;
      icon.textContent = file.kind === "xlsx" ? "XLS" : "CSV";

      const main = document.createElement("div");
      main.className = "f-main";
      const link = document.createElement("a");
      link.href = file.url;
      link.textContent = file.name;
      link.title = file.name;
      const meta = document.createElement("span");
      meta.textContent = `${file.size_kb} KB · ${file.modified}`;
      main.append(link, meta);

      item.append(icon, main);
      list.appendChild(item);
    }
  } catch { /* sin conexión: se reintenta al siguiente evento */ }
}

/* ------------------------------ acciones ------------------------------- */
async function post(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : null,
  });
  return response.json();
}

$("btnStart").addEventListener("click", async () => {
  const usuario = $("usuario").value.trim();
  if (!usuario) {
    $("alert").className = "alert error show";
    $("alert").textContent = "⚠️ Escribe el nombre de usuario de TikTok (por ejemplo: @usuario).";
    $("usuario").focus();
    return;
  }
  $("alert").className = "alert";
  const data = await post("/api/start", { usuario, regalos: $("regalos").checked });
  if (!data.ok) {
    $("alert").className = "alert error show";
    $("alert").textContent = "⚠️ " + data.error;
    return;
  }
  applyStatus(data.status);
});

$("btnStop").addEventListener("click", async () => {
  const data = await post("/api/stop");
  applyStatus(data.status);
});

$("btnDemo").addEventListener("click", async () => {
  $("alert").className = "alert";
  const data = await post("/api/demo");
  if (!data.ok) {
    $("alert").className = "alert error show";
    $("alert").textContent = "⚠️ " + data.error;
    return;
  }
  applyStatus(data.status);
});

$("btnExport").addEventListener("click", async () => {
  const data = await post("/api/export");
  if (!data.ok) {
    $("alert").className = "alert error show";
    $("alert").textContent = "⚠️ " + data.error;
    return;
  }
  $("alert").className = "alert info show";
  $("alert").textContent = `✅ Excel generado con ${data.rows} comentarios: ${data.file}`;
  const link = document.createElement("a");
  link.href = data.url;
  link.download = data.file;
  document.body.appendChild(link);
  link.click();
  link.remove();
  loadFiles();
});

$("btnRefresh").addEventListener("click", loadFiles);

$("filtro").addEventListener("input", (event) => {
  query = event.target.value.trim().toLowerCase();
  renderAll();
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    document.querySelectorAll(".chip").forEach((other) => other.setAttribute("aria-pressed", "false"));
    chip.setAttribute("aria-pressed", "true");
    activeChip = chip.dataset.filter;
    renderAll();
  });
});

$("autoscroll").addEventListener("change", (event) => {
  autoScroll = event.target.checked;
  if (autoScroll) scrollToBottom();
});

// Si el usuario sube manualmente, se desactiva el auto-scroll para no molestar.
$("tableScroll").addEventListener("scroll", (event) => {
  const box = event.target;
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  if (!atBottom && autoScroll) {
    autoScroll = false;
    $("autoscroll").checked = false;
  }
});

$("usuario").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !$("btnStart").disabled) $("btnStart").click();
});

setInterval(() => {
  $("clock").textContent = new Date().toLocaleTimeString("es-ES");
}, 1000);
$("clock").textContent = new Date().toLocaleTimeString("es-ES");

connectStream();
loadFiles();
