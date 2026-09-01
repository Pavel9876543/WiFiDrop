export class UploadQueue {
    constructor(maxFileSizeBytes, onChange) {
        this.maxFileSizeBytes = maxFileSizeBytes;
        this.onChange = onChange;
        this.items = [];
        this.sequence = 0;
    }

    add(files) {
        const rejected = [];
        for (const file of files) {
            if (this.maxFileSizeBytes !== null && file.size > this.maxFileSizeBytes) {
                rejected.push(file);
                continue;
            }
            this.sequence += 1;
            this.items.push({
                id: `upload-${Date.now()}-${this.sequence}`,
                file,
                status: "pending",
                progress: 0,
                loaded: 0,
                speed: 0,
                message: "Ожидает загрузки",
                result: null,
            });
        }
        this.emit();
        return rejected;
    }

    update(id, changes) {
        const item = this.items.find((candidate) => candidate.id === id);
        if (!item) return;
        Object.assign(item, changes);
        this.emit();
    }

    get(id) {
        return this.items.find((candidate) => candidate.id === id);
    }

    cancel(id) {
        this.cancelMany([id]);
    }

    cancelMany(ids) {
        const selectedIds = new Set(ids);
        let changed = false;
        for (const item of this.items) {
            if (!selectedIds.has(item.id) || item.status === "success") continue;
            Object.assign(item, {
                status: "canceled",
                progress: 0,
                loaded: 0,
                speed: 0,
                message: "Загрузка отменена",
            });
            changed = true;
        }
        if (changed) this.emit();
    }

    remove(id) {
        const item = this.items.find((candidate) => candidate.id === id);
        if (!item || item.status === "uploading") return;
        this.items = this.items.filter((candidate) => candidate.id !== id);
        this.emit();
    }

    clear() {
        if (this.isUploading) return;
        this.items = [];
        this.emit();
    }

    get actionableItems() {
        return this.items.filter((item) =>
            item.status === "pending" || item.status === "error" || item.status === "canceled"
        );
    }

    get isUploading() {
        return this.items.some((item) => item.status === "uploading");
    }

    emit() {
        this.onChange(this.items);
    }
}
