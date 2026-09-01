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

    let reloadingForUpdate = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
        if (reloadingForUpdate) return;
        if (window.sessionStorage.getItem("wifidrop-sw-reloaded") === "1") return;
        reloadingForUpdate = true;
        window.sessionStorage.setItem("wifidrop-sw-reloaded", "1");
        window.location.reload();
    });

    window.addEventListener("load", async () => {
        try {
            const registration = await navigator.serviceWorker.register("/service-worker.js", {
                updateViaCache: "none",
            });
            await registration.update();
        } catch {
            // File transfer remains available when PWA installation is unsupported.
        }
    });
}

function isStandalone() {
    return window.matchMedia("(display-mode: standalone)").matches
        || window.navigator.standalone === true;
}

function isIos() {
    return /iphone|ipad|ipod/i.test(window.navigator.userAgent);
}
