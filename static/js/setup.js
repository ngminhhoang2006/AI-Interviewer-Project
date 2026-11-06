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

    document.getElementById("btnGenerate").onclick = async () => {
        const language = document.getElementById("language").value;
        const jobInput = document.getElementById("jobPosition");
        const jobPosition = jobInput.value.replace(/\s+/g, " ").trim();

        if (!jobPosition) {
            document.getElementById("status").innerText = t("js.need_position");
            jobInput.focus();
            return;
        }

        document.getElementById("status").innerText = t("js.generating");

        try {
            const response = await fetch("/generate_questions", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ candidate_folder: currentCandidateFolder, language: language, job_position: jobPosition, candidate_name: document.getElementById("candidateName").value.trim() })
            });

            const data = await response.json().catch(() => ({}));
            if (response.ok) {
                window.location.href = data.redirect;
            } else {
                document.getElementById("status").innerText = t("js.err", { message: data.error || t("js.gen_failed", { status: response.status }) });
            }
        } catch (err) {
            document.getElementById("status").innerText = t("js.gen_server");
        }
    };
});
