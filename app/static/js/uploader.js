import { safeJsonParse } from "./utils.js";

export class UploadCancelledError extends Error {
    constructor() {
        super("Загрузка отменена.");
        this.name = "UploadCancelledError";
    }
}

export class ServerBusyError extends Error {
    constructor(message, retryAfterSeconds = null) {
        super(message);
        this.name = "ServerBusyError";
        this.retryAfterSeconds = retryAfterSeconds;
    }
}

export function uploadFile(file, onProgress, signal) {
    return new Promise((resolve, reject) => {
        if (signal?.aborted) {
            reject(new UploadCancelledError());
            return;
        }

        const request = new XMLHttpRequest();
        const formData = new FormData();
        let previousLoaded = 0;
        let previousTime = performance.now();
        let settled = false;
        formData.append("file", file, file.name);

        const finish = (callback) => {
            if (settled) return;
            settled = true;
            signal?.removeEventListener("abort", abortRequest);
            callback();
        };
        const abortRequest = () => request.abort();

        request.open("POST", "/api/uploads");
        request.timeout = 0;
        request.upload.addEventListener("progress", (event) => {
            if (!event.lengthComputable) return;
            const currentTime = performance.now();
            const elapsedSeconds = (currentTime - previousTime) / 1000;
            const speed = elapsedSeconds > 0 ? (event.loaded - previousLoaded) / elapsedSeconds : 0;
            previousLoaded = event.loaded;
            previousTime = currentTime;
            onProgress({
                loaded: event.loaded,
                progress: (event.loaded / event.total) * 100,
                speed,
            });
        });
        request.addEventListener("load", () => {
            const payload = safeJsonParse(request.responseText);
            if (request.status >= 200 && request.status < 300 && payload?.success) {
                finish(() => resolve(payload.file));
                return;
            }
            if (request.status === 503 && payload?.error === "server_busy") {
                const retryAfter = Number(request.getResponseHeader("Retry-After"));
                const retryAfterSeconds = Number.isFinite(retryAfter) && retryAfter > 0
                    ? Math.ceil(retryAfter)
                    : null;
                finish(() => reject(new ServerBusyError(
                    payload.message || "Сервер занят. Повторите отправку позже.",
                    retryAfterSeconds,
                )));
                return;
            }
            finish(() => {
                reject(new Error(payload?.message || `Сервер вернул ошибку ${request.status}.`));
            });
        });
        request.addEventListener("error", () => {
            finish(() => reject(new Error("Соединение с компьютером потеряно.")));
        });
        request.addEventListener("abort", () => {
            finish(() => reject(new UploadCancelledError()));
        });
        signal?.addEventListener("abort", abortRequest, { once: true });
        request.send(formData);
    });
}
