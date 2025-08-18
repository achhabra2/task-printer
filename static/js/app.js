/**
 * Task Printer — Frontend module
 * Path: static/js/app.js
 *
 * Purpose:
 * - Centralize dynamic form logic for the index page
 * - Use <template> cloning instead of string concatenation
 * - Build a JSON payload of sections/tasks and attach as hidden input payload_json before submit
 *
 * Notes:
 * - This module gracefully coexists with legacy inline event handlers by exposing functions on window.TaskPrinter
 * - It relies on window.__ICONS (optional) to render icon picker radios; when absent, it shows a small message
 * - Image flair file cannot be embedded in JSON; include the file input field name in flair_value and keep the file in multipart form
 */

(function () {
  "use strict";

  // Globals and configuration
  const ICONS = Array.isArray(window.__ICONS) ? window.__ICONS : null;

  // Lazy-created templates
  let sectionTemplate = null;
  let taskTemplate = null;

  function ensureTemplates() {
    if (!sectionTemplate) {
      sectionTemplate = document.createElement("template");
      sectionTemplate.innerHTML = `
        <div class="subtitle-section border-b border-gray-200 dark:border-slate-700 pb-5 mb-7" data-section="">
          <label class="block mb-2 font-semibold text-gray-600 dark:text-gray-200">Subtitle (e.g., Cleaning kitchen):</label>
          <input type="text" class="w-full p-2.5 border-2 rounded-md text-sm bg-white text-gray-900 border-gray-300 focus:outline-none focus:border-brand dark:bg-slate-800 dark:text-gray-100 dark:border-slate-600 mb-2">
          <div class="taskContainer"></div>
          <button type="button" class="add-task-btn w-full py-2.5 rounded-md bg-green-600 text-white hover:bg-green-700">➕ Add Task</button>
        </div>
      `.trim();
    }

    if (!taskTemplate) {
      taskTemplate = document.createElement("template");
      taskTemplate.innerHTML = `
        <div class="tp-task-block">
          <div class="task-input mb-4">
            <div class="flex items-center gap-2 mb-2">
              <label class="font-semibold text-gray-600 dark:text-gray-200">Task 1:</label>
              <button type="button" class="remove-task inline-flex items-center justify-center w-8 h-8 rounded-md bg-red-600 text-white hover:bg-red-700 flex-shrink-0 text-sm">✕</button>
            </div>
            <input type="text" class="w-full p-2.5 border-2 rounded-md text-sm bg-white text-gray-900 border-gray-300 focus:outline-none focus:border-brand dark:bg-slate-800 dark:text-gray-100 dark:border-slate-600 mb-3">
          </div>
          <div class="flair-row mb-4" data-for="">
            <label class="block mb-2 font-semibold text-gray-600 dark:text-gray-200">Flair:</label>
            <div class="flex items-center gap-2 mb-3">
              <select class="tp-flair-type p-1.5 text-xs border rounded dark:bg-slate-800 dark:text-gray-100 dark:border-slate-600">
                <option value="none" selected>None</option>
                <option value="icon">Icon</option>
                <option value="image">Image</option>
                <option value="qr">QR</option>
              </select>
              <input type="file" class="flair-image hidden" accept="image/*">
              <img class="flair-preview hidden w-10 h-10 object-contain border border-dashed border-gray-300 rounded" alt="preview">
              <input type="text" class="flair-qr hidden p-1.5 text-xs border rounded dark:bg-slate-800 dark:text-gray-100 dark:border-slate-600" placeholder="QR data">
            </div>
            <div class="flair-icon-picker hidden">
              <div class="icon-grid grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-2 sm:gap-3 mt-2 p-3 sm:p-2 bg-gray-50 dark:bg-slate-700 rounded-lg border max-h-64 overflow-y-auto"></div>
            </div>
          </div>
        </div>
      `.trim();
    }
  }

  // Utilities
  function show(el) {
    if (el) el.classList.remove("hidden");
  }
  function hide(el) {
    if (el) el.classList.add("hidden");
  }
  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) {
      return decodeURIComponent(parts.pop().split(";").shift());
    }
    return "";
  }
  function csrfHeader(headers = {}) {
    const token = getCookie("csrf_token");
    if (token) headers["X-CSRFToken"] = token;
    return headers;
  }

  // State
  let sectionCount = 0;
  const taskCounts = {}; // sectionId -> current task count

  function initCounts() {
    const container = document.getElementById("subtitleSections");
    if (!container) return;
    const sections = container.querySelectorAll(".subtitle-section");
    sectionCount = sections.length || 0;
    Array.from(sections).forEach((sec) => {
      const sid = sec.getAttribute("data-section") || "";
      const tasks = sec.querySelectorAll(".taskContainer .task-input");
      taskCounts[sid] = tasks.length || 0;
    });
  }

  // Icon picker content
  function buildIconPicker(sectionId, taskNumber) {
    const grid = document.createElement("div");
    grid.className =
      "grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-2 sm:gap-3 mt-2 p-3 sm:p-2 bg-gray-50 dark:bg-slate-700 rounded-lg border max-h-64 overflow-y-auto";

    if (!ICONS || ICONS.length === 0) {
      const msg = document.createElement("em");
      msg.className = "text-slate-500";
      msg.textContent = "No icons available";
      grid.appendChild(msg);
      return grid;
    }

    ICONS.forEach((ic) => {
      const label = document.createElement("label");
      label.className =
        "flex flex-col items-center gap-1.5 sm:gap-1 p-2 sm:p-1.5 cursor-pointer hover:bg-white dark:hover:bg-slate-600 rounded-md transition-all duration-200 min-h-[5.5rem] sm:min-h-[4.5rem] border-2 border-transparent has-[:checked]:border-blue-500 has-[:checked]:bg-blue-50 dark:has-[:checked]:bg-blue-900/30 has-[:checked]:shadow-md hover:shadow-sm";

      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = `flair_icon_${sectionId}_${taskNumber}`;
      radio.value = ic.name;
      radio.className = "peer sr-only";

      const wrap = document.createElement("div");
      wrap.className =
        "w-10 h-10 sm:w-8 sm:h-8 lg:w-9 lg:h-9 flex items-center justify-center bg-white rounded-md shadow-sm border border-gray-200 dark:border-slate-600 peer-checked:border-blue-500 peer-checked:shadow-md";

      const img = document.createElement("img");
      img.src = ic.url;
      img.alt = ic.name;
      img.className = "w-8 h-8 sm:w-6 sm:h-6 lg:w-7 lg:h-7 object-contain";
      img.onerror = function () {
        this.style.display = "none";
      };

      wrap.appendChild(img);

      const caption = document.createElement("span");
      caption.className =
        "text-xs font-medium text-center leading-tight text-gray-700 dark:text-gray-300 peer-checked:text-blue-600 dark:peer-checked:text-blue-400 capitalize";
      try {
        caption.textContent = String(ic.name || "").replace(/_/g, " ");
      } catch {
        caption.textContent = "icon";
      }

      label.appendChild(radio);
      label.appendChild(wrap);
      label.appendChild(caption);
      grid.appendChild(label);
    });

    return grid;
  }

  // Build a new task block (task row + flair row) for a given section/task numbers
  function createTaskBlock(sectionId, taskNumber) {
    ensureTemplates();
    const node = taskTemplate.content.cloneNode(true);

    const taskInputDiv = node.querySelector(".task-input");
    const label = taskInputDiv.querySelector("label");
    label.textContent = `Task ${taskNumber}:`;

    const textInput = taskInputDiv.querySelector('input[type="text"]');
    textInput.name = `task_${sectionId}_${taskNumber}`;
    textInput.placeholder = `Enter task ${taskNumber}...`;

    const flairRow = node.querySelector(".flair-row");
    flairRow.setAttribute("data-for", `${sectionId}_${taskNumber}`);

    const flairType = flairRow.querySelector(".tp-flair-type");
    flairType.name = `flair_type_${sectionId}_${taskNumber}`;

    const imgInput = flairRow.querySelector(".flair-image");
    imgInput.name = `flair_image_${sectionId}_${taskNumber}`;

    const qrInput = flairRow.querySelector(".flair-qr");
    qrInput.name = `flair_qr_${sectionId}_${taskNumber}`;

    const iconPickerWrap = flairRow.querySelector(
      ".flair-icon-picker .icon-grid",
    );
    if (iconPickerWrap) {
      const grid = buildIconPicker(sectionId, taskNumber);
      iconPickerWrap.replaceWith(grid);
      grid.classList.add("icon-grid");
    }

    return node;
  }

  // Create and append a new section with one empty task
  function addSubtitleSection() {
    ensureTemplates();

    const container = document.getElementById("subtitleSections");
    if (!container) return;

    sectionCount += 1;
    const sid = String(sectionCount);
    taskCounts[sid] = 0;

    const frag = sectionTemplate.content.cloneNode(true);
    const sectionDiv = frag.querySelector(".subtitle-section");
    sectionDiv.setAttribute("data-section", sid);

    const subtitleInput = sectionDiv.querySelector('input[type="text"]');
    subtitleInput.id = `subtitle_${sid}`;
    subtitleInput.name = `subtitle_${sid}`;

    const taskContainer = sectionDiv.querySelector(".taskContainer");

    // First task
    const tnum = 1;
    taskCounts[sid] = tnum;
    taskContainer.appendChild(createTaskBlock(sid, tnum));

    // Wire add-task button
    const addBtn = sectionDiv.querySelector(".add-task-btn");
    if (addBtn) {
      addBtn.addEventListener("click", function () {
        addTask(addBtn);
      });
    }

    container.appendChild(frag);

    // Update remove buttons for the new section
    updateRemoveButtons(taskContainer);
  }

  // Add a task to the specific section (button inside the section)
  function addTask(btn) {
    const sectionDiv = btn.closest(".subtitle-section");
    if (!sectionDiv) return;
    const sid = sectionDiv.getAttribute("data-section");
    const taskContainer = sectionDiv.querySelector(".taskContainer");
    if (!sid || !taskContainer) return;

    const current = Number(taskCounts[sid] || 0) + 1;
    taskCounts[sid] = current;

    const block = createTaskBlock(sid, current);
    taskContainer.appendChild(block);
    updateRemoveButtons(taskContainer);
  }

  // Remove a task and its flair row; re-number remaining tasks in the section
  function removeTask(btn) {
    const taskDiv = btn.closest(".task-input");
    if (!taskDiv) return;
    const taskContainer = taskDiv.parentElement;
    const sectionDiv = taskContainer.closest(".subtitle-section");
    const sid = sectionDiv.getAttribute("data-section");

    // Find index to remove the matching flair row
    const index = Array.from(
      taskContainer.querySelectorAll(".task-input"),
    ).indexOf(taskDiv);
    const flairRows = taskContainer.querySelectorAll(".flair-row");
    if (flairRows[index]) flairRows[index].remove();

    taskDiv.remove();

    // If no tasks remain, remove the entire section
    const remainingTasks = taskContainer.querySelectorAll(".task-input");
    if (remainingTasks.length === 0) {
      const allSections = document.getElementById("subtitleSections");
      allSections.removeChild(sectionDiv);
      // If no sections remain, create a fresh one
      if (allSections.children.length === 0) {
        addSubtitleSection();
      }
      return;
    }

    // Renumber remaining tasks and inputs
    const inputs = taskContainer.querySelectorAll(".task-input");
    inputs.forEach((row, idx) => {
      const tnum = idx + 1;
      const label = row.querySelector("label");
      if (label) label.textContent = `Task ${tnum}:`;

      const textInput = row.querySelector('input[type="text"]');
      if (textInput && textInput.name) {
        textInput.name = textInput.name.replace(
          /^(task_\d+_)\d+$/,
          `$1${tnum}`,
        );
        textInput.placeholder = `Enter task ${tnum}...`;
      }
    });

    const allFlairs = taskContainer.querySelectorAll(".flair-row");
    allFlairs.forEach((fr, idx) => {
      const newNum = idx + 1;
      fr.setAttribute("data-for", `${sid}_${newNum}`);
      fr.querySelectorAll("select, input").forEach((el) => {
        if (!el.name) return;
        el.name = el.name
          .replace(/^(flair_type_\d+_)\d+$/, `$1${newNum}`)
          .replace(/^(flair_image_\d+_)\d+$/, `$1${newNum}`)
          .replace(/^(flair_qr_\d+_)\d+$/, `$1${newNum}`)
          .replace(/^(flair_icon_\d+_)\d+$/, `$1${newNum}`);
      });
    });

    taskCounts[sid] = inputs.length;
    updateRemoveButtons(taskContainer);
  }

  // Show/hide controls based on selected flair type
  function onFlairTypeChange(sel) {
    const row = sel.closest(".flair-row");
    const iconPicker = row.querySelector(".flair-icon-picker");
    const qrInput = row.querySelector(".flair-qr");
    const imgInput = row.querySelector(".flair-image");
    const preview = row.querySelector(".flair-preview");

    if (sel.value === "icon") {
      show(iconPicker);
      hide(qrInput);
      hide(imgInput);
      if (preview) {
        hide(preview);
        preview.src = "";
      }
    } else if (sel.value === "image") {
      hide(iconPicker);
      hide(qrInput);
      show(imgInput);
    } else if (sel.value === "qr") {
      hide(iconPicker);
      show(qrInput);
      hide(imgInput);
      if (preview) {
        hide(preview);
        preview.src = "";
      }
    } else {
      hide(iconPicker);
      hide(qrInput);
      hide(imgInput);
      if (preview) {
        hide(preview);
        preview.src = "";
      }
    }
  }

  // Hide remove button for the very first task in the only section; show otherwise
  function updateRemoveButtons(taskContainer) {
    const taskInputs = taskContainer.querySelectorAll(".task-input");
    const subtitleSections = document.getElementById("subtitleSections");
    const isOnlySection = subtitleSections.children.length === 1;

    taskInputs.forEach((input) => {
      const removeBtn = input.querySelector(".remove-task");
      if (!removeBtn) return;
      if (taskInputs.length === 1 && isOnlySection) {
        hide(removeBtn);
      } else {
        show(removeBtn);
      }
    });
  }

  // Serialize the form into sections/tasks JSON (excluding images)
  function collectFormSections() {
    const sections = [];
    const container = document.getElementById("subtitleSections");
    if (!container) return sections;

    const sectionDivs = container.querySelectorAll(".subtitle-section");
    sectionDivs.forEach((sec) => {
      const sid = sec.getAttribute("data-section");
      const subtitleInput =
        sec.querySelector(`#subtitle_${sid}`) ||
        sec.querySelector('input[type="text"]');
      const subtitle = ((subtitleInput && subtitleInput.value) || "").trim();
      const tasks = [];
      const taskContainer = sec.querySelector(".taskContainer");
      const taskRows = taskContainer
        ? taskContainer.querySelectorAll(".task-input")
        : [];
      Array.from(taskRows).forEach((row, idx) => {
        const tnum = idx + 1;
        const input =
          row.querySelector(`input[name="task_${sid}_${tnum}"]`) ||
          row.querySelector('input[type="text"]');
        const text = ((input && input.value) || "").trim();
        if (!text) return;

        const flairRow = taskContainer.querySelector(
          `.flair-row[data-for="${sid}_${tnum}"]`,
        );
        let flair_type = "none";
        let flair_value = null;
        if (flairRow) {
          const sel =
            flairRow.querySelector(
              `select[name="flair_type_${sid}_${tnum}"]`,
            ) || flairRow.querySelector(".tp-flair-type");
          if (sel) flair_type = sel.value || "none";
          if (flair_type === "icon") {
            const checked = flairRow.querySelector(
              `input[name="flair_icon_${sid}_${tnum}"]:checked`,
            );
            flair_value = checked ? checked.value : null;
            if (!flair_value) flair_type = "none";
          } else if (flair_type === "qr") {
            const qr =
              flairRow.querySelector(`input[name="flair_qr_${sid}_${tnum}"]`) ||
              flairRow.querySelector(".flair-qr");
            flair_value = qr ? (qr.value || "").trim() : null;
            if (!flair_value) flair_type = "none";
          } else if (flair_type === "image") {
            // Include the file input field name so the backend can associate the upload.
            const img =
              flairRow.querySelector(
                `input[name="flair_image_${sid}_${tnum}"]`,
              ) || flairRow.querySelector(".flair-image");
            const imgName =
              img && img.name ? img.name : `flair_image_${sid}_${tnum}`;
            flair_value = imgName;
          }
        }

        tasks.push({ text, flair_type, flair_value });
      });

      if (subtitle || tasks.length) {
        sections.push({ subtitle, tasks });
      }
    });

    return sections;
  }

  // Save current form as a template via JSON POST
  async function saveCurrentAsTemplate() {
    const name = (prompt("Save as Template — name:", "") || "").trim();
    if (!name) return;
    const notes = (prompt("Optional notes:", "") || "").trim();
    const sections = collectFormSections();
    if (!sections.length) {
      alert("No tasks to save.");
      return;
    }

    try {
      const res = await fetch("/templates", {
        method: "POST",
        headers: csrfHeader({
          "Content-Type": "application/json",
          Accept: "application/json",
        }),
        body: JSON.stringify({ name, notes, sections }),
      });
      if (!res.ok) {
        let err = {};
        try {
          err = await res.json();
        } catch {}
        alert("Save failed: " + (err.error || res.statusText));
        return;
      }
      location.href = "/templates";
    } catch (e) {
      alert("Save failed: " + e);
    }
  }

  // Before submitting the print form, attach payload_json with sections/tasks
  function attachPayloadOnSubmit() {
    const form = document.getElementById("taskForm");
    if (!form) return;

    form.addEventListener("submit", function () {
      // Remove any previous hidden payload
      const prev = form.querySelector('input[name="payload_json"]');
      if (prev) prev.remove();

      const payload = collectFormSections();
      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = "payload_json";
      hidden.value = JSON.stringify({ sections: payload });
      form.appendChild(hidden);
    });
  }

  // Image preview change handling
  function handleImagePreviewChange() {
    document.addEventListener("change", function (e) {
      const input = e.target;
      if (
        !input ||
        !input.classList ||
        !input.classList.contains("flair-image")
      )
        return;
      const row = input.closest(".flair-row");
      const preview = row ? row.querySelector(".flair-preview") : null;
      if (input.files && input.files[0] && preview) {
        const reader = new FileReader();
        reader.onload = function (ev) {
          preview.src = ev.target.result;
          show(preview);
        };
        reader.readAsDataURL(input.files[0]);
      } else if (preview) {
        preview.src = "";
        hide(preview);
      }
    });
  }

  // Flair type change via event delegation
  function handleFlairTypeChange() {
    document.addEventListener("change", function (e) {
      const sel = e.target;
      if (!sel || sel.tagName !== "SELECT") return;
      if (!(sel.classList && sel.classList.contains("tp-flair-type"))) return;
      onFlairTypeChange(sel);
    });
  }

  // Job status polling
  function initJobStatusPolling() {
    const container = document.getElementById("jobStatus");
    if (!container) return;
    const jobId = container.getAttribute("data-job-id");
    const text = document.getElementById("jobStatusText");
    const dismiss = document.getElementById("jobDismissBtn");
    let timer = null;

    function update() {
      fetch(`/jobs/${jobId}`)
        .then((r) => {
          if (!r.ok) {
            throw new Error("not found");
          }
          return r.json();
        })
        .then((j) => {
          if (text) text.textContent = `— ${j.status}`;
          if (j.status === "success" || j.status === "error") {
            clearInterval(timer);
            setTimeout(() => {
              container.style.display = "none";
            }, 4000);
          }
        })
        .catch(() => {
          if (text) text.textContent = "— unavailable";
          clearInterval(timer);
          setTimeout(() => {
            container.style.display = "none";
          }, 4000);
        });
    }

    timer = setInterval(update, 2000);
    update();
    if (dismiss) {
      dismiss.addEventListener("click", () => {
        if (timer) clearInterval(timer);
        container.style.display = "none";
      });
    }
  }

  // Wire Save as Template button
  function wireSaveAsTemplateButton() {
    const saveBtn = document.getElementById("saveTplBtn");
    if (!saveBtn) return;
    saveBtn.addEventListener("click", function () {
      saveCurrentAsTemplate();
    });
  }

  // Prefill helpers (moved from inline index.html script)
  function setFlairForTask(sectionDiv, sid, tnum, t) {
    const rowSel =
      sectionDiv.querySelector(`select[name="flair_type_${sid}_${tnum}"]`) ||
      sectionDiv.querySelector(".tp-flair-type");
    if (!rowSel) return;
    const ftype = t && t.flair_type ? String(t.flair_type) : "none";
    const fval = t ? t.flair_value : null;
    rowSel.value = ftype;
    onFlairTypeChange(rowSel);

    if (ftype === "icon" && fval != null) {
      const radios = sectionDiv.querySelectorAll(
        `input[name="flair_icon_${sid}_${tnum}"]`,
      );
      for (let i = 0; i < radios.length; i++) {
        if (String(radios[i].value) === String(fval)) {
          radios[i].checked = true;
          break;
        }
      }
    } else if (ftype === "qr" && fval != null) {
      const qr = sectionDiv.querySelector(
        `input[name="flair_qr_${sid}_${tnum}"]`,
      );
      if (qr) qr.value = String(fval);
    }
    // images cannot be prefilled due to browser file input restrictions
  }

  function prefillFromTemplateData(tpl) {
    const container = document.getElementById("subtitleSections");
    if (!container) return false;

    try {
      // Reset sections
      container.innerHTML = "";
      sectionCount = 0;
      // Clear counts
      for (const k in taskCounts) {
        if (Object.hasOwn(taskCounts, k)) delete taskCounts[k];
      }

      const sections = Array.isArray(tpl.sections) ? tpl.sections : [];
      sections.forEach((sec) => {
        addSubtitleSection();
        const sectionDiv = container.lastElementChild;
        if (!sectionDiv) return;
        const sid = sectionDiv.getAttribute("data-section");
        const subInput = sectionDiv.querySelector(`#subtitle_${sid}`);
        if (subInput) subInput.value = sec && sec.subtitle ? sec.subtitle : "";

        const tasks = Array.isArray(sec.tasks) ? sec.tasks : [];
        if (tasks.length === 0) return;

        // First task
        const firstTaskInput = sectionDiv.querySelector(
          `input[name="task_${sid}_1"]`,
        );
        if (firstTaskInput)
          firstTaskInput.value = tasks[0] && tasks[0].text ? tasks[0].text : "";
        setFlairForTask(sectionDiv, sid, 1, tasks[0]);

        // Additional tasks
        for (let i = 1; i < tasks.length; i++) {
          const addBtn = sectionDiv.querySelector(".add-task-btn");
          if (addBtn) addTask(addBtn);
          const tnum = i + 1;
          const taskInput = sectionDiv.querySelector(
            `input[name="task_${sid}_${tnum}"]`,
          );
          if (taskInput)
            taskInput.value = tasks[i] && tasks[i].text ? tasks[i].text : "";
          setFlairForTask(sectionDiv, sid, tnum, tasks[i]);
        }

        const taskContainer = sectionDiv.querySelector(".taskContainer");
        if (taskContainer) updateRemoveButtons(taskContainer);
      });

      return true;
    } catch {
      return false;
    }
  }

  async function autoPrefill() {
    // 1) Server-provided object (/?prefill=<id> path)
    try {
      if (
        typeof window.__PREFILL_TEMPLATE !== "undefined" &&
        window.__PREFILL_TEMPLATE
      ) {
        const ok = prefillFromTemplateData(window.__PREFILL_TEMPLATE);
        window.__PREFILL_TEMPLATE = null;
        if (ok) return true;
      }
    } catch {
      /* ignore */
    }

    // 2) LocalStorage path
    try {
      const raw = localStorage.getItem("taskprinter:prefill_template");
      if (raw) {
        localStorage.removeItem("taskprinter:prefill_template");
        const data = JSON.parse(raw);
        if (prefillFromTemplateData(data)) return true;
      }
    } catch {
      /* ignore */
    }

    // 3) Client fetch based on URL param (?prefill=<id>) as last resort
    try {
      const m = (location.search || "").match(/[?&]prefill=(\d+)/);
      if (m) {
        const pid = m[1];
        const res = await fetch(`/templates/${pid}`, {
          headers: { Accept: "application/json" },
        });
        if (res && res.ok) {
          const data = await res.json();
          if (prefillFromTemplateData(data)) return true;
        }
      }
    } catch {
      /* ignore */
    }

    return false;
  }

  // Initialize module on DOM ready
  function init() {
    ensureTemplates();
    initCounts();
    // If there are no sections (fresh page with nothing rendered), create one
    const container = document.getElementById("subtitleSections");
    if (container && container.children.length === 0) {
      addSubtitleSection();
    } else {
      // Ensure remove buttons state is correct for existing content
      if (container) {
        const sections = container.querySelectorAll(
          ".subtitle-section .taskContainer",
        );
        Array.from(sections).forEach((tc) => updateRemoveButtons(tc));
      }
    }

    // Attempt automatic prefill from multiple sources
    // This may overwrite the initial default section created above.
    autoPrefill();

    // Delegated handlers for dynamically added buttons that use our functions explicitly
    document.addEventListener("click", function (e) {
      const target = e.target;
      if (!(target instanceof Element)) return;

      if (target.classList.contains("add-task-btn")) {
        e.preventDefault();
        addTask(target);
      } else if (target.classList.contains("remove-task")) {
        e.preventDefault();
        removeTask(target);
      }
    });

    handleImagePreviewChange();
    handleFlairTypeChange();
    attachPayloadOnSubmit();
    initJobStatusPolling();
    wireSaveAsTemplateButton();

    // Expose API for legacy inline handlers support
    window.TaskPrinter = {
      addSubtitleSection,
      addTask,
      removeTask,
      onFlairTypeChange,
      updateRemoveButtons,
      collectFormSections,
      saveCurrentAsTemplate,
      prefillFromTemplateData, // exposed for potential manual hooks
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
