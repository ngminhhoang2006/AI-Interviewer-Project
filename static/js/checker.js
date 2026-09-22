document.addEventListener("DOMContentLoaded", () => {
    const searchInput = document.getElementById("searchInput");
    if (!searchInput) return; // Admin-only section not present for this user

    window.searchCandidate = async function () {
        const query = searchInput.value.trim();
        const resultsDiv = document.getElementById("searchResults");
        const reportDiv = document.getElementById("reportContainer");

        if (!query) return alert("Please enter a candidate name.");

        resultsDiv.innerHTML = "Searching disk records...";
        reportDiv.classList.add("hidden");

        try {
            const res = await fetch("/api/search", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: query })
            });

            const data = await res.json();
            resultsDiv.innerHTML = "";

            if (data.message) {
                resultsDiv.innerHTML = `<p class="empty-msg">${data.message}</p>`;
                return;
            }

            data.candidates.forEach(cand => {
                const card = document.createElement("div");
                card.className = "candidate-item";
                let reportsHTML = cand.reports.length === 0
                    ? "<p class='empty-msg'>No report file (.md) found.</p>"
                    : cand.reports.map(reportName => `
                        <div class="report-item-row">
                            <span class="file-name">📄 ${reportName}</span>
                            <button class="btn btn-teal-sm" onclick="viewReport('${cand.folder_path}', '${reportName}')">View</button>
                        </div>
                    `).join('');

                card.innerHTML = `<h4>Candidate Folder: <strong>${cand.folder_name}</strong></h4>${reportsHTML}`;
                resultsDiv.appendChild(card);
            });
        } catch (err) {
            resultsDiv.innerHTML = "<p class='empty-msg'>Failed to retrieve search results.</p>";
        }
    };

    window.viewReport = async function (folderPath, reportFilename) {
        const res = await fetch("/api/get_report", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ folder_path: folderPath, report_filename: reportFilename })
        });
        const data = await res.json();
        if (data.error) return alert(data.error);

        document.getElementById("reportTitle").innerText = `Report: ${data.candidate}`;
        document.getElementById("reportContent").innerHTML = data.content_html;
        document.getElementById("reportContainer").classList.remove("hidden");
    };

    window.closeReport = function () {
        document.getElementById("reportContainer").classList.add("hidden");
    };
});
