document.addEventListener("DOMContentLoaded", () => {
    const searchInput = document.getElementById("searchInput");
    if (!searchInput) return; // Admin-only section not present for this user

    const resultsDiv = document.getElementById("searchResults");
    const reportDiv = document.getElementById("reportContainer");

    // Everything below that shows server data uses textContent / DOM nodes, never innerHTML.
    // Folder names come from the name on an uploaded CV, so they are attacker-controlled.
    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function showMessage(text) {
        resultsDiv.replaceChildren(el("p", "empty-msg", text));
    }

    async function searchCandidate() {
        const query = searchInput.value.trim();

        if (!query) {
            return alertDialog({
                title: "Candidate name required",
                message: "Please enter a candidate name to search.",
            }).then(() => searchInput.focus());
        }

        showMessage("Searching disk records...");
        reportDiv.classList.add("hidden");

        try {
            const res = await fetch("/api/search", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: query })
            });

            const data = await res.json();
            resultsDiv.replaceChildren();

            if (data.error || data.message) {
                showMessage(String(data.error || data.message));
                return;
            }

            data.candidates.forEach(cand => {
                const card = el("div", "candidate-item");

                const title = el("h4", null, "Candidate Folder: ");
                title.appendChild(el("strong", null, cand.folder_name));
                card.appendChild(title);

                card.appendChild(el("p", null,
                    `CV Score: ${cand.cv_score} | Interview Score: ${cand.interview_score}`));

                if (cand.reports.length === 0) {
                    card.appendChild(el("p", "empty-msg", "No report file (.md) found."));
                } else {
                    cand.reports.forEach(reportName => {
                        const row = el("div", "report-item-row");
                        row.appendChild(el("span", "file-name", "📄 " + reportName));

                        const viewBtn = el("button", "btn btn-teal-sm", "View");
                        viewBtn.type = "button";
                        // Values are captured in a closure - they are never parsed as code or HTML.
                        viewBtn.addEventListener("click", () => viewReport(cand.folder_path, reportName));
                        row.appendChild(viewBtn);

                        card.appendChild(row);
                    });
                }
                resultsDiv.appendChild(card);
            });
        } catch (err) {
            showMessage("Failed to retrieve search results.");
        }
    }

    async function viewReport(folderPath, reportFilename) {
        const res = await fetch("/api/get_report", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ folder_path: folderPath, report_filename: reportFilename })
        });
        const data = await res.json();
        if (data.error) {
            return alertDialog({ title: "Couldn't open the report", message: String(data.error) });
        }

        document.getElementById("reportTitle").textContent = `Report: ${data.candidate}`;
        // content_html is Markdown rendered from LLM output; the server sanitizes it with nh3
        // (see check_app.get_report) and the CSP blocks inline script as a second layer.
        document.getElementById("reportContent").innerHTML = data.content_html;
        reportDiv.classList.remove("hidden");
    }

    function closeReport() {
        reportDiv.classList.add("hidden");
    }

    // Event wiring (replaces the inline onclick= / onkeyup= attributes, which the CSP blocks)
    document.getElementById("searchBtn").addEventListener("click", searchCandidate);
    searchInput.addEventListener("keyup", (event) => {
        if (event.key === "Enter") searchCandidate();
    });
    document.getElementById("closeReportBtn").addEventListener("click", closeReport);
});
