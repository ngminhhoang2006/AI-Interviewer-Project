/* CSRF protection for fetch(): every same-origin POST/PUT/PATCH/DELETE automatically gets the
 * X-CSRFToken header, using the token the server put in <meta name="csrf-token"> (see base.html).
 * Loaded in <head> so it is active before any page script calls fetch(). Cross-origin requests
 * never receive the token. */
(function () {
    "use strict";
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (!meta || !window.fetch) return;
    const token = meta.getAttribute("content");
    const SAFE_METHODS = ["GET", "HEAD", "OPTIONS", "TRACE"];
    const originalFetch = window.fetch;

    window.fetch = function (input, init) {
        init = init || {};
        const isRequest = typeof Request !== "undefined" && input instanceof Request;
        const method = String(init.method || (isRequest ? input.method : "GET")).toUpperCase();

        if (!SAFE_METHODS.includes(method)) {
            const url = new URL(isRequest ? input.url : String(input), window.location.href);
            if (url.origin === window.location.origin) {
                const headers = new Headers(init.headers || (isRequest ? input.headers : undefined));
                headers.set("X-CSRFToken", token);
                init = Object.assign({}, init, { headers: headers });
            }
        }
        return originalFetch.call(this, input, init);
    };
})();
