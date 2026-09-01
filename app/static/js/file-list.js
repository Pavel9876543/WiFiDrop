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
        this.rows = new Map();
        this.container.addEventListener("click", (event) => {
            const button = event.target.closest("[data-file-action-id]");
            if (button) this.onAction(button.dataset.fileActionId);
        });
    }

    render(items) {
        const activeIds = new Set(items.map((item) => item.id));
        for (const [id, row] of this.rows) {
            if (!activeIds.has(id)) {
                row.remove();
                this.rows.delete(id);
            }
        }

        for (const item of items) {
            let row = this.rows.get(item.id);
            if (!row) {
                row = this.createItem(item);
                this.rows.set(item.id, row);
                this.container.append(row);
            }
            this.updateItem(row, item);
        }
    }

    createItem(item) {
        const row = document.createElement("article");
        row.className = "file-item";
        row.dataset.fileId = item.id;
        row.innerHTML = `
            <span class="file-item__icon">${FILE_ICON}</span>
            <div class="file-item__content">
                <div class="file-item__topline">
                    <span class="file-item__name"></span>
                    <span class="file-item__percent"></span>
                </div>
                <div class="file-item__details">
                    <span class="file-item__size"></span>
                    <span class="file-item__status"></span>
                </div>
                <div class="file-item__progress"><span></span></div>
            </div>
            <button class="file-item__remove" type="button" data-file-action-id="${item.id}">${REMOVE_ICON}</button>
        `;
        return row;
    }

    updateItem(row, item) {
        const name = row.querySelector(".file-item__name");
        name.title = item.file.name;
        name.textContent = item.file.name;
        row.querySelector(".file-item__percent").textContent = this.progressText(item);
        row.querySelector(".file-item__size").textContent = formatBytes(item.file.size);

        const status = row.querySelector(".file-item__status");
        status.className = `file-item__status file-item__status--${item.status}`;
        status.textContent = this.statusText(item);

        row.querySelector(".file-item__progress span").style.width = `${item.progress}%`;
        const remove = row.querySelector(".file-item__remove");
        const actionLabel = item.status === "uploading"
            ? `Отменить загрузку ${item.file.name}`
            : `Убрать ${item.file.name}`;
        remove.ariaLabel = actionLabel;
        remove.title = actionLabel;
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
