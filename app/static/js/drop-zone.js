export function initializeDropZone(dropZone, fileInput, onFiles) {
    const openPicker = () => {
        if (typeof fileInput.showPicker === "function") {
            try {
                fileInput.showPicker();
                return;
            } catch (error) {
                if (error?.name !== "NotAllowedError" && error?.name !== "InvalidStateError") {
                    throw error;
                }
            }
        }
        fileInput.click();
    };

    // Вся зона загрузки — нативный <label for="file-input">, поэтому обычный
    // клик/тап открывает системный выбор файлов без программного click().
    // Для управления с клавиатуры оставляем явный вызов picker.
    dropZone.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openPicker();
        }
    });
    fileInput.addEventListener("change", () => {
        onFiles([...fileInput.files]);
        fileInput.value = "";
    });

    for (const eventName of ["dragenter", "dragover"]) {
        dropZone.addEventListener(eventName, (event) => {
            event.preventDefault();
            dropZone.classList.add("drop-zone--active");
        });
    }
    for (const eventName of ["dragleave", "drop"]) {
        dropZone.addEventListener(eventName, (event) => {
            event.preventDefault();
            dropZone.classList.remove("drop-zone--active");
        });
    }
    dropZone.addEventListener("drop", (event) => onFiles([...event.dataTransfer.files]));

    document.addEventListener("dragover", (event) => event.preventDefault());
    document.addEventListener("drop", (event) => event.preventDefault());
}
