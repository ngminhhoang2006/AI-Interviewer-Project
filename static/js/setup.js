document.addEventListener("DOMContentLoaded", () => {
    let currentCandidateFolder = "";

    function updateFileName(input) {
        const display = document.getElementById("fileNameDisplay");
        if (input.files && input.files[0]) {
            display.innerText = "📄 " + input.files[0].name;
            display.classList.add("file-selected");
        } else {
            display.innerText = "Click or drag PDF resume here";
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

        document.getElementById("status").innerText = "Parsing CV PDF...";

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
                        ? "No text could be read from this PDF (it may be a scanned image), so the questions will only use the position. Please type your name below."
                        : data.name_detected === false
                            ? "CV parsed, but the name could not be detected. Please type it below."
                            : "CV parsed successfully!";
            } else {
                document.getElementById("status").innerText = "Error: " + (data.error || "Failed to upload CV");
            }
        } catch (err) {
            document.getElementById("status").innerText = "Server error uploading CV.";
        }
    };

    document.getElementById("btnGenerate").onclick = async () => {
        const language = document.getElementById("language").value;
        const jobInput = document.getElementById("jobPosition");
        const jobPosition = jobInput.value.replace(/\s+/g, " ").trim();

        if (!jobPosition) {
            document.getElementById("status").innerText = "Please enter the position you're applying for.";
            jobInput.focus();
            return;
        }

        document.getElementById("status").innerText = "Generating questions via AI (this may take a few moments)...";

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
                document.getElementById("status").innerText = "Error: " + (data.error || ("Failed to generate questions (HTTP " + response.status + ")"));
            }
        } catch (err) {
            document.getElementById("status").innerText = "Server error generating questions.";
        }
    };
});
