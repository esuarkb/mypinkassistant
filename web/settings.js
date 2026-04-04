(function () {
    // -------------------------
    // Language toggle (your existing code)
    // -------------------------
    const enBtn = document.getElementById("langEn");
    const esBtn = document.getElementById("langEs");
    const lang = document.getElementById("language");

    function setLang(v) {
        lang.value = v;
        if (v === "es") {
            esBtn.classList.add("active");
            enBtn.classList.remove("active");
        } else {
            enBtn.classList.add("active");
            esBtn.classList.remove("active");
        }
    }

    function saveLang(v) {
        setLang(v);
        const fd = new FormData();
        fd.append("language", v);
        fetch("/settings/language", { method: "POST", body: fd });
    }

    if (enBtn && esBtn && lang) {
        enBtn.addEventListener("click", () => saveLang("en"));
        esBtn.addEventListener("click", () => saveLang("es"));
        setLang((lang.value || "en").trim());
    }

    // -------------------------
    // Referral link copy (robust)
    // -------------------------
    const copyBtn = document.getElementById("copyRefBtn");
    const refInput = document.getElementById("refLink");
    const msg = document.getElementById("copyRefMsg");

    function setMsg(text, ok) {
        if (!msg) return;
        msg.textContent = text;
        msg.style.color = ok ? "" : "#c2185b";
        clearTimeout(window.__copyMsgTimer);
        window.__copyMsgTimer = setTimeout(() => {
            msg.textContent = "";
            msg.style.color = "";
        }, 2500);
    }

    function selectInput(input) {
        try {
            input.focus({ preventScroll: true });
            input.select();
            input.setSelectionRange(0, input.value.length);
        } catch (e) { }
    }

    async function tryClipboard(text) {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
            return true;
        }
        return false;
    }

    function tryExecCommandCopy(input) {
        try {
            selectInput(input);
            return document.execCommand("copy");
        } catch (e) {
            return false;
        }
    }

    if (copyBtn && refInput) {
        copyBtn.addEventListener("click", async (e) => {
            e.preventDefault();
            e.stopPropagation();

            const text = (refInput.value || "").trim();
            if (!text) {
                setMsg("Nothing to copy.", false);
                return;
            }

            // show *something* immediately so you know click fired
            setMsg("Copying…", true);
            selectInput(refInput);

            try {
                const ok = await tryClipboard(text);
                if (ok) {
                    setMsg("Copied! ✅", true);
                    return;
                }
            } catch (err) { }

            const ok2 = tryExecCommandCopy(refInput);
            if (ok2) {
                setMsg("Copied! ✅", true);
                return;
            }

            setMsg("Press and hold to copy (or copy highlighted text).", false);
            window.prompt("Copy your referral link:", text);
        });

        // Helpful for debugging in logs/console
        console.log("[settings] Copy handler attached ✅");
    } else {
        console.log("[settings] Copy elements missing:", {
            copyBtn: !!copyBtn,
            refInput: !!refInput
        });
    }
})();