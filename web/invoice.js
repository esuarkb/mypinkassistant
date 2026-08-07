// Close button on the /invoice/{id} page (2026-08-06).
//
// The page is opened with window.open() from the chat bubble, so close() is
// permitted here — browsers only refuse it on windows the script did not open.
// If someone arrived another way (typed the URL, or the plain-href fallback
// fired because JS was off in the chat tab), close() is a silent no-op, so we
// step back through history instead: that restores the chat page as she left
// it, where reloading /app would hand her an empty conversation.
document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-close-window]");
    if (!btn) return;
    e.preventDefault();
    window.close();
    setTimeout(function () {
        if (history.length > 1) { history.back(); } else { location.href = "/app"; }
    }, 150);
});
