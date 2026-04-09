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
let toastQueue = [];

// Track all visible jobs: jobId -> status
const trackedJobs = new Map();
let jobsInitialized = false;

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

    const lang = (document.body.dataset.lang || "en").trim();
    const isEs = lang === "es";

    const h = pick(isEs ? (cfg.hero_headlines_es || cfg.hero_headlines) : cfg.hero_headlines);
    const s = pick(isEs ? (cfg.hero_subheads_es || cfg.hero_subheads) : cfg.hero_subheads);
    const youCanSayArr = isEs ? (cfg.you_can_say_es || cfg.you_can_say) : cfg.you_can_say;
    const youCanSayLabel = isEs ? "Puedes decir" : "You can say";
    const nextLabel = isEs ? "siguiente" : "next";

    if (heroTitle && h) heroTitle.textContent = h;
    if (heroSub && s) heroSub.textContent = s;

    if (footerLine && youCanSayArr && youCanSayArr.length > 0) {
        let youCanSayIndex = Math.floor(Math.random() * youCanSayArr.length);

        const textSpan = document.createElement("span");
        textSpan.id = "youCanSayText";
        textSpan.textContent = `${youCanSayLabel}: ${youCanSayArr[youCanSayIndex]}`;

        const cycleBtn = document.createElement("button");
        cycleBtn.id = "youCanSayCycle";
        cycleBtn.title = nextLabel;
        cycleBtn.textContent = "↻";
        cycleBtn.addEventListener("click", () => {
            youCanSayIndex = (youCanSayIndex + 1) % youCanSayArr.length;
            const ts = document.getElementById("youCanSayText");
            if (ts) ts.textContent = `${youCanSayLabel}: ${youCanSayArr[youCanSayIndex]}`;
            cycleBtn.classList.remove("spinning");
            void cycleBtn.offsetWidth;
            cycleBtn.classList.add("spinning");
            cycleBtn.addEventListener("animationend", () => cycleBtn.classList.remove("spinning"), { once: true });
        });

        footerLine.textContent = "";
        footerLine.appendChild(textSpan);
        footerLine.appendChild(cycleBtn);
    }

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
    if (who === "bot" && (text.includes("<a ") || text.includes("<div"))) {
        // Server-generated HTML (e.g. customer cards, follow-up cards)
        div.innerHTML = text;
    } else {
        div.textContent = text;
    }
    chat.appendChild(div);
    requestAnimationFrame(() => scrollChatToBottom());
}

function showToast(text, smallText = "") {
    if (!toast) return;
    toastQueue.push({ text, smallText });
    if (toastQueue.length === 1) _showNextToast();
}

function _showNextToast() {
    if (!toast || toastQueue.length === 0) return;
    const { text, smallText } = toastQueue[0];

    const isError =
        (text || "").includes("❌") ||
        (smallText || "").toLowerCase().includes("error") ||
        (smallText || "").toLowerCase().includes("could not") ||
        (smallText || "").toLowerCase().includes("please open") ||
        (smallText || "").toLowerCase().includes("confirm");

    const duration = isError ? 10000 : 5500;

    toast.classList.remove("hidden");
    toast.innerHTML = `${text}${smallText ? `<span class="small">${smallText}</span>` : ""}`;

    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
        toast.classList.add("hidden");
        toastQueue.shift();
        if (toastQueue.length > 0) _showNextToast();
    }, duration);
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

// Delegated handler for [data-send] links — clicking sends a chat message
chat.addEventListener("click", function(e) {
    var link = e.target.closest("[data-send]");
    if (link) {
        e.preventDefault();
        var text = link.dataset.send;
        if (text) {
            msg.value = text;
            sendMessage();
        }
        return;
    }
});

// Delegated handler for follow-up circles — avoids inline onclick CSP issues
chat.addEventListener("click", function(e) {
    var btn = e.target.closest(".followup-circle");
    if (!btn) return;

    var card = btn.closest(".followup-card");
    if (!card) return;

    var cardType = btn.dataset.cardType || "order";
    var orderId = parseInt(btn.dataset.orderId, 10);
    var followupWindow = parseInt(btn.dataset.windowId, 10);
    var customerId = parseInt(btn.dataset.customerId, 10);
    var isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);

    if (isMobile) {
        window.location.href = card.dataset.sms;
    } else {
        var existing = card.querySelector(".followup-desktop-panel");
        if (existing) {
            existing.remove();
        } else {
            var phone = card.dataset.phone || "";
            var msg = card.dataset.msg || "";
            var panel = document.createElement("div");
            panel.className = "followup-desktop-panel";
            var copyBtn = document.createElement("button");
            copyBtn.className = "fdp-copy";
            copyBtn.textContent = "Copy message";
            copyBtn.addEventListener("click", function() {
                function fallbackCopy() {
                    var ta = document.createElement("textarea");
                    ta.value = msg;
                    ta.style.position = "fixed";
                    ta.style.opacity = "0";
                    document.body.appendChild(ta);
                    ta.select();
                    document.execCommand("copy");
                    document.body.removeChild(ta);
                    copyBtn.textContent = "Copied!";
                    setTimeout(function() { copyBtn.textContent = "Copy message"; }, 1500);
                }
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(msg).then(function() {
                        copyBtn.textContent = "Copied!";
                        setTimeout(function() { copyBtn.textContent = "Copy message"; }, 1500);
                    }).catch(function() { fallbackCopy(); });
                } else {
                    fallbackCopy();
                }
            });
            var phoneDiv = document.createElement("div");
            phoneDiv.className = "fdp-phone";
            phoneDiv.textContent = "📱 " + phone;
            var msgDiv = document.createElement("div");
            msgDiv.className = "fdp-msg";
            msgDiv.textContent = msg;
            panel.appendChild(phoneDiv);
            panel.appendChild(msgDiv);
            panel.appendChild(copyBtn);
            card.appendChild(panel);
        }
    }

    if (!btn.classList.contains("done")) {
        btn.classList.add("done");
        btn.textContent = "✓";
        var payload = cardType === "birthday"
            ? { card_type: "birthday", customer_id: customerId }
            : { card_type: "order", order_id: orderId, followup_window: followupWindow };
        fetch("/followup/complete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        }).catch(function() {});
    }
});

function jobLabel(j) {
    if (!j) return "";
    if (j.type === "NEW_CUSTOMER") return "New customer";
    if (j.type === "NEW_ORDER_ROW") return "Order";
    if (j.type === "IMPORT_CUSTOMERS") return "Customer import";
    return j.type;
}

async function refreshJobs() {
    try {
        const res = await fetch("/jobs");
        const data = await res.json();
        const jobs = data.jobs || [];

        if (!jobsInitialized) {
            // Seed the map with current state — no toasts for pre-existing jobs
            for (const j of jobs) trackedJobs.set(j.id, j.status);
            jobsInitialized = true;
            return;
        }

        let newestNewJob = null;

        for (const j of jobs) {
            // Skip silent background sync jobs
            if ((j.payload || {}).silent_initial_sync) {
                trackedJobs.set(j.id, j.status);
                continue;
            }

            const prevStatus = trackedJobs.get(j.id);

            if (prevStatus === undefined) {
                // Brand new job — track it; announce only the newest one
                trackedJobs.set(j.id, j.status);
                if (!newestNewJob || j.id > newestNewJob.id) newestNewJob = j;
            } else if (j.status !== prevStatus) {
                // Status changed — show a completion toast for every job
                trackedJobs.set(j.id, j.status);
                if (j.status === "done") {
                    showToast("✅ " + (j.status_msg || "Complete"));
                } else if (j.status === "failed") {
                    const label = jobLabel(j);
                    showToast("❌ " + (j.status_msg || "Job failed"), label ? `• ${label}` : "");
                }
            }
        }

        // Announce the newest new job (queued/running state)
        if (newestNewJob) {
            const j = newestNewJob;
            const label = jobLabel(j);
            if (j.status === "queued") {
                showToast("🕒 Queued for MyCustomers", label ? `• ${label}` : "");
            } else if (j.status === "running") {
                showToast("▶️ Working…", label ? `• ${label}` : "");
            } else if (j.status === "done") {
                showToast("✅ " + (j.status_msg || "Complete"));
            } else if (j.status === "failed") {
                showToast("❌ " + (j.status_msg || "Job failed"), label ? `• ${label}` : "");
            }
        }

        // Prune jobs that have aged off the server's return list
        const serverIds = new Set(jobs.map(j => j.id));
        for (const id of trackedJobs.keys()) {
            if (!serverIds.has(id)) trackedJobs.delete(id);
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
