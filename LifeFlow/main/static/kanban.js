const $ = (s, p=document)=>p.querySelector(s);
const $$ = (s, p=document)=>Array.from(p.querySelectorAll(s));
const csrf = () => $('meta[name="csrf-token"]')?.getAttribute('content');

// --- Sidebar collapse ---
$("[data-resize-btn]")?.addEventListener("click", e => {
  e.preventDefault();
  document.body.classList.toggle("sb-expanded");
});

// ---------------- Add Cards (Items/Projects/Tasks) ----------------
function closeAllAdd() {
  $$('.add-card').forEach(box => {
    box.classList.remove('is-open');
    const form = $('.mini-form', box);
    const toggle = $('[data-add-toggle]', box);
    if (form) {
      form.hidden = true;
      form.reset();
      if (form.dataset.tid) clearTimeout(+form.dataset.tid);
    }
    if (toggle) toggle.hidden = false;
  });
}

$$('.add-card').forEach(box => {
  const toggle = $('[data-add-toggle]', box);
  const cancel = $('[data-add-cancel]', box);
  const form   = $('.mini-form', box);

  const open = () => {
    closeAllAdd();
    box.classList.add('is-open');
    form.hidden=false;
    form.querySelector('[name="title"], [name="name"]')?.focus();
    if (toggle) toggle.hidden=true;
  };
  const close = () => {
    box.classList.remove('is-open');
    form.hidden=true;
    form.reset();
    if (toggle) toggle.hidden=false;
  };

  toggle?.addEventListener('click', open);
  cancel?.addEventListener('click', close);

  // unified add handling
  if (form && form.dataset.bound !== "true") {
    form.dataset.bound = "true"; 
    form.addEventListener('submit', async e=>{
      e.preventDefault();
      const url = form.action;
      const data = new FormData(form);
      try {
        const res = await fetch(url, {
          method:'POST',
          headers:{
            'X-CSRFToken':csrf(),
            'X-Requested-With':'XMLHttpRequest'
          },
          body:data
        });
        if(!res.ok) throw new Error(await res.text());
        const item = await res.json();

        if (!item || !item.id) return;

        const card = buildKanbanCard(
          item.id,
          item.title || item.name,
          item.edit_url,
          item.delete_url
        );

        const itemsContainer = form.closest('.kanban-column');
        itemsContainer.insertBefore(card, form.closest('.add-card'));

        attachItemEvents(card);
        bindDragEvents(card);

        form.reset();
        form.hidden=true;
        box.classList.remove('is-open');
        if (toggle) toggle.hidden=false;
        document.dispatchEvent(new CustomEvent('kanban:updated'));
      } catch(err) {
        alert('Add failed: '+err.message);
      }
    });
  }
});

function buildKanbanCard(id, title, editUrl, deleteUrl) {
  const card = document.createElement('div');
  card.className = 'kanban-item task-with-actions';
  card.setAttribute('draggable','true');
  card.setAttribute('data-id', id);
  if (editUrl) card.setAttribute('data-edit-url', editUrl);
  if (deleteUrl) card.setAttribute('data-delete-url', deleteUrl);
  card.innerHTML = `<div class="task-row">
    <span class="task-title">${title}</span>
    <div class="task-actions">
      <button type="button" class="icon-btn edit" title="Edit"><i class='bx bx-edit'></i></button>
      <button type="button" class="icon-btn delete" title="Delete"><i class='bx bx-trash'></i></button>
    </div>
  </div>`;
  return card;
}

function refreshEmpty(){
  $$('.kanban-column').forEach(col=>{
    const hasItems = !!$('.kanban-item',col);
    $$('.kanban-empty',col).forEach(el=>el.style.display=hasItems?'none':'');
  });
}
refreshEmpty();
document.addEventListener('kanban:updated',refreshEmpty);

function attachItemEvents(card) {
  $('.edit', card)?.addEventListener('click', async ()=>{
    const newTitle = prompt("Edit:", $(".task-title", card).textContent);
    if(!newTitle) return;
    const res = await fetch(card.dataset.editUrl, {
      method:"POST",
      headers:{
        "X-CSRFToken":csrf(),
        "Content-Type":"application/x-www-form-urlencoded"
      },
      body:new URLSearchParams({title:newTitle})
    });
    const data = await res.json();
    if(data.ok) $(".task-title", card).textContent = newTitle;
    else alert(data.error||"Error editing");
  });

  $('.delete', card)?.addEventListener('click', async ()=>{
    if(!confirm("Delete this?")) return;
    const res = await fetch(card.dataset.deleteUrl, {
      method:"POST",
      headers:{"X-CSRFToken":csrf()}
    });
    const data = await res.json();
    if(data.ok) {
      card.remove();
      document.dispatchEvent(new CustomEvent("kanban:updated"));
    } else alert(data.error||"Delete failed");
  });
}

// ---------------- Drag & Drop Update ----------------
const kanban = $("#kanban");
if (kanban) {
  const updateUrl = kanban.dataset.updateUrl;
  let draggedCard = null;

  async function saveOrder(status, ids) {
    try {
      const res = await fetch(updateUrl, {
        method:"POST",
        headers:{
          "X-CSRFToken":csrf(),
          "Content-Type":"application/json",
          "X-Requested-With":"XMLHttpRequest"
        },
        body: JSON.stringify({status, ids})
      });
      return await res.json();
    } catch(err) {
      console.error("Update failed:", err);
    }
  }

  function bindDragEvents(card) {
    if (card.dataset.dragBound) return;
    card.dataset.dragBound = "true";

    card.addEventListener("dragstart", e=>{
      draggedCard = card;
      setTimeout(()=> card.classList.add("dragging"), 0);
    });
    card.addEventListener("dragend", e=>{
      card.classList.remove("dragging");
      draggedCard = null;
    });
  }

  // bind existing cards
  $$(".kanban-item").forEach(c=>{ attachItemEvents(c); bindDragEvents(c); });

  // columns
  $$(".kanban-column").forEach(col=>{
    col.addEventListener("dragover", e=>{
      e.preventDefault();
      const afterElement = getDragAfterElement(col, e.clientY);
      if (afterElement == null) {
        col.appendChild(draggedCard);
      } else {
        col.insertBefore(draggedCard, afterElement);
      }
    });

    col.addEventListener("drop", e=>{
      e.preventDefault();
      col.classList.remove("drag-over");
      const status = col.dataset.status;
      const ids = $$("[data-id]", col).map(el=>el.dataset.id);
      saveOrder(status, ids);
      document.dispatchEvent(new CustomEvent("kanban:updated"));
    });

    col.addEventListener("dragenter", ()=>col.classList.add("drag-over"));
    col.addEventListener("dragleave", ()=>col.classList.remove("drag-over"));
  });

  function getDragAfterElement(container, y) {
    const elements = [...container.querySelectorAll(".kanban-item:not(.dragging)")];
    return elements.reduce((closest, child)=>{
      const box = child.getBoundingClientRect();
      const offset = y - box.top - box.height/2;
      if (offset < 0 && offset > closest.offset) {
        return {offset: offset, element: child};
      } else {
        return closest;
      }
    }, {offset: Number.NEGATIVE_INFINITY}).element;
  }
}
