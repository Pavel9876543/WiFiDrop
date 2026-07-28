import { checkConnection } from "./connection.js";
import { initializeDropZone } from "./drop-zone.js";
import { FileListView } from "./file-list.js";
import { Notifications } from "./notifications.js";
import { initializePwa } from "./pwa.js";
import { UploadQueue } from "./queue-state.js";
import { initializeTheme } from "./theme.js";
import { ServerBusyError, UploadCancelledError, uploadFile } from "./uploader.js";
import { formatBytes, pluralizeFiles } from "./utils.js";

const elements = {
    browseButton: document.querySelector("#browse-button"),
    clearButton: document.querySelector("#clear-button"),
    connection: document.querySelector("#connection-status"),
    dropZone: document.querySelector("#drop-zone"),
    fileInput: document.querySelector("#file-input"),
    fileList: document.querySelector("#file-list"),
    installButton: document.querySelector("#install-app-button"),
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
const hasFileSizeLimit = Number.isFinite(maxFileSizeMb) && maxFileSizeMb > 0;
const maxFileSizeBytes = hasFileSizeLimit ? maxFileSizeMb * 1024 * 1024 : null;
const notifications = new Notifications(elements.toastRegion);
const queue = new UploadQueue(maxFileSizeBytes, render);
const fileList = new FileListView(elements.fileList, handleFileAction);
let currentRun = null;

initializeTheme(elements.themeToggle);
initializePwa(elements.installButton, (message) => notifications.show(message, "success"));
initializeDropZone(
    elements.dropZone,
    elements.fileInput,
    elements.browseButton,
    addFiles,
);
elements.clearButton.addEventListener("click", () => {
    if (currentRun) {
        cancelAll();
        return;
    }
    queue.clear();
});
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
    const isUploading = currentRun !== null;
    fileList.render(items);
    elements.queue.hidden = items.length === 0;
    elements.queueSummary.textContent = `${pluralizeFiles(items.length)} · ${formatBytes(
        items.reduce((total, item) => total + item.file.size, 0),
    )}`;
    elements.clearButton.textContent = isUploading ? "Отменить всё" : "Очистить";
    elements.clearButton.classList.toggle("text-button--danger", isUploading);
    elements.clearButton.ariaLabel = isUploading
        ? "Отменить загрузку всех файлов"
        : "Очистить список файлов";
    elements.uploadButton.disabled = isUploading || queue.actionableItems.length === 0;
    elements.uploadButton.querySelector("span").textContent = isUploading
        ? "Загрузка…"
        : items.some((item) => item.status === "error" || item.status === "canceled")
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
    if (currentRun) return;
    const items = [...queue.actionableItems];
    if (!items.length) return;

    const run = {
        itemIds: new Set(items.map((item) => item.id)),
        completedIds: new Set(),
        cancelledIds: new Set(),
        succeededIds: new Set(),
        failedIds: new Set(),
        active: null,
        busyError: null,
    };
    currentRun = run;
    render(queue.items);

    for (const item of items) {
        const queuedItem = queue.get(item.id);
        if (!queuedItem || run.cancelledIds.has(item.id)) {
            run.completedIds.add(item.id);
            continue;
        }

        queue.update(item.id, {
            status: "uploading",
            progress: 0,
            loaded: 0,
            speed: 0,
            message: "Загружается",
        });
        const controller = new AbortController();
        run.active = { id: item.id, controller };
        try {
            const result = await uploadFile(
                item.file,
                (progress) => queue.update(item.id, progress),
                controller.signal,
            );
            queue.update(item.id, {
                status: "success",
                progress: 100,
                loaded: item.file.size,
                speed: 0,
                message: "Загружен",
                result,
            });
            run.succeededIds.add(item.id);
        } catch (error) {
            if (error instanceof UploadCancelledError || run.cancelledIds.has(item.id)) {
                run.cancelledIds.add(item.id);
                queue.cancel(item.id);
            } else if (error instanceof ServerBusyError) {
                queue.update(item.id, {
                    status: "error",
                    progress: 0,
                    loaded: 0,
                    speed: 0,
                    message: error.message,
                });
                run.busyError = error;
            } else {
                queue.update(item.id, {
                    status: "error",
                    progress: 0,
                    loaded: 0,
                    speed: 0,
                    message: error.message,
                });
                run.failedIds.add(item.id);
            }
        } finally {
            run.completedIds.add(item.id);
            run.active = null;
        }
        if (run.busyError) break;
    }

    currentRun = null;
    render(queue.items);
    showUploadResult(run, run.itemIds.size);
}

function handleFileAction(id) {
    const item = queue.get(id);
    if (!item) return;

    const isQueuedInCurrentRun = currentRun?.itemIds.has(id)
        && !currentRun.completedIds.has(id);
    if (!isQueuedInCurrentRun) {
        queue.remove(id);
        return;
    }

    currentRun.cancelledIds.add(id);
    queue.cancel(id);
    if (currentRun.active?.id === id) currentRun.active.controller.abort();
}

function cancelAll() {
    if (!currentRun) return;
    const idsToCancel = queue.items
        .filter((item) => (
            currentRun.itemIds.has(item.id) && !currentRun.completedIds.has(item.id)
        ) || item.status === "pending" || item.status === "uploading")
        .map((item) => item.id);
    for (const id of idsToCancel) {
        currentRun.itemIds.add(id);
        currentRun.cancelledIds.add(id);
    }
    queue.cancelMany(idsToCancel);
    currentRun.active?.controller.abort();
}

function showUploadResult(run, total) {
    const succeeded = run.succeededIds.size;
    const failed = run.failedIds.size;
    const cancelled = run.cancelledIds.size;

    if (run.busyError) {
        const retryHint = run.busyError.retryAfterSeconds
            ? ` Повторите не раньше чем через ${run.busyError.retryAfterSeconds} сек.`
            : "";
        const completedHint = succeeded > 0 ? ` До этого загружено: ${succeeded}.` : "";
        notifications.show(`${run.busyError.message}${retryHint}${completedHint}`, "error");
    } else if (cancelled > 0) {
        if (succeeded === 0 && failed === 0) {
            notifications.show(`${pluralizeFiles(cancelled)} отменено.`);
            return;
        }
        const details = [`Загружено: ${succeeded}`, `отменено: ${cancelled}`];
        if (failed > 0) details.push(`с ошибкой: ${failed}`);
        notifications.show(`${details.join(", ")} из ${total}.`, failed > 0 ? "error" : "success");
    } else if (succeeded === total) {
        notifications.show(`${pluralizeFiles(succeeded)} успешно загружено.`, "success");
    } else if (succeeded > 0) {
        notifications.show(`Загружено ${succeeded} из ${total}. Ошибки можно повторить.`, "error");
    } else {
        notifications.show("Не удалось загрузить файлы. Проверьте соединение.", "error");
    }
}
