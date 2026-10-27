// Admin dashboard: calls the REST API (GET list, PUT update, DELETE remove).
// All message text is inserted with textContent (never innerHTML) because it is user-supplied.

const keyForm = document.getElementById("keyForm");
const keyInput = document.getElementById("adminKey");
const statusEl = document.getElementById("adminStatus");
const dashboard = document.getElementById("dashboard");
const rowsEl = document.getElementById("rows");
const emptyEl = document.getElementById("emptyState");
const fSentiment = document.getElementById("filterSentiment");
const fStatus = document.getElementById("filterStatus");
const fText = document.getElementById("filterText");

let allMessages = [];

// The key is kept only for this browser tab (sessionStorage), never in the source code.
function getKey() {
    try { return sessionStorage.getItem("ccAdminKey") || ""; } catch { return ""; }
}
function setKey(k) {
    try { sessionStorage.setItem("ccAdminKey", k); } catch { /* ignore */ }
}

function setStatus(text, isError = false) {
    statusEl.textContent = text;
    statusEl.style.color = isError ? "#dc2626" : "#16a34a";
}

async function api(path, options = {}) {
    const res = await fetch(API_BASE + path, {
        ...options,
        headers: {
            "Content-Type": "application/json",
            "x-admin-key": getKey(),
            ...(options.headers || {})
        }
    });
    let data = {};
    try { data = await res.json(); } catch { /* non-JSON error */ }
    if (!res.ok || data.success === false) {
        throw new Error(data.message || `Request failed (${res.status})`);
    }
    return data;
}

async function loadMessages() {
    setStatus("Loading...");
    try {
        const data = await api("/messages");
        allMessages = data.items || [];
        dashboard.hidden = false;
        setStatus(`Loaded ${allMessages.length} message(s).`);
        render();
    } catch (err) {
        dashboard.hidden = true;
        setStatus(err.message, true);
    }
}

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

function updateStats() {
    const count = (fn) => allMessages.filter(fn).length;
    document.getElementById("statTotal").textContent = allMessages.length;
    document.getElementById("statPositive").textContent = count(m => m.sentiment === "POSITIVE");
    document.getElementById("statNeutral").textContent = count(m => ["NEUTRAL", "MIXED"].includes(m.sentiment));
    document.getElementById("statNegative").textContent = count(m => m.sentiment === "NEGATIVE");
    document.getElementById("statOpen").textContent = count(m => (m.status || "New") !== "Resolved");
}

function matches(m) {
    if (fSentiment.value && (m.sentiment || "UNANALYZED") !== fSentiment.value) return false;
    if (fStatus.value && (m.status || "New") !== fStatus.value) return false;
    const q = fText.value.trim().toLowerCase();
    if (q && !`${m.name} ${m.email} ${m.message}`.toLowerCase().includes(q)) return false;
    return true;
}

function render() {
    updateStats();
    rowsEl.replaceChildren();
    const visible = allMessages.filter(matches);
    emptyEl.hidden = visible.length > 0;

    for (const m of visible) {
        const tr = document.createElement("tr");

        tr.append(el("td", "nowrap", m.createdAt ? new Date(m.createdAt).toLocaleString() : "—"));

        const from = el("td");
        from.append(el("strong", "", m.name || ""), el("br"), el("small", "", m.email || ""));
        tr.append(from);

        const msg = el("td", "msg");
        msg.append(el("p", "", m.message || ""));
        if (m.aiSummary) {
            const sum = el("p", "ai-summary");
            sum.append(el("b", "", "✨ AI summary: "), document.createTextNode(m.aiSummary));
            msg.append(sum);
        }
        const tags = el("div", "tags");
        const sentiment = m.sentiment || "UNANALYZED";
        tags.append(el("span", `pill ${sentiment.toLowerCase()}`, sentiment));
        if (m.category) tags.append(el("span", "pill cat", m.category));
        for (const p of (m.keyPhrases || [])) tags.append(el("span", "pill phrase", p));
        msg.append(tags);
        if (m.aiSuggestedReply) {
            const box = el("details", "ai-reply");
            box.append(el("summary", "", "✉ Suggested reply (AI draft)"));
            box.append(el("p", "", m.aiSuggestedReply));
            const copy = el("button", "secondary small-btn", "Copy reply");
            copy.type = "button";
            copy.addEventListener("click", async () => {
                try { await navigator.clipboard.writeText(m.aiSuggestedReply); copy.textContent = "Copied ✓"; }
                catch { copy.textContent = "Copy failed"; }
            });
            box.append(copy);
            msg.append(box);
        }
        tr.append(msg);

        tr.append(el("td", "", m.priority || "—"));

        const statusTd = el("td");
        const select = document.createElement("select");
        for (const s of ["New", "In Progress", "Resolved"]) {
            const opt = el("option", "", s);
            opt.value = s;
            if ((m.status || "New") === s) opt.selected = true;
            select.append(opt);
        }
        select.addEventListener("change", () => updateStatus(m.id, select.value));
        statusTd.append(select);
        tr.append(statusTd);

        const actions = el("td");
        const del = el("button", "danger", "Delete");
        del.type = "button";
        del.addEventListener("click", () => removeMessage(m.id));
        actions.append(del);
        tr.append(actions);

        rowsEl.append(tr);
    }
}

async function updateStatus(id, status) {
    try {
        const data = await api(`/messages/${encodeURIComponent(id)}`, {
            method: "PUT",
            body: JSON.stringify({ status })
        });
        const i = allMessages.findIndex(m => m.id === id);
        if (i >= 0) allMessages[i] = data.item;
        setStatus("Status updated.");
        render();
    } catch (err) {
        setStatus(err.message, true);
    }
}

async function removeMessage(id) {
    if (!confirm("Delete this message permanently?")) return;
    try {
        await api(`/messages/${encodeURIComponent(id)}`, { method: "DELETE" });
        allMessages = allMessages.filter(m => m.id !== id);
        setStatus("Message deleted.");
        render();
    } catch (err) {
        setStatus(err.message, true);
    }
}

keyForm.addEventListener("submit", (e) => {
    e.preventDefault();
    setKey(keyInput.value.trim());
    loadMessages();
});
document.getElementById("refreshBtn").addEventListener("click", loadMessages);
[fSentiment, fStatus].forEach(n => n.addEventListener("change", render));
fText.addEventListener("input", render);

if (getKey()) {
    keyInput.value = getKey();
    loadMessages();
}
