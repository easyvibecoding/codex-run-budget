"use strict";
(() => {
  const windowPicker = document.getElementById("window-picker");
  const taskPicker = document.getElementById("task-picker");
  const status = document.getElementById("selection-status");
  function update() {
    let visibleRows = 0;
    document.querySelectorAll("[data-window]").forEach(section => {
      section.hidden = section.dataset.window !== windowPicker.value;
      section.querySelectorAll("[data-task]").forEach(row => {
        row.hidden = Boolean(taskPicker.value && row.dataset.task !== taskPicker.value);
        if (!section.hidden && !row.hidden) visibleRows += 1;
      });
    });
    status.textContent = `${windowPicker.selectedOptions[0].textContent} · ${
      taskPicker.selectedOptions[0].textContent} · ${visibleRows} 筆篩選後明細列（含摺疊內容，非請求數）`;
    if (!visibleRows) status.textContent += " · 此範圍沒有可顯示明細；請同時查看截斷與涵蓋範圍。";
  }
  windowPicker.addEventListener("change", update);
  taskPicker.addEventListener("change", update);
  document.getElementById("print-report").addEventListener("click", () => window.print());
  update();
})();
