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

function checkEmailMatch() {
    const em1 = document.getElementById("email");
    const em2 = document.getElementById("email2");
    if (!em2.value) return;
    if (em1.value.toLowerCase() !== em2.value.toLowerCase()) {
        showEmailError("Email addresses do not match.");
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
            showEmailError('An account with that email already exists. <a href="/login">Log in instead?</a>');
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
        showPwError("Passwords do not match.", null);
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
        showEmailError("Email addresses do not match.");
        em2.focus();
        return;
    }

    const pw1 = document.getElementById("pw1");
    const pw2 = document.getElementById("pw2");

    if ((pw1.value || "").length < 8) {
        e.preventDefault();
        showPwError("Password must be at least 8 characters.", pw1);
        return;
    }

    if (pw1.value !== pw2.value) {
        e.preventDefault();
        showPwError("Passwords do not match.", pw2);
        return;
    }
});
