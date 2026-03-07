document.addEventListener('DOMContentLoaded', () => {
    const API_URL = 'http://127.0.0.1:8000/api/incidents';
    const container = document.getElementById('incidents-container');
    const refreshBtn = document.getElementById('refresh-btn');
    const template = document.getElementById('incident-template');

    // Fetch and render incidents
    async function fetchIncidents() {
        try {
            refreshBtn.classList.add('fa-spin');
            
            const response = await fetch(API_URL);
            if (!response.ok) throw new Error('Network response was not ok');
            
            const result = await response.json();
            renderIncidents(result.data);
            
        } catch (error) {
            console.error('Failed to fetch incidents:', error);
            container.innerHTML = `
                <div class="glass-card" style="text-align: center; color: var(--accent-red);">
                    <i class="fa-solid fa-triangle-exclamation" style="font-size: 2rem; margin-bottom: 1rem;"></i>
                    <p>Failed to connect to the Event Gateway API.</p>
                    <p style="font-size: 0.85rem; margin-top: 0.5rem; color: var(--text-secondary);">Ensure the FastAPI server is running on port 8000.</p>
                </div>
            `;
        } finally {
            setTimeout(() => refreshBtn.classList.remove('fa-spin'), 500);
        }
    }

    // Render logic
    function renderIncidents(incidents) {
        container.innerHTML = ''; // Clear loading state
        
        if (incidents.length === 0) {
            container.innerHTML = `
                <div class="glass-card" style="text-align: center; color: var(--text-secondary); padding: 3rem;">
                    <i class="fa-solid fa-shield-halved" style="font-size: 2rem; margin-bottom: 1rem; color: var(--accent-green);"></i>
                    <p>No incidents detected.</p>
                    <p style="font-size: 0.85rem; margin-top: 0.5rem;">The cluster is healthy and stable.</p>
                </div>
            `;
            return;
        }

        incidents.forEach(inc => {
            const clone = template.content.cloneNode(true);
            
            // Map JSON to DOM
            clone.querySelector('.alert-name').textContent = inc.alert_name;
            clone.querySelector('.service-name').textContent = inc.service_name;
            
            // Format timestamp relative to now
            const date = new Date(inc.timestamp + "Z"); // SQLite defaults to UTC
            clone.querySelector('.time-str').textContent = date.toLocaleString();
            
            clone.querySelector('.analysis-text').textContent = inc.analysis;
            clone.querySelector('.tool-name').textContent = inc.proposed_tool;
            clone.querySelector('.parameters').textContent = JSON.stringify(inc.action_parameters, null, 2);
            
            container.appendChild(clone);
        });
    }

    // Bind events
    refreshBtn.addEventListener('click', fetchIncidents);

    // Initial load
    fetchIncidents();
    
    // Auto-poll every 10 seconds for the demo
    setInterval(fetchIncidents, 10000);
});
