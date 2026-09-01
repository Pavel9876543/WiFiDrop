const STORAGE_KEY = "wifidrop-theme";

export function initializeTheme(toggleButton) {
    let storedTheme = null;
    try {
        storedTheme = localStorage.getItem(STORAGE_KEY);
    } catch {
        storedTheme = null;
    }
    const preferredTheme = window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
    applyTheme(storedTheme || preferredTheme);

    toggleButton.addEventListener("click", () => {
        const nextTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
        applyTheme(nextTheme);
        try {
            localStorage.setItem(STORAGE_KEY, nextTheme);
        } catch {
            // The selected theme still applies when storage is unavailable.
        }
    });
}

function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]').content = theme === "dark" ? "#111119" : "#f7f8fc";
}

