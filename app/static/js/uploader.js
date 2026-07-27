import { safeJsonParse } from "./utils.js";

export function uploadFile(file, onProgress) {
    return new Promise((resolve, reject) => {
        const request = new XMLHttpRequest();
        const formData = new FormData();
        let previousLoaded = 0;
        let previousTime = performance.now();
        formData.append("file", file, file.name);

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
                resolve(payload.file);
                return;
            }
            reject(new Error(payload?.message || `Сервер вернул ошибку ${request.status}.`));
        });
        request.addEventListener("error", () => {
            reject(new Error("Соединение с компьютером потеряно."));
        });
        request.addEventListener("abort", () => reject(new Error("Загрузка отменена.")));
        request.send(formData);
    });
}

