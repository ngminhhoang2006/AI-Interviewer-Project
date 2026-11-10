document.addEventListener("DOMContentLoaded", () => {
    let currentCandidateFolder = "";

    function updateFileName(input) {
        const display = document.getElementById("fileNameDisplay");
        if (input.files && input.files[0]) {
            display.innerText = input.files[0].name;
            display.classList.add("file-selected");
        } else {
            display.innerText = t("setup.drop");
            display.classList.remove("file-selected");
        }
    }
    // (no inline onchange= attribute: the Content-Security-Policy blocks those)
    const cvInput = document.getElementById("cv_file");
    if (cvInput) cvInput.addEventListener("change", () => updateFileName(cvInput));

    document.getElementById("uploadForm").onsubmit = async (e) => {
        e.preventDefault();
        const formData = new FormData();
        formData.append("cv_file", document.getElementById("cv_file").files[0]);

        document.getElementById("status").innerText = t("js.parsing");

        try {
            const response = await fetch("/upload_cv", { method: "POST", body: formData });
            const data = await response.json();

            if (response.ok) {
                currentCandidateFolder = data.candidate_folder;
                document.getElementById("candidateName").value = data.name_detected === false ? "" : data.candidate;
                document.getElementById("step-upload").classList.add("hidden");
                document.getElementById("step-questions").classList.remove("hidden");
                document.getElementById("status").innerText =
                    data.text_extracted === false
                        ? t("js.cv_no_text")
                        : data.name_detected === false
                            ? t("js.cv_no_name")
                            : t("js.cv_ok");
            } else {
                document.getElementById("status").innerText = t("js.err", { message: data.error || t("js.upload_failed") });
            }
        } catch (err) {
            document.getElementById("status").innerText = t("js.upload_server");
        }
    };

    // Question generation runs on the server in the background; this follows it and opens the next page when done.
    const genProgress = document.getElementById("genProgress");
    const genBar = document.getElementById("genBar");
    const genEta = document.getElementById("genEta");
    const btnGenerate = document.getElementById("btnGenerate");

    function formatTime(seconds) {
        const total = Math.max(0, Math.round(seconds));
        return Math.floor(total / 60) + ":" + String(total % 60).padStart(2, "0");
    }

    // Only touch the DOM when the text changes, so screen readers don't repeat it every second
    function setText(el, text) {
        if (el.textContent !== text) el.textContent = text;
    }

    function showGenerationFailed(message) {
        genProgress.hidden = true;
        btnGenerate.disabled = false;
        document.getElementById("status").innerText = message;
    }

    function followGeneration(statusUrl) {
        genProgress.hidden = false;
        genBar.value = 0;
        setText(genEta, t("js.grade_eta_wait"));

        async function poll() {
            let next = true;
            try {
                const res = await fetch(statusUrl, { cache: "no-store" });
                const s = await res.json();

                if (s.state === "done") {
                    next = false;
                    genBar.value = 100;
                    window.location.href = s.redirect;
                } else if (s.state === "error") {
                    next = false;
                    showGenerationFailed(t("js.err", { message: s.error || t("js.gen_failed", { status: res.status }) }));
                } else if (s.state === "missing") {
                    next = false;                      // the server forgot the job (e.g. it was restarted)
                    showGenerationFailed(t("js.gen_server"));
                } else {
                    genBar.value = s.percent;
                    if (s.eta === null || s.eta === undefined) {
                        setText(genEta, t("js.grade_eta_wait"));
                    } else if (s.eta < 1) {
                        setText(genEta, t("js.grade_eta_soon"));
                    } else {
                        setText(genEta, t("js.grade_eta", { time: formatTime(s.eta) }));
                    }
                }
            } catch (err) {
                console.error("Could not read generation status:", err);   // network hiccup: keep trying
            }
            if (next) setTimeout(poll, 1000);
        }
        poll();
    }

    btnGenerate.onclick = async () => {
        const language = document.getElementById("language").value;
        const jobInput = document.getElementById("jobPosition");
        const jobPosition = jobInput.value.replace(/\s+/g, " ").trim();

        if (!jobPosition) {
            document.getElementById("status").innerText = t("js.need_position");
            jobInput.focus();
            return;
        }

        document.getElementById("status").innerText = t("js.generating");
        btnGenerate.disabled = true;               // one generation at a time

        try {
            const response = await fetch("/generate_questions", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ candidate_folder: currentCandidateFolder, language: language, job_position: jobPosition, candidate_name: document.getElementById("candidateName").value.trim() })
            });

            const data = await response.json().catch(() => ({}));
            if (response.ok && data.status_url) {
                followGeneration(data.status_url);
            } else if (response.ok && data.redirect) {
                window.location.href = data.redirect;   // a server that generated the questions before replying
            } else {
                showGenerationFailed(t("js.err", { message: data.error || t("js.gen_failed", { status: response.status }) }));
            }
        } catch (err) {
            showGenerationFailed(t("js.gen_server"));
        }
    };
});
