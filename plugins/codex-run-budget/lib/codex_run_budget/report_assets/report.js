"use strict";
(() => {
  const root = document.getElementById("report-root");
  const windowPicker = document.getElementById("window-picker");
  const taskPicker = document.getElementById("task-picker");
  const status = document.getElementById("selection-status");
  const statusTemplate = root?.dataset.statusTemplate ||
    "{window} · {task} · {rows} filtered detail rows (including collapsed content; not request count)";
  const statusEmpty = root?.dataset.statusEmpty ||
    " · No detail rows are available in this scope; also check truncation and coverage.";
  function format(template, values) {
    return template.replace(/\{([a-z]+)\}/gi, (_, key) =>
      Object.prototype.hasOwnProperty.call(values, key) ? values[key] : "");
  }
  function update() {
    let visibleRows = 0;
    document.querySelectorAll("[data-window]").forEach(section => {
      section.hidden = section.dataset.window !== windowPicker.value;
      section.querySelectorAll("[data-task]").forEach(row => {
        row.hidden = Boolean(taskPicker.value && row.dataset.task !== taskPicker.value);
        if (!section.hidden && !row.hidden) visibleRows += 1;
      });
    });
    status.textContent = format(statusTemplate, {
      window: windowPicker.selectedOptions[0].textContent,
      task: taskPicker.selectedOptions[0].textContent,
      rows: visibleRows,
    });
    if (!visibleRows) status.textContent += statusEmpty;
  }
  windowPicker.addEventListener("change", update);
  taskPicker.addEventListener("change", update);
  document.getElementById("print-report").addEventListener("click", () => window.print());
  update();
})();
