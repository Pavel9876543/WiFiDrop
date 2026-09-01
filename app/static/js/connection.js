export async function checkConnection(element) {
    const label = element.querySelector(".connection__text");
    try {
        const response = await fetch("/api/health", { cache: "no-store" });
        if (!response.ok) throw new Error("Health check failed");
        element.classList.add("connection--online");
        element.classList.remove("connection--offline");
        label.textContent = "Сервер доступен";
    } catch {
        element.classList.add("connection--offline");
        element.classList.remove("connection--online");
        label.textContent = "Нет соединения";
    }
}

