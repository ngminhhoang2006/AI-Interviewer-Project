// Grading progress page: polls the server for "7 of 10 questions graded" and a time estimate, and opens the report
// when grading is done.
document.addEventListener("DOMContentLoaded", () => {
    const cfg = document.getElementById("gradingConfig");
    if (!cfg) return;

    const statusUrl = cfg.dataset.statusUrl;
    const reportUrl = cfg.dataset.reportUrl;
    const bar = document.getElementById("gradeBar");
    const countEl = document.getElementById("gradeCount");
    const etaEl = document.getElementById("gradeEta");
    const progressBox = document.getElementById("gradeProgress");
    const errorBox = document.getElementById("gradeError");

    // Only touch the DOM when the text changes, so screen readers don't repeat it every second
    function setText(el, text) {
        if (el.textContent !== text) el.textContent = text;
    }

    function formatTime(seconds) {
        const total = Math.max(0, Math.round(seconds));
        return Math.floor(total / 60) + ":" + String(total % 60).padStart(2, "0");
    }

    function render(s) {
        // The bar counts the final summary as one more step after the questions
        bar.value = s.total >= 0 ? Math.round((s.done / (s.total + 1)) * 100) : 0;

        if (s.stage === "summary") {
            setText(countEl, t("js.grade_summary"));
        } else {
            setText(countEl, t("js.grade_progress", { done: s.done, total: s.total }));
        }

        if (s.eta === null || s.eta === undefined) {
            setText(etaEl, t("js.grade_eta_wait"));
        } else if (s.eta < 1) {
            setText(etaEl, t("js.grade_eta_soon"));
        } else {
            setText(etaEl, t("js.grade_eta", { time: formatTime(s.eta) }));
        }
    }

    async function poll() {
        let next = true;
        try {
            const res = await fetch(statusUrl, { cache: "no-store" });
            const s = await res.json();

            if (s.state === "done" || s.state === "missing") {
                // Done: show the report. Missing (server restarted): the report page starts grading again.
                next = false;
                if (s.state === "done") bar.value = 100;
                window.location.replace(reportUrl);
            } else if (s.state === "error") {
                next = false;
                progressBox.hidden = true;
                errorBox.hidden = false;
            } else {
                render(s);
            }
        } catch (err) {
            console.error("Could not read grading status:", err);   // network hiccup: keep trying
        }
        if (next) setTimeout(poll, 1000);
    }

    setText(etaEl, t("js.grade_eta_wait"));
    poll();
});
