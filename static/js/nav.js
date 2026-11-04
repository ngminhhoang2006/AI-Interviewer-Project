// Marks the page as script-capable so the CSS may collapse the nav into a labelled Menu button.
// Without script the links stay visible.
(function () {
    document.documentElement.classList.add("nav-js");

    document.addEventListener("DOMContentLoaded", function () {
        var nav = document.querySelector(".navbar");
        var toggle = document.getElementById("navToggle");
        if (!nav || !toggle) return;

        function setOpen(open) {
            nav.classList.toggle("nav-open", open);
            toggle.setAttribute("aria-expanded", open ? "true" : "false");
            toggle.textContent = open ? "Close" : "Menu";
        }

        toggle.addEventListener("click", function () {
            setOpen(!nav.classList.contains("nav-open"));
        });

        document.addEventListener("keydown", function (e) {
            if (e.key === "Escape" && nav.classList.contains("nav-open")) {
                setOpen(false);
                toggle.focus();
            }
        });
    });
})();
