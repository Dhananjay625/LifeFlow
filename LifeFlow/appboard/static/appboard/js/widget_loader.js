function loadCalendarWidget() {
    const container = document.getElementById("calendar-widget-body");
    fetch("/api/widgets/calendar/")
      .then(res => res.json())
      .then(data => {
        container.innerHTML = "";
  
        if (data.events && data.events.length > 0) {
          data.events.forEach(ev => {
            const eventEl = document.createElement("div");
            eventEl.classList.add("event");
  
            eventEl.innerHTML = `
              <span>${ev.title}</span>
              <span class="event-date">${ev.date}</span>
            `;
            container.appendChild(eventEl);
          });
        } else {
          container.innerHTML = "<div>No upcoming events</div>";
        }
      })
      .catch(err => {
        container.innerHTML = "<div class='error'>Failed to load calendar</div>";
        console.error(err);
      });
  }
  
  window.addEventListener("DOMContentLoaded", () => {
    loadCalendarWidget();
  });