function showPwError(msg, focusEl) {
    const err = document.getElementById("pwErr");
    const pw1 = document.getElementById("pw1");
    const pw2 = document.getElementById("pw2");
    err.textContent = msg;
    err.style.display = "block";
    pw1.classList.toggle("field-error", focusEl === pw1);
    pw2.classList.toggle("field-error", focusEl === pw2);
    if (focusEl) focusEl.focus();
}

function clearPwError() {
    const err = document.getElementById("pwErr");
    err.style.display = "none";
    err.textContent = "";
    document.getElementById("pw1").classList.remove("field-error");
    document.getElementById("pw2").classList.remove("field-error");
}

function showEmailError(msg) {
    const err = document.getElementById("emailErr");
    const em2 = document.getElementById("email2");
    err.innerHTML = msg;
    err.style.display = "block";
    em2.classList.add("field-error");
}

function clearEmailError() {
    const err = document.getElementById("emailErr");
    err.style.display = "none";
    err.textContent = "";
    document.getElementById("email2").classList.remove("field-error");
}

window.currentLang = "en";

function setLang(lang) {
    window.currentLang = lang;
    var langInput = document.getElementById("language");
    if (langInput) langInput.value = lang;

    Array.from(document.querySelectorAll("[data-en][data-es]")).forEach(function(el) {
        el.innerHTML = el.getAttribute("data-" + lang);
    });

    Array.from(document.querySelectorAll("[data-en-ph][data-es-ph]")).forEach(function(el) {
        el.setAttribute("placeholder", el.getAttribute("data-" + lang + "-ph"));
    });

    var termsLabel = document.getElementById("termsLabel");
    if (termsLabel) {
        if (lang === "es") {
            termsLabel.innerHTML = 'Acepto los <a href="/legal#terms" target="_blank">T\u00e9rminos y Condiciones</a> y la <a href="/legal#privacy" target="_blank">Pol\u00edtica de Privacidad</a>';
        } else {
            termsLabel.innerHTML = 'I agree to the <a href="/legal#terms" target="_blank">Terms &amp; Conditions</a> and <a href="/legal#privacy" target="_blank">Privacy Policy</a>';
        }
    }

    var enBtn = document.getElementById("langEn");
    var esBtn = document.getElementById("langEs");
    if (enBtn) enBtn.classList.toggle("active", lang === "en");
    if (esBtn) esBtn.classList.toggle("active", lang === "es");
}

var _langEnBtn = document.getElementById("langEn");
var _langEsBtn = document.getElementById("langEs");
if (_langEnBtn) {
    _langEnBtn.addEventListener("click", function(e) { e.preventDefault(); setLang("en"); });
}
if (_langEsBtn) {
    _langEsBtn.addEventListener("click", function(e) { e.preventDefault(); setLang("es"); });
}

const i18n = {
    en: {
        emailNoMatch:  "Email addresses do not match.",
        emailExists:   'An account with that email already exists. <a href="/login">Log in instead?</a>',
        pwShort:       "Password must be at least 8 characters.",
        pwNoMatch:     "Passwords do not match.",
    },
    es: {
        emailNoMatch:  "Los correos electrónicos no coinciden.",
        emailExists:   'Ya existe una cuenta con ese correo. <a href="/login">¿Iniciar sesión?</a>',
        pwShort:       "La contraseña debe tener al menos 8 caracteres.",
        pwNoMatch:     "Las contraseñas no coinciden.",
    },
};

function t(key) {
    const lang = (window.currentLang || "en");
    return (i18n[lang] || i18n.en)[key];
}

function checkEmailMatch() {
    const em1 = document.getElementById("email");
    const em2 = document.getElementById("email2");
    if (!em2.value) return;
    if (em1.value.toLowerCase() !== em2.value.toLowerCase()) {
        showEmailError(t("emailNoMatch"));
    } else {
        clearEmailError();
    }
}

document.getElementById("email").addEventListener("blur", async function () {
    const val = this.value.trim();
    if (!val) return;
    try {
        const res = await fetch("/check-email?email=" + encodeURIComponent(val));
        const data = await res.json();
        if (data.exists) {
            showEmailError(t("emailExists"));
        } else {
            clearEmailError();
        }
    } catch (e) { /* ignore network errors */ }
});

document.getElementById("email2").addEventListener("blur", checkEmailMatch);
document.getElementById("email2").addEventListener("input", function () {
    // Once they've seen an error, clear it live as they fix it
    const err = document.getElementById("emailErr");
    if (err.style.display !== "none") checkEmailMatch();
});
document.getElementById("email").addEventListener("input", function () {
    const err = document.getElementById("emailErr");
    if (err.style.display !== "none") checkEmailMatch();
});

function checkPasswordMatch() {
    const pw1 = document.getElementById("pw1");
    const pw2 = document.getElementById("pw2");
    if (!pw2.value) return;
    if (pw1.value !== pw2.value) {
        showPwError(t("pwNoMatch"), null);
    } else {
        clearPwError();
    }
}

document.getElementById("pw2").addEventListener("blur", checkPasswordMatch);
document.getElementById("pw2").addEventListener("input", function () {
    const err = document.getElementById("pwErr");
    if (err.style.display !== "none") checkPasswordMatch();
});
document.getElementById("pw1").addEventListener("input", function () {
    const err = document.getElementById("pwErr");
    if (err.style.display !== "none") checkPasswordMatch();
});

document.getElementById("onboardForm").addEventListener("submit", function (e) {
    clearPwError();
    clearEmailError();

    const em1 = document.getElementById("email");
    const em2 = document.getElementById("email2");
    if (em1.value.toLowerCase() !== em2.value.toLowerCase()) {
        e.preventDefault();
        showEmailError(t("emailNoMatch"));
        em2.focus();
        return;
    }

    const pw1 = document.getElementById("pw1");
    const pw2 = document.getElementById("pw2");

    if ((pw1.value || "").length < 8) {
        e.preventDefault();
        showPwError(t("pwShort"), pw1);
        return;
    }

    if (pw1.value !== pw2.value) {
        e.preventDefault();
        showPwError(t("pwNoMatch"), pw2);
        return;
    }
});
