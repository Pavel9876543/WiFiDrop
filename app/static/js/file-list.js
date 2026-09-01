import { formatBytes, formatSpeed } from "./utils.js";

const FILE_ICON = `
    <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M6 3h8l4 4v14H6V3Z"/><path d="M14 3v5h4"/>
    </svg>`;
const REMOVE_ICON = `
    <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="m7 7 10 10M17 7 7 17"/>
    </svg>`;

export class FileListView {
    constructor(container, onAction) {
        this.container = container;
        this.onAction = onAction;
        this.container.addEventListener("click", (event) => {
            const button = event.target.closest("[data-file-action-id]");
            if (button) this.onAction(button.dataset.fileActionId);
        });
    }

    render(items) {
        const fragment = document.createDocumentFragment();
        for (const item of items) fragment.append(this.createItem(item));
        this.container.replaceChildren(fragment);
    }

    createItem(item) {
        const row = document.createElement("article");
        row.className = "file-item";
        row.dataset.fileId = item.id;

        const icon = document.createElement("span");
        icon.className = "file-item__icon";
        icon.innerHTML = FILE_ICON;

        const content = document.createElement("div");
        content.className = "file-item__content";
        const topLine = document.createElement("div");
        topLine.className = "file-item__topline";
        const name = document.createElement("span");
        name.className = "file-item__name";
        name.title = item.file.name;
        name.textContent = item.file.name;
        const percent = document.createElement("span");
        percent.className = "file-item__percent";
        percent.textContent = this.progressText(item);
        topLine.append(name, percent);

        const details = document.createElement("div");
        details.className = "file-item__details";
        const size = document.createElement("span");
        size.textContent = formatBytes(item.file.size);
        const status = document.createElement("span");
        status.className = `file-item__status file-item__status--${item.status}`;
        status.textContent = this.statusText(item);
        details.append(size, status);

        const progress = document.createElement("div");
        progress.className = "file-item__progress";
        const progressFill = document.createElement("span");
        progressFill.style.width = `${item.progress}%`;
        progress.append(progressFill);
        content.append(topLine, details, progress);

        const remove = document.createElement("button");
        remove.className = "file-item__remove";
        remove.type = "button";
        remove.dataset.fileActionId = item.id;
        const actionLabel = item.status === "uploading"
            ? `Отменить загрузку ${item.file.name}`
            : `Убрать ${item.file.name}`;
        remove.ariaLabel = actionLabel;
        remove.title = actionLabel;
        remove.innerHTML = REMOVE_ICON;
        row.append(icon, content, remove);
        return row;
    }

    progressText(item) {
        if (item.status === "success") return "Готово";
        if (item.status === "canceled") return "Отменено";
        return `${Math.round(item.progress)}%`;
    }

    statusText(item) {
        if (item.status === "uploading") return formatSpeed(item.speed);
        if (item.status === "success") return item.result?.category || "Загружен";
        if (item.status === "error") return item.message || "Ошибка";
        if (item.status === "canceled") return "Загрузка отменена";
        return "Ожидает";
    }
}
