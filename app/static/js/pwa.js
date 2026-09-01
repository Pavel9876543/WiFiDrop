export function initializePwa(installButton, showMessage) {
    registerServiceWorker();

    if (isStandalone()) {
        installButton.hidden = true;
        return;
    }

    let installPrompt = null;
    installButton.hidden = false;

    window.addEventListener("beforeinstallprompt", (event) => {
        event.preventDefault();
        installPrompt = event;
    });

    window.addEventListener("appinstalled", () => {
        installPrompt = null;
        installButton.hidden = true;
        showMessage("WiFiDrop установлен и доступен в меню приложений.");
    });

    installButton.addEventListener("click", async () => {
        if (installPrompt) {
            await installPrompt.prompt();
            const choice = await installPrompt.userChoice;
            if (choice.outcome === "accepted") installButton.hidden = true;
            installPrompt = null;
            return;
        }

        if (isIos()) {
            showMessage("В Safari нажмите «Поделиться», затем «На экран Домой».");
            return;
        }

        showMessage("Откройте меню браузера и выберите «Установить приложение» или «На главный экран».");
    });
}

function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    window.addEventListener("load", () => {
        navigator.serviceWorker.register("/service-worker.js").catch(() => {
            // File transfer remains available when PWA installation is unsupported.
        });
    });
}

function isStandalone() {
    return window.matchMedia("(display-mode: standalone)").matches
        || window.navigator.standalone === true;
}

function isIos() {
    return /iphone|ipad|ipod/i.test(window.navigator.userAgent);
}
