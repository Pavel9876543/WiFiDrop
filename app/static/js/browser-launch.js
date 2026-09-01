function legacyCopy(text) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    const copied = document.execCommand("copy");
    textarea.remove();
    return copied;
}

async function copyText(text) {
    if (navigator.clipboard?.writeText && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return true;
    }
    return legacyCopy(text);
}

function isAndroid() {
    return /Android/i.test(navigator.userAgent || "");
}

function isAppleMobile() {
    return /iPhone|iPad|iPod/i.test(navigator.userAgent || "")
        || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}

function buildAndroidPackageIntent(rawUrl, packageName) {
    const url = new URL(rawUrl, window.location.href);
    const scheme = url.protocol.replace(":", "");
    const path = `${url.host}${url.pathname}${url.search}${url.hash}`;
    return `intent://${path}#Intent;scheme=${scheme};action=android.intent.action.VIEW;category=android.intent.category.BROWSABLE;package=${packageName};end`;
}

function buildIosUrl(rawUrl, browser) {
    const encoded = encodeURIComponent(rawUrl);
    if (browser === "chrome") {
        return rawUrl.replace(/^http:/, "googlechrome:").replace(/^https:/, "googlechromes:");
    }
    if (browser === "firefox") return `firefox://open-url?url=${encoded}`;
    return "";
}

function showHint(hintElement, text, success = false) {
    if (!hintElement) return;
    hintElement.textContent = text;
    hintElement.classList.toggle("browser-launch__hint--success", success);
}

export function initializeBrowserLaunch(openButton, chooserButton, copyButton, hintElement, notify) {
    const rawUrl = openButton?.dataset.url || chooserButton?.dataset.url || copyButton?.dataset.url || "";
    const chooser = document.querySelector("#browser-picker");
    const closeButton = document.querySelector("#browser-picker-close");
    const browserButtons = [...document.querySelectorAll("[data-browser-target]")];
    const android = isAndroid();
    const apple = isAppleMobile();

    const openChooser = (event) => {
        event?.preventDefault();
        if (!chooser) return;
        chooser.hidden = false;
        document.body.classList.add("browser-picker-open");
        browserButtons.forEach((button) => {
            const platforms = (button.dataset.platforms || "").split(",");
            button.hidden = platforms.length > 0 && !platforms.includes(android ? "android" : apple ? "ios" : "other");
        });
        showHint(hintElement, "Сначала выберите браузер. WiFiDrop не открывает браузер по умолчанию автоматически.");
    };

    openButton?.addEventListener("click", openChooser);
    chooserButton?.addEventListener("click", openChooser);
    closeButton?.addEventListener("click", () => {
        chooser.hidden = true;
        document.body.classList.remove("browser-picker-open");
    });

    browserButtons.forEach((button) => {
        button.addEventListener("click", () => {
            if (!rawUrl) return;
            const browser = button.dataset.browserTarget;
            if (android) {
                const packages = {
                    chrome: "com.android.chrome",
                    firefox: "org.mozilla.firefox",
                    yandex: "com.yandex.browser",
                    edge: "com.microsoft.emmx",
                    brave: "com.brave.browser",
                    opera: "com.opera.browser",
                };
                const packageName = packages[browser];
                if (!packageName) return;
                showHint(hintElement, `Открываем ${button.textContent.trim()}…`);
                window.location.href = buildAndroidPackageIntent(rawUrl, packageName);
                return;
            }
            if (apple) {
                const target = buildIosUrl(rawUrl, browser);
                if (!target) {
                    showHint(hintElement, "Для этого браузера iPhone не предоставляет надёжной публичной схему запуска. Скопируйте адрес.");
                    return;
                }
                showHint(hintElement, `Открываем ${button.textContent.trim()}…`);
                window.location.href = target;
                return;
            }
            showHint(hintElement, "На этой платформе принудительный выбор браузера недоступен. Скопируйте адрес.");
        });
    });

    copyButton?.addEventListener("click", async () => {
        if (!rawUrl) return;
        try {
            const copied = await copyText(rawUrl);
            if (!copied) throw new Error("copy failed");
            copyButton.textContent = "Адрес скопирован";
            showHint(hintElement, "Адрес скопирован. Откройте нужный браузер вручную и вставьте его.", true);
            notify?.("Адрес WiFiDrop скопирован.", "success");
            window.setTimeout(() => {
                copyButton.textContent = "Скопировать адрес";
                hintElement?.classList.remove("browser-launch__hint--success");
            }, 2500);
        } catch {
            notify?.("Не удалось скопировать адрес автоматически.", "error");
        }
    });
}
