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

export function initializeBrowserLaunch(copyButton, hintElement, notify) {
    if (!copyButton) return;

    copyButton.addEventListener("click", async () => {
        const url = copyButton.dataset.url || "";
        if (!url) return;
        try {
            const copied = await copyText(url);
            if (!copied) throw new Error("copy failed");
            copyButton.textContent = "Адрес скопирован";
            hintElement?.classList.add("browser-launch__hint--success");
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
