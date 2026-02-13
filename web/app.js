const chat = document.getElementById("chat");
const chatWrap = document.getElementById("chatWrap");
const msg = document.getElementById("msg");
const send = document.getElementById("send");
const toast = document.getElementById("jobToast");

const composerCenter = document.getElementById("composerCenter");
const composerDock = document.getElementById("composerDock");
const dockComposerInner = composerDock ? composerDock.querySelector(".composer-bottom") : null;

const heroTitle = document.getElementById("heroTitle");
const heroSub = document.querySelector(".welcome-sub");
const footerLine = document.querySelector(".welcome .footerLine");
const noticeBanner = document.getElementById("noticeBanner");

let toastTimer = null;
let lastSeenJobId = null;
let lastSeenStatus = null;

function pick(arr) {
    if (!arr || arr.length === 0) return null;
    return arr[Math.floor(Math.random() * arr.length)];
}

async function loadUiMessages() {
    // Defaults (in case JSON missing)
    let cfg = {
        hero_headlines: ["Hey there 👋 Let’s do some work."],
        hero_subheads: ["Paste a new customer or an order. I’ll confirm details, then queue it for MyCustomers."],
        you_can_say: ["New customer Jane Doe, jane@gmail.com 555 5th St Arab, Alabama 12345 5551231234"],
        emergency: { enabled: false }
    };

    try {
        const res = await fetch(`/web/ui_messages.json?v=${Date.now()}`, { cache: "no-store" });
        if (res.ok) cfg = await res.json();
    } catch (e) {
        console.error("Failed to load/parse ui_messages.json:", e);
        // use defaults
    }

    const h = pick(cfg.hero_headlines);
    const s = pick(cfg.hero_subheads);
    const y = pick(cfg.you_can_say);

    if (heroTitle && h) heroTitle.textContent = h;
    if (heroSub && s) heroSub.textContent = s;
    if (footerLine && y) footerLine.textContent = `You can say: ${y}`;

    // Emergency banner
    if (noticeBanner && cfg.emergency && cfg.emergency.enabled) {
        const title = cfg.emergency.title || "Notice";
        const message = cfg.emergency.message || "";
        noticeBanner.innerHTML = `<strong>${title}:</strong> ${message}`;
        noticeBanner.classList.remove("hidden");
    } else if (noticeBanner) {
        noticeBanner.classList.add("hidden");
    }
}

function scrollChatToBottom() {
    if (chatWrap) chatWrap.scrollTop = chatWrap.scrollHeight;
}

function addMessage(text, who) {
    const div = document.createElement("div");
    div.className = `msg ${who}`;
    div.textContent = text;
    chat.appendChild(div);
    requestAnimationFrame(() => scrollChatToBottom());
}

function showToast(text, smallText = "") {
    if (!toast) return;

    toast.classList.remove("hidden");
    toast.innerHTML = `${text}${smallText ? `<span class="small">${smallText}</span>` : ""}`;

    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
        toast.classList.add("hidden");
    }, 5500);
}

function updateKeyboardOffset() {
    if (!window.visualViewport) return;

    const vv = window.visualViewport;
    const offset = Math.max(0, (window.innerHeight - vv.height - vv.offsetTop));

    document.documentElement.style.setProperty("--kbOffset", `${offset}px`);
    requestAnimationFrame(() => scrollChatToBottom());
}

if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", updateKeyboardOffset);
    window.visualViewport.addEventListener("scroll", updateKeyboardOffset);
}
window.addEventListener("resize", updateKeyboardOffset);

function enterChatModeIfNeeded() {
    document.body.classList.add("chatStarted");

    if (composerCenter) composerCenter.classList.add("isHidden");
    if (composerDock) composerDock.style.display = "block";

    // Move textarea + button into dock composer
    if (dockComposerInner && msg && send) {
        if (!dockComposerInner.contains(msg)) dockComposerInner.appendChild(msg);
        if (!dockComposerInner.contains(send)) dockComposerInner.appendChild(send);
    }

    scrollChatToBottom();
    updateKeyboardOffset();
}

function resetToInitialState() {
    chat.innerHTML = "";
    document.body.classList.remove("chatStarted");

    if (composerCenter) composerCenter.classList.remove("isHidden");
    if (composerDock) composerDock.style.display = "none";

    // Move textarea + button back to center composer
    if (composerCenter && msg && send) {
        if (!composerCenter.contains(msg)) composerCenter.appendChild(msg);
        if (!composerCenter.contains(send)) composerCenter.appendChild(send);
    }

    msg.value = "";
    if (window.innerWidth > 600) msg.focus();
    updateKeyboardOffset();
}

async function resetServerSession() {
    try {
        // Clears pending + last_customer on the server for this consultant
        await fetch("/reset", { method: "POST" });
    } catch (e) {
        // ignore
    }
}

// Best-effort: if the user backgrounds/leaves the page mid-confirmation,
// try to clear the server pending so it doesn't stick around.
window.addEventListener("pagehide", () => {
    try {
        if (navigator.sendBeacon) navigator.sendBeacon("/reset");
    } catch (e) {
        // ignore
    }
});

async function sendMessage() {
    const text = msg.value.trim();
    if (!text) return;

    enterChatModeIfNeeded();

    addMessage(text, "user");
    msg.value = "";
    send.disabled = true;

    // Mobile: close keyboard after sending (tap input to reopen)
    msg.blur();

    try {
        const res = await fetch("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: text })
        });

        const data = await res.json();
        addMessage(data.reply || "(no reply)", "bot");

        // Desktop: keep typing flow fast
        if (window.innerWidth > 600) {
            setTimeout(() => msg.focus(), 0);
        }
    } catch (e) {
        addMessage("Error talking to server. Check terminal logs.", "bot");
    } finally {
        send.disabled = false;
        msg.blur();
        updateKeyboardOffset();
    }
}

send.addEventListener("click", sendMessage);

// Enter sends, Shift+Enter new line
msg.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

function jobLabel(j) {
    if (!j) return "";
    if (j.type === "NEW_CUSTOMER") return "New customer";
    if (j.type === "NEW_ORDER_ROW") return "Order";
    return j.type;
}

async function refreshJobs() {
    try {
        const res = await fetch("/jobs");
        const data = await res.json();
        const jobs = data.jobs || [];
        if (jobs.length === 0) return;

        const j = jobs[0];

        if (lastSeenJobId === null) {
            lastSeenJobId = j.id;
            lastSeenStatus = j.status;
            return;
        }

        // New job appeared
        if (j.id !== lastSeenJobId) {
            lastSeenJobId = j.id;
            lastSeenStatus = j.status;

            const label = jobLabel(j);

            if (j.status === "queued") {
                showToast("🕒 Queued for MyCustomers", label ? `• ${label}` : "");
            } else if (j.status === "running") {
                showToast("▶️ Working…", label ? `• ${label}` : "");
            } else if (j.status === "done") {
                showToast("✅ " + (j.status_msg || "Complete"));
            } else if (j.status === "failed") {
                showToast("❌ " + (j.status_msg || "Job failed"), j.error ? j.error : "");
            } else {
                showToast(`ℹ️ ${j.status}`, label ? `• ${label}` : "");
            }
            return;
        }

        // Same job, status changed
        if (j.status !== lastSeenStatus) {
            lastSeenStatus = j.status;
            const label = jobLabel(j);

            if (j.status === "running") {
                showToast("▶️ Working…", label ? `• ${label}` : "");
            } else if (j.status === "done") {
                showToast("✅ " + (j.status_msg || "Complete"));
            } else if (j.status === "failed") {
                showToast("❌ " + (j.status_msg || "Job failed"), j.error ? j.error : "");
            }
        }
    } catch (e) {
        // ignore
    }
}

// Poll job updates every 3 seconds
setInterval(refreshJobs, 3000);
refreshJobs();

// One clean startup sequence:
// 1) Clear server pending so “yes/no” never survives reload
// 2) Reset UI
// 3) Load rotating hero messages
(async () => {
    updateKeyboardOffset();
    await resetServerSession();
    resetToInitialState();
    await loadUiMessages();
})();
