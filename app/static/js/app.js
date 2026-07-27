import { checkConnection } from "./connection.js";
import { initializeDropZone } from "./drop-zone.js";
import { FileListView } from "./file-list.js";
import { Notifications } from "./notifications.js";
import { UploadQueue } from "./queue-state.js";
import { initializeTheme } from "./theme.js";
import { uploadFile } from "./uploader.js";
import { formatBytes, pluralizeFiles } from "./utils.js";

const elements = {
    browseButton: document.querySelector("#browse-button"),
    clearButton: document.querySelector("#clear-button"),
    connection: document.querySelector("#connection-status"),
    dropZone: document.querySelector("#drop-zone"),
    fileInput: document.querySelector("#file-input"),
    fileList: document.querySelector("#file-list"),
    queue: document.querySelector("#queue"),
    queueSummary: document.querySelector("#queue-summary"),
    themeToggle: document.querySelector("#theme-toggle"),
    toastRegion: document.querySelector("#toast-region"),
    totalPercent: document.querySelector("#total-percent"),
    totalProgress: document.querySelector("#total-progress"),
    totalProgressBar: document.querySelector("#total-progress-bar"),
    uploadButton: document.querySelector("#upload-button"),
};

const maxFileSizeMb = Number(document.body.dataset.maxFileSizeMb);
const notifications = new Notifications(elements.toastRegion);
const queue = new UploadQueue(maxFileSizeMb * 1024 * 1024, render);
const fileList = new FileListView(elements.fileList, (id) => queue.remove(id));

initializeTheme(elements.themeToggle);
initializeDropZone(
    elements.dropZone,
    elements.fileInput,
    elements.browseButton,
    addFiles,
);
elements.clearButton.addEventListener("click", () => queue.clear());
elements.uploadButton.addEventListener("click", startUpload);
checkConnection(elements.connection);
window.setInterval(() => checkConnection(elements.connection), 30000);

function addFiles(files) {
    if (!files.length) return;
    const rejected = queue.add(files);
    if (rejected.length) {
        notifications.show(
            `${pluralizeFiles(rejected.length)} больше лимита ${maxFileSizeMb} МБ.`,
            "error",
        );
    }
}

function render(items) {
    fileList.render(items);
    elements.queue.hidden = items.length === 0;
    elements.queueSummary.textContent = `${pluralizeFiles(items.length)} · ${formatBytes(
        items.reduce((total, item) => total + item.file.size, 0),
    )}`;
    elements.clearButton.disabled = queue.isUploading;
    elements.uploadButton.disabled = queue.isUploading || queue.actionableItems.length === 0;
    elements.uploadButton.querySelector("span").textContent = queue.isUploading
        ? "Загрузка…"
        : items.some((item) => item.status === "error")
            ? "Повторить"
            : "Загрузить";
    updateTotalProgress(items);
}

function updateTotalProgress(items) {
    const hasStarted = items.some((item) => item.status !== "pending");
    elements.totalProgress.hidden = !hasStarted;
    const totalBytes = items.reduce((total, item) => total + item.file.size, 0);
    const completedBytes = items.reduce((total, item) => {
        if (item.status === "success" || item.status === "error") return total + item.file.size;
        return total + item.file.size * (item.progress / 100);
    }, 0);
    const percentage = totalBytes > 0 ? Math.min(100, (completedBytes / totalBytes) * 100) : 0;
    elements.totalPercent.textContent = `${Math.round(percentage)}%`;
    elements.totalProgressBar.style.width = `${percentage}%`;
}

async function startUpload() {
    if (queue.isUploading) return;
    const items = [...queue.actionableItems];
    let succeeded = 0;

    for (const item of items) {
        queue.update(item.id, {
            status: "uploading",
            progress: 0,
            loaded: 0,
            speed: 0,
            message: "Загружается",
        });
        try {
            const result = await uploadFile(item.file, (progress) => queue.update(item.id, progress));
            queue.update(item.id, {
                status: "success",
                progress: 100,
                loaded: item.file.size,
                speed: 0,
                message: "Загружен",
                result,
            });
            succeeded += 1;
        } catch (error) {
            queue.update(item.id, {
                status: "error",
                progress: 0,
                loaded: 0,
                speed: 0,
                message: error.message,
            });
        }
    }

    if (succeeded === items.length) {
        notifications.show(`${pluralizeFiles(succeeded)} успешно загружено.`, "success");
    } else if (succeeded > 0) {
        notifications.show(`Загружено ${succeeded} из ${items.length}. Ошибки можно повторить.`, "error");
    } else {
        notifications.show("Не удалось загрузить файлы. Проверьте соединение.", "error");
    }
}

