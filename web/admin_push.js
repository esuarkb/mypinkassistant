/* Admin push-alert enable/test buttons (2026-07-12). Loaded ONLY on /admin —
   consultants never see a notification prompt. External file per CSP. */
document.addEventListener('DOMContentLoaded', function () {
    var btnEnable = document.getElementById('btn-push-enable');
    var btnTest = document.getElementById('btn-push-test');
    var status = document.getElementById('push-status');
    if (!btnEnable) return;

    function say(msg) { if (status) status.textContent = msg; }

    function b64ToUint8(base64) {
        var padding = '='.repeat((4 - (base64.length % 4)) % 4);
        var raw = atob((base64 + padding).replace(/-/g, '+').replace(/_/g, '/'));
        var arr = new Uint8Array(raw.length);
        for (var i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
        return arr;
    }

    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        say('Push not supported in this browser. On iPhone: open from the installed home-screen app.');
        btnEnable.disabled = true;
        return;
    }

    // Reflect current state on load
    navigator.serviceWorker.getRegistration('/').then(function (reg) {
        if (!reg) return;
        reg.pushManager.getSubscription().then(function (sub) {
            if (sub) {
                btnEnable.textContent = 'Push alerts enabled ✓ (tap to disable)';
            }
        });
    });

    btnEnable.addEventListener('click', function () {
        var vapid = btnEnable.getAttribute('data-vapid') || '';
        if (!vapid) { say('Server is missing VAPID keys.'); return; }
        say('Working…');

        navigator.serviceWorker.register('/sw.js').then(function (reg) {
            return navigator.serviceWorker.ready.then(function () { return reg; });
        }).then(function (reg) {
            return reg.pushManager.getSubscription().then(function (existing) {
                if (existing) {
                    // Toggle off: unsubscribe + tell the server
                    return existing.unsubscribe().then(function () {
                        return fetch('/push/unsubscribe', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ endpoint: existing.endpoint }),
                        });
                    }).then(function () {
                        btnEnable.textContent = 'Enable push alerts 🔔';
                        say('Push alerts disabled on this device.');
                        return null;
                    });
                }
                return Notification.requestPermission().then(function (perm) {
                    if (perm !== 'granted') { say('Notifications were not allowed.'); return null; }
                    return reg.pushManager.subscribe({
                        userVisibleOnly: true,
                        applicationServerKey: b64ToUint8(vapid),
                    }).then(function (sub) {
                        return fetch('/push/subscribe', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(sub.toJSON()),
                        }).then(function (r) { return r.json(); }).then(function (data) {
                            if (data.ok) {
                                btnEnable.textContent = 'Push alerts enabled ✓ (tap to disable)';
                                say('Enabled — try a test push.');
                            } else {
                                say('Server rejected the subscription.');
                            }
                        });
                    });
                });
            });
        }).catch(function (e) {
            say('Error: ' + (e && e.message ? e.message : e));
        });
    });

    if (btnTest) {
        btnTest.addEventListener('click', function () {
            say('Sending…');
            fetch('/push/test', { method: 'POST' })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    say(data.sent > 0
                        ? 'Test sent to ' + data.sent + ' device(s).'
                        : 'No subscriptions found — enable push alerts first.');
                })
                .catch(function () { say('Test failed.'); });
        });
    }
});
