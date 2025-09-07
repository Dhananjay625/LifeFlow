(function(){
    const board=document.getElementById('kanban');if(!board)return;
    const getCsrf=()=>document.querySelector('meta[name="csrf-token"]').content;
    let dragEl=null;
  
    function hookCard(card){
      card.addEventListener('dragstart',e=>{
        dragEl=card;
        card.classList.add('dragging');
      });
      card.addEventListener('dragend',()=>{
        if(dragEl) dragEl.classList.remove('dragging');
        dragEl=null;
        saveOrder();
      });
    }
  
    document.querySelectorAll('.kanban-item').forEach(hookCard);
  
    document.querySelectorAll('.kanban-column').forEach(col=>{
      col.addEventListener('dragover',e=>{
        e.preventDefault();
        const after=getDragAfterElement(col,e.clientY);
        if(!dragEl)return;
        if(after==null) col.appendChild(dragEl);
        else col.insertBefore(dragEl,after);
      });
      col.addEventListener('drop',()=>{
        document.querySelectorAll('.kanban-item').forEach(hookCard);
      });
    });
  
    function getDragAfterElement(container,y){
      const els=[...container.querySelectorAll('.kanban-item:not(.dragging)')];
      return els.reduce((closest,child)=>{
        const box=child.getBoundingClientRect();
        const offset=y-box.top-box.height/2;
        return (offset<0 && offset>closest.offset)?{offset,element:child}:closest;
      },{offset:Number.NEGATIVE_INFINITY}).element;
    }
  
    function saveOrder(){
      const moves=[];
      document.querySelectorAll('.kanban-column').forEach(col=>{
        const status=parseInt(col.dataset.status,10);
        [...col.querySelectorAll('.kanban-item')].forEach((item,index)=>{
          moves.push({item_id:parseInt(item.dataset.id,10),status,order:index});
        });
      });
      fetch(board.dataset.updateUrl,{
        method:'POST',
        headers:{
          'Content-Type':'application/json',
          'X-CSRFToken':getCsrf()
        },
        body:JSON.stringify({moves})
      }).catch(()=>{});
    }
  })();
  