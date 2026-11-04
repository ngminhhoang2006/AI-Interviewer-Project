/* Home hero ground: an ASCII field on an 8 by 16 cell.
   Raw characters on the left (a résumé as it arrives), resolved lattice on the right (the scored report).
   The centre stays clear so the headline never sits on a dense cell. Colours come from the CSS tokens.
   The field is drawn once and redraws only while the pointer moves over it, so nothing loops on its own.
   Without script the hero keeps its CSS dot grid. */
(function () {
    "use strict";
    var hero = document.querySelector(".hero");
    if (!hero) return;

    var canvas = document.createElement("canvas");
    canvas.className = "hero-field";
    canvas.setAttribute("aria-hidden", "true");
    hero.insertBefore(canvas, hero.firstChild);
    var ctx = canvas.getContext("2d");
    if (!ctx) { canvas.remove(); return; }
    hero.classList.add("has-field");

    var css = getComputedStyle(document.documentElement);
    function token(name) { return css.getPropertyValue(name).trim(); }
    var CELL_W = parseFloat(token("--cell-w")) || 8;
    var CELL_H = parseFloat(token("--cell-h")) || 16;
    var tints = [token("--color-glyph-1"), token("--color-glyph-2"), token("--color-glyph-3"), token("--color-glyph-4")];
    var densest = token("--color-accent-deep");
    var mono = token("--font-outlier") || "monospace";
    var RAW = " .:-=+*#%@";
    var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    var cols = 0, rows = 0, dpr = 1, pointer = null;

    function size() {
        var rect = hero.getBoundingClientRect();
        dpr = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.round(rect.width * dpr);
        canvas.height = Math.round(rect.height * dpr);
        cols = Math.floor(rect.width / CELL_W);
        rows = Math.floor(rect.height / CELL_H);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.font = (CELL_H - 3) + "px " + mono;
        ctx.textBaseline = "top";
    }

    // cheap smooth noise from layered sines, in 0..1
    function noise(x, y, t) {
        var v = Math.sin(x * 0.21 + t) + Math.sin(y * 0.37 - t * 0.7) + Math.sin((x + y) * 0.13 + t * 0.5) + Math.sin(Math.hypot(x - 40, y - 12) * 0.19 - t);
        return (v + 4) / 8;
    }

    function draw(t) {
        ctx.clearRect(0, 0, canvas.width / dpr, canvas.height / dpr);
        for (var r = 0; r < rows; r++) {
            for (var c = 0; c < cols; c++) {
                var u = c / cols, v = r / rows;
                // clear zone behind the text: an ellipse that keeps its centre empty
                var dx = (u - 0.5) / 0.42, dy = (v - 0.5) / 0.62;
                var edge = Math.min(1, Math.max(0, dx * dx + dy * dy - 0.6));
                var d = noise(c, r, t) * edge;
                if (pointer) {
                    var lx = (c * CELL_W - pointer.x) / 90, ly = (r * CELL_H - pointer.y) / 90;
                    d += Math.max(0, 1 - (lx * lx + ly * ly)) * 0.35 * edge;
                }
                if (d < 0.2) continue;
                var level = Math.min(3, Math.floor((d - 0.2) * 5));
                var ch;
                if (u < 0.5) {
                    // raw: a character chosen by density, jittered per cell
                    ch = RAW.charAt(Math.min(RAW.length - 1, Math.floor(d * RAW.length * 1.1 + ((c * 7 + r * 13) % 3))));
                } else {
                    // resolved: the same density snapped to a lattice
                    var onLattice = c % 4 === 0 && r % 2 === 0;
                    ch = onLattice ? (level > 0 ? "+" : ".") : (c % 4 === 0 ? "|" : (r % 2 === 0 && level > 0 ? "-" : ""));
                    if (!ch) continue;
                }
                ctx.fillStyle = (level === 3 && d > 0.8) ? densest : tints[u < 0.5 ? level : Math.min(3, level + 1)];
                ctx.fillText(ch, c * CELL_W, r * CELL_H);
            }
        }
    }

    var T0 = 2.4;       // a fixed phase of the noise, chosen for a balanced starting picture
    var queued = false;
    function redraw() {
        if (queued) return;
        queued = true;
        requestAnimationFrame(function () { queued = false; draw(T0); });
    }

    size();
    draw(T0);

    if (!reduced) {
        hero.addEventListener("pointermove", function (e) {
            var rect = hero.getBoundingClientRect();
            pointer = { x: e.clientX - rect.left, y: e.clientY - rect.top };
            redraw();
        });
        hero.addEventListener("pointerleave", function () { pointer = null; redraw(); });
    }

    if ("ResizeObserver" in window) {
        new ResizeObserver(function () { size(); draw(T0); }).observe(hero);
    }
})();
