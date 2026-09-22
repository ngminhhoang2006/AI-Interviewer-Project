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
    // Exposed so the inline onchange="updateFileName(this)" in the HTML keeps working
    window.updateFileName = updateFileName;

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
                document.getElementById("candidateName").innerText = data.candidate;
                document.getElementById("step-upload").classList.add("hidden");
                document.getElementById("step-questions").classList.remove("hidden");
                document.getElementById("status").innerText = "CV parsed successfully!";
            } else {
                document.getElementById("status").innerText = "Error: " + (data.error || "Failed to upload CV");
            }
        } catch (err) {
            document.getElementById("status").innerText = "Server error uploading CV.";
        }
    };

    document.getElementById("btnGenerate").onclick = async () => {
        const language = document.getElementById("language").value;
        document.getElementById("status").innerText = "Generating questions via AI (this may take a few moments)...";

        try {
            const response = await fetch("/generate_questions", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ candidate_folder: currentCandidateFolder, language: language })
            });

            const data = await response.json();
            if (response.ok) {
                window.location.href = data.redirect;
            } else {
                document.getElementById("status").innerText = "Error: " + (data.error || "Failed to generate questions");
            }
        } catch (err) {
            document.getElementById("status").innerText = "Server error generating questions.";
        }
    };
});
