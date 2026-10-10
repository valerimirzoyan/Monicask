const state = {
  agentId: Number(localStorage.getItem("agentId") || 1),
  timer: null,
  contact: null,
};

const $ = (id) => document.getElementById(id);

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2).toLowerCase(), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
}

function fmt(iso) {
  if (!iso) return "";
  const value = iso.endsWith("Z") ? iso : iso + "Z";
  const date = new Date(value);
  return isNaN(date) ? iso : date.toLocaleTimeString();
}

async function api(path, options = {}) {
  const headers = Object.assign({ "X-Agent-Id": String(state.agentId) }, options.headers || {});
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, Object.assign({}, options, { headers }));
  let data = null;
  try { data = await response.json(); } catch (e) { /* no body */ }
  if (!response.ok) {
    throw new Error((data && data.detail) || `HTTP ${response.status}`);
  }
  return data;
}

function toast(message, isError = false) {
  const node = $("toast");
  node.textContent = message;
  node.style.borderColor = isError ? "var(--err)" : "var(--border)";
  node.classList.remove("hidden");
  clearTimeout(node._t);
  node._t = setTimeout(() => node.classList.add("hidden"), 3000);
}

function pill(node, value, prefix) {
  node.className = "pill pill-" + value;
  node.textContent = (prefix ? prefix + " " : "") + value;
}

function renderState(s) {
  pill($("statePill"), s.computed_state);
  const sync = $("syncPill");
  sync.textContent = s.asterisk_confirmed ? "AMI ok" : "AMI " + s.sync_status;
  sync.className = "pill " + (s.asterisk_confirmed ? "pill-ready" : "pill-offline");
  $("agentName").textContent = `${s.name} · ${s.extension} · ${s.reason}`;

  const banner = $("banner");
  if (s.sync_status === "error") {
    banner.textContent = "Синхронизация с Asterisk не подтверждена: " + (s.sync_error || "ошибка AMI");
    banner.classList.remove("hidden");
  } else if (s.computed_state === "ready" && !s.asterisk_confirmed) {
    banner.textContent = "Готовность не подтверждена: фактическое состояние очереди неизвестно.";
    banner.classList.remove("hidden");
  } else {
    banner.classList.add("hidden");
  }
}

function taskItem(session, handlers) {
  const meta = el("span", { class: "meta", text: `${session.work_mode} · ${fmt(session.started_at)}` });
  const actions = el("div", { class: "actions" }, [
    el("button", { class: "btn btn-sm btn-muted", text: "Завершить", onclick: () => handlers.complete(session.ticket_id) }),
  ]);
  return el("li", {}, [
    el("div", {}, [el("div", { class: "title", text: "#" + session.ticket_id }), meta]),
    actions,
  ]);
}

function renderTasks(data, handlers) {
  const blocking = $("blockingList");
  const background = $("backgroundList");
  blocking.replaceChildren();
  background.replaceChildren();
  if (!data.blocking.length) blocking.append(el("li", { class: "empty", text: "Нет блокирующих задач" }));
  if (!data.background.length) background.append(el("li", { class: "empty", text: "Нет фоновых задач" }));
  data.blocking.forEach((s) => blocking.append(taskItem(s, handlers)));
  data.background.forEach((s) => background.append(taskItem(s, handlers)));
}

function ticketItem(ticket, handlers) {
  const info = el("div", {}, [
    el("div", { class: "title", text: `#${ticket.id} ${ticket.title}` }),
    el("span", { class: "meta", text: `${ticket.priority || ""} · ${ticket.state}` }),
  ]);
  const actions = el("div", { class: "actions" });
  if (ticket.mine) {
    actions.append(el("span", { class: "badge badge-" + ticket.work_mode, text: ticket.work_mode }));
    actions.append(el("button", { class: "btn btn-sm btn-muted", text: "Завершить", onclick: () => handlers.complete(ticket.id) }));
  } else {
    actions.append(el("button", { class: "btn btn-sm btn-warn", text: "Приступить", onclick: () => handlers.start(ticket.id, "blocking") }));
    actions.append(el("button", { class: "btn btn-sm btn-secondary", text: "В фон", onclick: () => handlers.start(ticket.id, "background") }));
  }
  return el("li", {}, [info, actions]);
}

function renderTickets(data, handlers) {
  const list = $("ticketsList");
  list.replaceChildren();
  if (data.error) {
    list.append(el("li", { class: "empty", text: "Zammad недоступен: " + data.error }));
    return;
  }
  if (!data.tickets.length) list.append(el("li", { class: "empty", text: "Очередь пуста" }));
  data.tickets.forEach((t) => list.append(ticketItem(t, handlers)));
}

function renderAudit(data) {
  const list = $("auditList");
  list.replaceChildren();
  if (!data.events.length) list.append(el("li", { class: "empty", text: "Нет событий" }));
  data.events.forEach((e) =>
    list.append(el("li", {}, [
      el("span", { text: e.action }),
      el("span", { class: "meta", text: `${e.subject_type} ${e.subject_id} · ${fmt(e.at)}` }),
    ]))
  );
}

function renderCalls(data) {
  const list = $("callsList");
  list.replaceChildren();
  if (!data.calls.length) list.append(el("li", { class: "empty", text: "Нет звонков" }));
  data.calls.forEach((c) =>
    list.append(el("li", {}, [
      el("span", { text: c.number }),
      el("span", { class: "meta", text: `${c.direction} · ${fmt(c.started_at)}` }),
    ]))
  );
}

async function refresh() {
  try {
    const [agentState, tasks, tickets, audit, calls] = await Promise.all([
      api("/api/agents/me/state"),
      api("/api/agents/me/tasks"),
      api("/api/agents/me/tickets"),
      api("/api/agents/me/audit"),
      api("/api/agents/me/calls"),
    ]);
    renderState(agentState);
    renderTasks(tasks, handlers);
    renderTickets(tickets, handlers);
    renderAudit(audit);
    renderCalls(calls);
  } catch (error) {
    toast(error.message, true);
    pill($("statePill"), "offline");
  }
}

async function lookup(number) {
  if (!number) { toast("Введите номер", true); return null; }
  const result = await api("/api/contacts/lookup", { method: "POST", body: JSON.stringify({ number }) });
  const box = $("contactBox");
  if (result.found) {
    state.contact = result.contact;
    box.replaceChildren(
      el("div", { class: "name", text: result.contact.name }),
      el("div", { class: "meta", text: `${result.contact.phone} · ${result.contact.email || ""}` })
    );
    if (!$("ticketSubject").value) $("ticketSubject").value = "Обращение от " + result.contact.name;
  } else {
    state.contact = null;
    box.replaceChildren(el("div", { class: "meta", text: "Клиент не найден: " + result.number_normalized }));
  }
  box.classList.remove("hidden");
  return result;
}

const handlers = {
  async start(ticketId, mode) {
    try {
      const result = await api(`/api/tickets/${ticketId}/start`, { method: "POST", body: JSON.stringify({ work_mode: mode }) });
      toast(`Тикет #${ticketId}: режим ${result.work_mode}`);
      await refresh();
    } catch (error) { toast(error.message, true); }
  },
  async complete(ticketId) {
    try {
      await api(`/api/tickets/${ticketId}/complete`, { method: "POST", body: JSON.stringify({}) });
      toast(`Тикет #${ticketId} завершён`);
      await refresh();
    } catch (error) { toast(error.message, true); }
  },
};

function bind() {
  $("agentId").value = state.agentId;
  $("connectBtn").onclick = () => {
    state.agentId = Number($("agentId").value || 1);
    localStorage.setItem("agentId", String(state.agentId));
    toast("Оператор " + state.agentId);
    refresh();
  };
  $("readyBtn").onclick = async () => { try { await api("/api/agents/me/ready", { method: "POST", body: "{}" }); await refresh(); } catch (e) { toast(e.message, true); } };
  $("breakBtn").onclick = async () => { try { await api("/api/agents/me/break", { method: "POST", body: JSON.stringify({ reason: "manual" }) }); await refresh(); } catch (e) { toast(e.message, true); } };
  $("offlineBtn").onclick = async () => { try { await api("/api/agents/me/offline", { method: "POST", body: "{}" }); await refresh(); } catch (e) { toast(e.message, true); } };
  $("lookupBtn").onclick = () => lookup($("callNumber").value).catch((e) => toast(e.message, true));
  $("simulateBtn").onclick = async () => {
    try {
      const call = await api("/api/dev/simulate-call", { method: "POST", body: JSON.stringify({ number: $("callNumber").value || "+37360123456" }) });
      $("callNumber").value = call.number;
      await lookup(call.number);
      await refresh();
    } catch (e) { toast(e.message, true); }
  };
  $("createTicketBtn").onclick = async () => {
    try {
      const ticket = await api("/api/tickets", {
        method: "POST",
        body: JSON.stringify({
          subject: $("ticketSubject").value || "Обращение",
          description: "",
          customer: state.contact ? String(state.contact.id) : "",
        }),
      });
      toast("Создан тикет #" + ticket.id);
      $("ticketSubject").value = "";
      await refresh();
    } catch (e) { toast(e.message, true); }
  };
}

bind();
refresh();
state.timer = setInterval(refresh, 5000);
