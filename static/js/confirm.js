/* Confirmation dialogs for the nav bar (loaded from base.html on every page).
 *
 *  - Logout always asks "Log out?".
 *  - While window.interviewInProgress === true (set by interview.js), every nav bar link
 *    asks "Leave the interview?" because answers are only saved when the interview ends.
 *  - Back / refresh / closing the tab shows the browser's "Leave site?" warning in that case too.
 */
(function () {
    "use strict";

    // ------------------------------------------------------------------ dialog
    function confirmDialog(options) {
        const o = Object.assign(
            { title: "Are you sure?", message: "", confirmText: "Confirm", cancelText: "Cancel", danger: false, hideCancel: false },
            options || {}
        );

        return new Promise((resolve) => {
            const previouslyFocused = document.activeElement;

            const overlay = document.createElement("div");
            overlay.className = "confirm-overlay";

            const dialog = document.createElement("div");
            dialog.className = "confirm-dialog";
            dialog.setAttribute("role", "alertdialog");
            dialog.setAttribute("aria-modal", "true");
            dialog.setAttribute("aria-labelledby", "confirmTitle");
            dialog.setAttribute("aria-describedby", "confirmMessage");

            const title = document.createElement("h3");
            title.id = "confirmTitle";
            title.className = "confirm-title";
            title.textContent = o.title;

            const message = document.createElement("p");
            message.id = "confirmMessage";
            message.className = "confirm-message";
            message.textContent = o.message;

            const actions = document.createElement("div");
            actions.className = "confirm-actions";

            const cancelBtn = document.createElement("button");
            cancelBtn.type = "button";
            cancelBtn.className = "confirm-btn confirm-cancel";
            cancelBtn.textContent = o.cancelText;

            const okBtn = document.createElement("button");
            okBtn.type = "button";
            okBtn.className = "confirm-btn confirm-ok" + (o.danger ? " danger" : "");
            okBtn.textContent = o.confirmText;

            if (o.hideCancel) actions.append(okBtn);
            else actions.append(cancelBtn, okBtn);
            dialog.append(title, message, actions);
            overlay.append(dialog);
            document.body.append(overlay);

            function close(result) {
                document.removeEventListener("keydown", onKeyDown, true);
                overlay.remove();
                if (previouslyFocused && previouslyFocused.focus) previouslyFocused.focus();
                resolve(result);
            }

            function onKeyDown(e) {
                if (e.key === "Escape") {
                    e.preventDefault();
                    close(false);
                } else if (e.key === "Tab") {
                    // keep keyboard focus inside the dialog
                    e.preventDefault();
                    (o.hideCancel || document.activeElement === cancelBtn ? okBtn : cancelBtn).focus();
                }
            }

            cancelBtn.addEventListener("click", () => close(false));
            okBtn.addEventListener("click", () => close(true));
            overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(false); });
            document.addEventListener("keydown", onKeyDown, true);

            // The safe choice is focused by default
            (o.hideCancel ? okBtn : cancelBtn).focus();
        });
    }

    // Overridable (used by tests)
    confirmDialog.navigate = function (url) { window.location.assign(url); };
    window.confirmDialog = confirmDialog;

    // One-button variant: await alertDialog({ title, message });
    window.alertDialog = function (options) {
        // Don't stack on top of a dialog that is already open (e.g. repeated microphone errors)
        if (document.querySelector(".confirm-overlay")) return Promise.resolve(false);
        return confirmDialog(Object.assign({ confirmText: "OK" }, options || {}, { hideCancel: true }));
    };

    // --------------------------------------------------------------- nav bar
    let dialogOpen = false;

    document.addEventListener("click", async function (event) {
        const link = event.target.closest && event.target.closest(".navbar a[href]");
        if (!link || event.defaultPrevented) return;

        const url = new URL(link.href, window.location.href);
        const isLogout = url.origin === window.location.origin &&
                         url.pathname.replace(/\/+$/, "") === "/logout";
        const inInterview = window.interviewInProgress === true;

        // Ctrl/Cmd/Shift-click or target=_blank opens another tab: the interview is not left.
        const opensElsewhere = event.ctrlKey || event.metaKey || event.shiftKey || event.altKey ||
                               event.button !== 0 || link.target === "_blank";

        if (!isLogout && (!inInterview || opensElsewhere)) return;

        event.preventDefault();
        if (dialogOpen) return;

        let config;
        if (inInterview) {
            config = {
                title: isLogout ? "Leave the interview and log out?" : "Leave the interview?",
                message: "Your interview is still in progress. If you leave now, your answers so far " +
                         "will not be saved and the interview cannot be resumed.",
                confirmText: isLogout ? "Leave & log out" : "Leave interview",
                cancelText: "Stay in interview",
                danger: true,
            };
        } else {
            config = {
                title: "Log out?",
                message: "You will need to sign in again to continue.",
                confirmText: "Log out",
                cancelText: "Cancel",
                danger: false,
            };
        }

        dialogOpen = true;
        const confirmed = await confirmDialog(config);
        dialogOpen = false;

        if (confirmed) {
            window.interviewInProgress = false;
            const logoutForm = document.getElementById("logoutForm");
            if (isLogout && logoutForm) {
                logoutForm.submit();          // logout is a POST with a CSRF token
            } else {
                confirmDialog.navigate(link.href);
            }
        }
    });
    // ------------------------------------------------- browser back / refresh / close tab
    // Shows the browser's own "Leave site?" warning while an interview is in progress.
    // (Browsers don't allow a custom message here.) It does not fire after the interview has
    // finished, or after the person confirmed leaving through the dialog above, because both
    // set window.interviewInProgress = false before navigating.
    window.addEventListener("beforeunload", function (event) {
        if (window.interviewInProgress === true) {
            event.preventDefault();
            event.returnValue = "";
        }
    });
})();
