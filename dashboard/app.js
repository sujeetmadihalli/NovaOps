document.addEventListener('DOMContentLoaded', () => {
    const API_URL = 'http://127.0.0.1:8000/api/incidents';
    const container = document.getElementById('incidents-container');
    const refreshBtn = document.getElementById('refresh-btn');
    const template = document.getElementById('incident-template');
    
    // New UI Elements
    const sortSelect = document.getElementById('sort-select');
    const filterBtns = document.querySelectorAll('.filter-btn');
    const paginationControls = document.getElementById('pagination-controls');
    const prevBtn = document.getElementById('prev-page');
    const nextBtn = document.getElementById('next-page');
    const currentPageSpan = document.getElementById('current-page');
    const totalPagesSpan = document.getElementById('total-pages');

    // Tab Navigation UI
    const tabBtns = document.querySelectorAll('.tab-btn');
    const viewSections = document.querySelectorAll('.view-section');
    const terminalOutput = document.getElementById('terminal-output');

    let allIncidents = [];
    let currentFilter = 'all';
    let currentSort = 'newest';
    let currentPage = 1;
    const itemsPerPage = 3; // Kept at 3 to avoid vertical crowding

    // Fetch and render incidents
    async function fetchIncidents() {
        try {
            refreshBtn.classList.add('fa-spin');
            
            const response = await fetch(API_URL);
            if (!response.ok) throw new Error('Network response was not ok');
            
            const result = await response.json();
            allIncidents = result.data || [];
            applyFiltersAndRender();
            
        } catch (error) {
            console.error('Failed to fetch incidents:', error);
            container.innerHTML = `
                <div class="glass-card" style="text-align: center; color: var(--accent-red);">
                    <i class="fa-solid fa-triangle-exclamation" style="font-size: 2rem; margin-bottom: 1rem;"></i>
                    <p>Failed to connect to the Event Gateway API.</p>
                    <p style="font-size: 0.85rem; margin-top: 0.5rem; color: var(--text-secondary);">Ensure the FastAPI server is running on port 8000.</p>
                </div>
            `;
            paginationControls.style.display = 'none';
        } finally {
            setTimeout(() => refreshBtn.classList.remove('fa-spin'), 500);
        }
    }

    function applyFiltersAndRender() {
        // Apply Filter
        let filtered = allIncidents;
        if (currentFilter !== 'all') {
            filtered = allIncidents.filter(inc => inc.proposed_tool === currentFilter);
        }

        // Apply Sort
        filtered.sort((a, b) => {
            const timeA = new Date(a.timestamp + "Z").getTime();
            const timeB = new Date(b.timestamp + "Z").getTime();
            return currentSort === 'newest' ? timeB - timeA : timeA - timeB;
        });

        // Apply Pagination
        const totalItems = filtered.length;
        const totalPages = Math.ceil(totalItems / itemsPerPage) || 1;
        
        if (currentPage > totalPages) currentPage = totalPages;
        if (currentPage < 1) currentPage = 1;

        const startIndex = (currentPage - 1) * itemsPerPage;
        const endIndex = startIndex + itemsPerPage;
        const paginated = filtered.slice(startIndex, endIndex);

        renderIncidents(paginated);
        updatePaginationUI(totalPages);
    }

    function updatePaginationUI(totalPages) {
        if (allIncidents.length === 0) {
            paginationControls.style.display = 'none';
            return;
        }
        
        paginationControls.style.display = 'flex';
        currentPageSpan.textContent = currentPage;
        totalPagesSpan.textContent = totalPages;
        
        prevBtn.disabled = currentPage === 1;
        nextBtn.disabled = currentPage >= totalPages;
    }

    // Render logic
    function renderIncidents(incidents) {
        container.innerHTML = ''; // Clear loading state
        
        if (incidents.length === 0 && allIncidents.length === 0) {
            container.innerHTML = `
                <div class="glass-card" style="text-align: center; color: var(--text-secondary); padding: 3rem;">
                    <i class="fa-solid fa-shield-halved" style="font-size: 2rem; margin-bottom: 1rem; color: var(--accent-green);"></i>
                    <p>No incidents detected.</p>
                    <p style="font-size: 0.85rem; margin-top: 0.5rem;">The cluster is healthy and stable.</p>
                </div>
            `;
            return;
        } else if (incidents.length === 0) {
            container.innerHTML = `
                <div class="glass-card" style="text-align: center; color: var(--text-secondary); padding: 3rem;">
                    <i class="fa-solid fa-filter" style="font-size: 2rem; margin-bottom: 1rem;"></i>
                    <p>No incidents match the current filter.</p>
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

    // --- View 2: Live Logs Terminal ---
    
    // Simple ANSI to CSS parser for terminal colors
    function formatAnsiLog(line) {
        if (!line) return '';
        
        // Escape HTML first
        let html = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        
        // Replace ANSI color codes
        html = html.replace(/\x1b\[0;31m/g, '<span class="ansi-red">')
                   .replace(/\x1b\[0;32m/g, '<span class="ansi-green">')
                   .replace(/\x1b\[0;33m/g, '<span class="ansi-yellow">')
                   .replace(/\x1b\[0;34m/g, '<span class="ansi-blue">')
                   .replace(/\x1b\[0;35m/g, '<span class="ansi-magenta">')
                   .replace(/\x1b\[0;36m/g, '<span class="ansi-cyan">')
                   .replace(/\x1b\[0m/g, '</span>');
                   
        return html;
    }

    async function fetchLogs() {
        // Only fetch logs if the logs tab is actively visible to save bandwidth
        if (!document.getElementById('logs-view').classList.contains('active')) return;
        
        try {
            const response = await fetch('http://127.0.0.1:8000/api/logs');
            if (response.ok) {
                const result = await response.json();
                
                let htmlOutput = '';
                result.logs.forEach(line => {
                    htmlOutput += `<p>${formatAnsiLog(line)}</p>`;
                });
                
                // Only update DOM if the content actually changed to prevent scroll jumping
                if (terminalOutput.innerHTML !== htmlOutput) {
                    const isScrolledToBottom = terminalOutput.scrollHeight - terminalOutput.clientHeight <= terminalOutput.scrollTop + 50;
                    
                    terminalOutput.innerHTML = htmlOutput || '<p>No logs found...</p>';
                    
                    // Auto-scroll to bottom if they were already at the bottom
                    if (isScrolledToBottom) {
                        terminalOutput.scrollTop = terminalOutput.scrollHeight;
                    }
                }
            }
        } catch (e) {
            console.error('Failed to fetch logs:', e);
            terminalOutput.innerHTML = `<p class="ansi-red">Failed to connect to backend log stream.</p>`;
        }
    }

    // --- Event Listeners ---

    // Tab Switching
    tabBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            // Remove active classes
            tabBtns.forEach(b => b.classList.remove('active'));
            viewSections.forEach(v => v.classList.remove('active'));
            
            // Add to target
            const targetBtn = e.currentTarget;
            targetBtn.classList.add('active');
            
            const viewId = targetBtn.getAttribute('data-target');
            document.getElementById(viewId).classList.add('active');
            
            if (viewId === 'logs-view') {
                fetchLogs();
                // Force scroll to bottom on first open
                setTimeout(() => { terminalOutput.scrollTop = terminalOutput.scrollHeight; }, 100);
            }
        });
    });

    refreshBtn.addEventListener('click', fetchIncidents);

    sortSelect.addEventListener('change', (e) => {
        currentSort = e.target.value;
        applyFiltersAndRender();
    });

    filterBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            filterBtns.forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            currentFilter = e.target.getAttribute('data-filter');
            currentPage = 1; // Reset to first page on new filter
            applyFiltersAndRender();
        });
    });

    prevBtn.addEventListener('click', () => {
        if (currentPage > 1) {
            currentPage--;
            applyFiltersAndRender();
        }
    });

    nextBtn.addEventListener('click', () => {
        currentPage++;
        applyFiltersAndRender();
    });

    // Initial load
    fetchIncidents();
    
    // Auto-poll every 5 seconds for the demo
    setInterval(() => {
        fetchIncidents();
        fetchLogs();
    }, 5000);
});
