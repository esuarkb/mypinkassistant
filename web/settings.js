(function () {
    const enBtn = document.getElementById("langEn");
    const esBtn = document.getElementById("langEs");
    const lang = document.getElementById("language");
    const form = document.getElementById("settingsForm");

    if (!enBtn || !esBtn || !lang) return;

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

    enBtn.addEventListener("click", () => setLang("en"));
    esBtn.addEventListener("click", () => setLang("es"));

    // Ensure active state matches hidden input on load
    setLang((lang.value || "en").trim());
})();