// Marks the page as script-capable so the CSS may collapse the nav into a labelled Menu button.
// Without script the links stay visible.
(function () {
    document.documentElement.classList.add("nav-js");
    // Phones start collapsed, so the menu never flashes open while the page loads
    if (window.matchMedia("(max-width: 56rem)").matches) document.documentElement.classList.add("nav-compact");

    document.addEventListener("DOMContentLoaded", function () {
        var nav = document.querySelector(".navbar");
        var toggle = document.getElementById("navToggle");
        if (!nav || !toggle) return;
        var root = document.documentElement;
        var brand = nav.querySelector(".brand");
        var links = nav.querySelector(".nav-links");

        // Show the full row; if the links wrap below the brand, collapse into the Menu button instead.
        function fit() {
            root.classList.remove("nav-compact");
            var wraps = links.getBoundingClientRect().top > brand.getBoundingClientRect().bottom - 4;
            if (wraps || window.matchMedia("(max-width: 56rem)").matches) root.classList.add("nav-compact");
        }
        fit();
        window.addEventListener("resize", fit);
        window.addEventListener("load", fit);
        if (document.fonts && document.fonts.ready) document.fonts.ready.then(fit);

        function setOpen(open) {
            nav.classList.toggle("nav-open", open);
            toggle.setAttribute("aria-expanded", open ? "true" : "false");
            toggle.textContent = open ? toggle.dataset.labelOpen : toggle.dataset.labelClosed;
        }

        toggle.addEventListener("click", function () {
            setOpen(!nav.classList.contains("nav-open"));
        });

        var langSelect = document.getElementById("uiLang");
        if (langSelect) {
            langSelect.addEventListener("change", function () { langSelect.form.submit(); });
        }

        document.addEventListener("keydown", function (e) {
            if (e.key === "Escape" && nav.classList.contains("nav-open")) {
                setOpen(false);
                toggle.focus();
            }
        });
    });
})();
