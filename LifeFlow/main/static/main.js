document.addEventListener('DOMContentLoaded', function () {
    fetch("{% url 'weekly_metrics_api' %}")
        .then(res => res.json())
        .then(data => {
            new Chart(document.getElementById('weeklyChart'), {
                type: 'line',
                data: {
                    labels: data.dates,
                    datasets: [
                        { label: 'Steps', data: data.steps, borderColor: 'blue', fill: false },
                        { label: 'Calories', data: data.calories, borderColor: 'orange', fill: false },
                        { label: 'Water (L)', data: data.water, borderColor: 'aqua', fill: false }
                    ]
                }
            });
        });
});