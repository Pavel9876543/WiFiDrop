export class Notifications {
    constructor(region) {
        this.region = region;
    }

    show(message, type = "info") {
        const toast = document.createElement("div");
        toast.className = `toast toast--${type}`;
        toast.setAttribute("role", type === "error" ? "alert" : "status");
        const dot = document.createElement("span");
        dot.className = "toast__dot";
        const text = document.createElement("span");
        text.textContent = message;
        toast.append(dot, text);
        this.region.append(toast);
        window.setTimeout(() => toast.remove(), 4500);
    }
}

