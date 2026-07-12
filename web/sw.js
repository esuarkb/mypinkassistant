/* MyPinkAssistant service worker — web push only (2026-07-12).
   Registered ONLY from the /admin page for now (admin alert pushes).
   When consultant push ships, move registration into app.js and this
   file serves both audiences unchanged. */

self.addEventListener('install', function (event) {
    self.skipWaiting();
});

self.addEventListener('activate', function (event) {
    event.waitUntil(self.clients.claim());
});

self.addEventListener('push', function (event) {
    var data = {};
    try {
        data = event.data ? event.data.json() : {};
    } catch (e) {
        data = { title: 'MyPinkAssistant', body: event.data ? event.data.text() : '' };
    }
    var title = data.title || 'MyPinkAssistant';
    var options = {
        body: data.body || '',
        data: { url: data.url || '/admin' },
        badge: '/web/icon-192.png',
        icon: '/web/icon-192.png',
        tag: data.tag || 'mpa-alert',
    };
    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', function (event) {
    event.notification.close();
    var url = (event.notification.data && event.notification.data.url) || '/admin';
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (wins) {
            for (var i = 0; i < wins.length; i++) {
                if (wins[i].url.indexOf(url) !== -1 && 'focus' in wins[i]) {
                    return wins[i].focus();
                }
            }
            return clients.openWindow(url);
        })
    );
});
