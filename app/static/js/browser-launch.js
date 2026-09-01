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

function buildAndroidIntentUrl(rawUrl) {
    const url = new URL(rawUrl, window.location.href);
    const scheme = url.protocol.replace(":", "");
    const path = `${url.host}${url.pathname}${url.search}${url.hash}`;
    const fallback = encodeURIComponent(url.href);
    return `intent://${path}#Intent;scheme=${scheme};action=android.intent.action.VIEW;category=android.intent.category.BROWSABLE;S.browser_fallback_url=${fallback};end`;
}

function showAttemptHint(hintElement, text) {
    if (!hintElement) return;
    hintElement.textContent = text;
    hintElement.classList.remove("browser-launch__hint--success");
}

export function initializeBrowserLaunch(openButton, chooserButton, copyButton, hintElement, notify) {
    if (!openButton && !copyButton) return;

    const rawUrl = openButton?.href || copyButton?.dataset.url || "";
    const android = isAndroid();
    const apple = isAppleMobile();

    if (android && chooserButton) {
        chooserButton.hidden = false;
        chooserButton.addEventListener("click", () => {
            if (!rawUrl) return;
            showAttemptHint(
                hintElement,
                "Android: передаём ссылку системе. Если браузер по умолчанию не выбран, система может показать список подходящих приложений.",
            );
            window.location.href = buildAndroidIntentUrl(rawUrl);
        });
    }

    if (openButton) {
        openButton.addEventListener("click", (event) => {
            if (!rawUrl) return;

            if (android) {
                event.preventDefault();
                showAttemptHint(hintElement, "Пытаемся открыть WiFiDrop во внешнем браузере Android…");
                window.location.href = buildAndroidIntentUrl(rawUrl);
                return;
            }

            if (apple) {
                // iOS chooses the configured default browser for normal HTTP(S) links.
                // Captive Web Sheet itself can still decide to keep the navigation inside.
                showAttemptHint(hintElement, "Передаём ссылку браузеру, выбранному в iPhone/iPad по умолчанию…");
            }
        });
    }

    copyButton?.addEventListener("click", async () => {
        const url = copyButton.dataset.url || rawUrl;
        if (!url) return;
        try {
            const copied = await copyText(url);
            if (!copied) throw new Error("copy failed");
            copyButton.textContent = "Адрес скопирован";
            hintElement?.classList.add("browser-launch__hint--success");
            if (hintElement) hintElement.textContent = "Адрес скопирован. Откройте любой браузер и вставьте его в адресную строку.";
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
