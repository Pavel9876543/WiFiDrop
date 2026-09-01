export function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) return "0 Б";
    const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
    const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
    const value = bytes / 1024 ** unitIndex;
    const digits = unitIndex === 0 || value >= 100 ? 0 : value >= 10 ? 1 : 2;
    return `${value.toFixed(digits)} ${units[unitIndex]}`;
}

export function formatSpeed(bytesPerSecond) {
    return bytesPerSecond > 0 ? `${formatBytes(bytesPerSecond)}/с` : "—";
}

export function pluralizeFiles(count) {
    const remainder100 = count % 100;
    const remainder10 = count % 10;
    if (remainder100 >= 11 && remainder100 <= 19) return `${count} файлов`;
    if (remainder10 === 1) return `${count} файл`;
    if (remainder10 >= 2 && remainder10 <= 4) return `${count} файла`;
    return `${count} файлов`;
}

export function safeJsonParse(value) {
    try {
        return JSON.parse(value);
    } catch {
        return null;
    }
}

