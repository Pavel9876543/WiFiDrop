export function initializeDropZone(dropZone, fileInput, browseButton, onFiles) {
    const openPicker = () => {
        // The visible control is a native <label for=file-input>. Keep this
        // fallback for the drop zone and keyboard activation only.
        fileInput.click();
    };

    dropZone.addEventListener("click", (event) => {
        if (event.target.closest("#browse-button") || event.target === fileInput) return;
        openPicker();
    });
    browseButton.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openPicker();
        }
    });
    fileInput.addEventListener("change", () => {
        const files = [...(fileInput.files || [])];
        if (files.length) onFiles(files);
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
