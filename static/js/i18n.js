// t(key, params): the page's translated strings. The server writes them into #i18n-data (see base.html).
// The JSON is read on first use, so script order does not matter.
(function () {
    var data = null;

    function load() {
        data = {};
        try {
            var el = document.getElementById("i18n-data");
            if (el) data = JSON.parse(el.textContent);
        } catch (e) {
            data = {};
        }
    }

    window.t = function (key, params) {
        if (data === null) load();
        var text = Object.prototype.hasOwnProperty.call(data, key) ? data[key] : key;
        if (!params) return text;
        return text.replace(/\{([a-z_0-9]+)\}/g, function (match, name) {
            return Object.prototype.hasOwnProperty.call(params, name) ? params[name] : match;
        });
    };
})();
