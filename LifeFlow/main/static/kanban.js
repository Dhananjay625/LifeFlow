document.addEventListener("DOMContentLoaded", () => {
  const kanban = document.getElementById("kanban");
  if (!kanban) return;

  const updateUrl = kanban.dataset.updateUrl;
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

  let draggedItem = null;

 
  async function postJSON(url, data = {}) {
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error(`Request failed: ${res.status}`);
      return await res.json();
    } catch (err) {
      console.error("Fetch error:", err);
      return null;
    }
  }

  function makeDraggable(item) {
    item.setAttribute("draggable", "true");
    item.addEventListener("dragstart", e => {
      draggedItem = item;
      e.dataTransfer.effectAllowed = "move";
    });
  }

  document.querySelectorAll(".kanban-item").forEach(makeDraggable);

  document.querySelectorAll(".kanban-column").forEach(column => {
    column.addEventListener("dragover", e => e.preventDefault());

    column.addEventListener("drop", async e => {
      e.preventDefault();
      if (!draggedItem) return;

      const taskId = draggedItem.dataset.id;
      const newStatus = column.dataset.status;

      const data = await postJSON(updateUrl, { id: taskId, status: newStatus });
      if (data) {
        column.appendChild(draggedItem);
        console.log("Task updated:", data);
      }
    });
  });


  kanban.addEventListener("click", async e => {
    const btn = e.target.closest("button");
    if (!btn) return;

    const card = btn.closest(".kanban-item");
    const url = btn.dataset.url;

    // Delete
    if (btn.classList.contains("delete")) {
      if (!confirm("Delete this task?")) return;
      const res = await fetch(url, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken }
      });
      if (res.ok && card) {
        card.remove();
      }
    }

    // Edit
    if (btn.classList.contains("edit")) {
      const titleEl = card.querySelector(".task-title");
      const currentTitle = titleEl?.textContent.trim();
      const newTitle = prompt("Edit task title:", currentTitle);
      if (!newTitle) return;

      const data = await postJSON(url, { title: newTitle });
      if (data && data.title && titleEl) {
        titleEl.textContent = data.title;
      }
    }
  });

 
  document.querySelectorAll(".add-card form").forEach(form => {
    form.addEventListener("submit", async e => {
      e.preventDefault();

      const formData = new FormData(form);
      const url = form.action;
      const payload = {};
      formData.forEach((val, key) => payload[key] = val);

      const data = await postJSON(url, payload);
      if (data && data.html) {
        // server should return rendered HTML for the new task
        const column = form.closest(".kanban-column");
        column.insertAdjacentHTML("beforeend", data.html);

        // re-bind draggable
        const newItem = column.querySelector(`.kanban-item[data-id="${data.id}"]`);
        if (newItem) makeDraggable(newItem);

        form.reset();
      }
    });
  });
});
