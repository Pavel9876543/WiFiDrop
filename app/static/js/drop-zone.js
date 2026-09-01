export function initializeDropZone(dropZone, fileInput, browseButton, onFiles) {
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

    // Кнопка выбора — нативный <label for="file-input">. Не перехватываем
    // её click: браузер сам открывает системный выбор файлов. Это надёжнее
    // программного click()/showPicker() в Chrome на Android.
    browseButton.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openPicker();
        }
    });

    dropZone.addEventListener("click", (event) => {
        if (!browseButton.contains(event.target)) openPicker();
    });
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
