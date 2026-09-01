export function initializeDropZone(dropZone, fileInput, browseButton, onFiles) {
    const openPicker = () => {
        // Chrome требует открывать окно выбора непосредственно из пользовательского
        // клика/касания. Сначала используем стандартный showPicker(), а click()
        // оставляем как совместимый fallback для остальных браузеров.
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

    dropZone.addEventListener("click", (event) => {
        if (!browseButton.contains(event.target)) openPicker();
    });
    browseButton.addEventListener("click", (event) => {
        event.stopPropagation();
        openPicker();
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
