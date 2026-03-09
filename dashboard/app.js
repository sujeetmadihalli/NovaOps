document.addEventListener('DOMContentLoaded', () => {
    const API_URL = 'http://127.0.0.1:8082/api/incidents';
    const pirModal = document.getElementById('pir-modal');
    const pirLoading = document.getElementById('pir-loading');
    const pirContent = document.getElementById('pir-content');
    const pirCopyBtn = document.getElementById('pir-copy-btn');
    const pirDownloadBtn = document.getElementById('pir-download-btn');

    // PIR Modal helpers
    function openPirModal() {
        pirModal.style.display = 'flex';
        pirLoading.style.display = 'flex';
        pirContent.style.display = 'none';
        pirCopyBtn.style.display = 'none';
        pirDownloadBtn.style.display = 'none'; // Ensure download button is hidden on open
        pirContent.textContent = '';
    }

    function renderMarkdown(text) {
        return text
            .split('\n')
            .map(line => {
                if (line.startsWith('## '))  return `<h2>${line.slice(3)}</h2>`;
                if (line.startsWith('### ')) return `<h3>${line.slice(4)}</h3>`;
                if (line === '---') return '<hr>';
                // bold **text**
                line = line.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
                // italic *text*
                line = line.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>');
                if (line.startsWith('- [ ]')) return `<p class="pir-check">☐ ${line.slice(5)}</p>`;
                if (line.startsWith('- [x]')) return `<p class="pir-check">☑ ${line.slice(5)}</p>`;
                if (line.startsWith('- ') || line.startsWith('* ')) return `<p class="pir-bullet">• ${line.slice(2)}</p>`;
                if (line.trim() === '') return '<br>';
                return `<p>${line}</p>`;
            })
            .join('');
    }

    function showPirContent(text, pdfPath) {
        pirLoading.style.display = 'none';
        pirContent.style.display = 'block';
        pirCopyBtn.style.display = 'inline-flex';
        
        if (pdfPath) {
            pirDownloadBtn.style.display = 'inline-flex';
            pirDownloadBtn.dataset.pdfPath = pdfPath;
            pirDownloadBtn.onclick = () => downloadFromS3(pdfPath);
        } else {
            pirDownloadBtn.style.display = 'none';
        }
        
        pirContent.innerHTML = renderMarkdown(text);
        pirContent._rawText = text;
    }

    async function downloadFromS3(s3Key) {
        try {
            const btn = pirDownloadBtn;
            const originalHtml = btn.innerHTML;
            btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Downloading...';
            btn.disabled = true;
            
            // Fetch presigned URL from our backend
            const response = await fetch(`${API_URL}/download-pdf?key=${encodeURIComponent(s3Key)}`);
            if (!response.ok) throw new Error('Failed to get download link');
            
            const data = await response.json();
            
            // Trigger browser download
            const a = document.createElement('a');
            a.href = data.download_url;
            a.download = s3Key;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            
            setTimeout(() => {
                btn.innerHTML = originalHtml;
                btn.disabled = false;
            }, 1000);
        } catch (err) {
            console.error("Download failed:", err);
            alert("Failed to download PDF from S3.");
            pirDownloadBtn.innerHTML = '<i class="fa-solid fa-download"></i> Download PDF';
            pirDownloadBtn.disabled = false;
        }
    }

    function closePirModal() {
        pirModal.style.display = 'none';
    }

    document.getElementById('pir-close-btn').addEventListener('click', closePirModal);
    document.getElementById('pir-close-footer-btn').addEventListener('click', closePirModal);
    pirModal.addEventListener('click', (e) => { if (e.target === pirModal) closePirModal(); });

    pirCopyBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(pirContent._rawText || pirContent.textContent).then(() => {
            pirCopyBtn.innerHTML = '<i class="fa-solid fa-check"></i> Copied!';
            setTimeout(() => {
                pirCopyBtn.innerHTML = '<i class="fa-solid fa-copy"></i> Copy Report';
            }, 2000);
        });
    });

    async function fetchOrGeneratePir(incidentId) {
        openPirModal();
        try {
            // Try to get an existing PIR first
            let response = await fetch(`${API_URL}/${incidentId}/report`);
            if (response.ok) {
                const data = await response.json();
                showPirContent(data.report, data.pdf_path);
                return;
            }
            // Not found — generate a new one
            response = await fetch(`${API_URL}/${incidentId}/report`, { method: 'POST' });
            if (!response.ok) throw new Error(`Server error: ${response.status}`);
            const data = await response.json();
            showPirContent(data.report, data.pdf_path);
        } catch (err) {
            showPirContent(`Failed to generate Post-Incident Report.\n\nError: ${err.message}`, null);
        }
    }
    const container = document.getElementById('incidents-container');
    const refreshBtn = document.getElementById('refresh-btn');
    const template = document.getElementById('incident-template');
    
    // New UI Elements
    const sortSelect = document.getElementById('sort-select');
    const filterBtns = document.querySelectorAll('[data-filter]');
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
    let currentLogFilter = 'all';

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
                    <p style="font-size: 0.85rem; margin-top: 0.5rem; color: var(--text-secondary);">Ensure the FastAPI server is running on port 8082.</p>
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

            // Mark card if a PIR already exists
            const pirBtn = clone.querySelector('.pir-btn');
            if (inc.pir_report) {
                pirBtn.innerHTML = '<i class="fa-solid fa-file-circle-check"></i> View PIR';
                pirBtn.classList.add('pir-exists');
            }
            pirBtn.addEventListener('click', () => fetchOrGeneratePir(inc.incident_id));

            container.appendChild(clone);
        });
    }

    // --- View 2: Live Logs Terminal ---
    
    // Detect which service a log line came from
    function getLogSource(line) {
        if (line.includes('[Nova-Agent]') || line.includes('Nova-Agent') || line.includes('[Nova]')) return 'Nova-Agent';
        if (line.includes('[Event-API]') || line.includes('Event-API') || line.includes('uvicorn')) return 'Event-API';
        if (line.includes('[K8s-Prom]') || line.includes('K8s-Prom') || line.includes('kubectl')) return 'K8s-Prom';
        if (line.includes('[Dashboard]') || line.includes('Dashboard') || line.includes('http.server')) return 'Dashboard';
        return 'other';
    }

    // Simple ANSI to CSS parser for terminal colors
    function formatAnsiLog(line) {
        if (!line) return '';
        
        // Escape HTML first
        let html = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        
        // Replace ANSI color codes (using actual ESC char \x1b = \u001b)
        html = html.replace(/\u001b\[0;31m/g, '<span class="ansi-red">')
                   .replace(/\u001b\[0;32m/g, '<span class="ansi-green">')
                   .replace(/\u001b\[0;33m/g, '<span class="ansi-yellow">')
                   .replace(/\u001b\[0;34m/g, '<span class="ansi-blue">')
                   .replace(/\u001b\[0;35m/g, '<span class="ansi-magenta">')
                   .replace(/\u001b\[0;36m/g, '<span class="ansi-cyan">')
                   .replace(/\u001b\[0m/g, '</span>');
        
        // Strip any remaining unmatched ANSI escape sequences
        html = html.replace(/\u001b\[[0-9;]*m/g, '');
                   
        return html;
    }

    async function fetchLogs() {
        // Only fetch logs if the logs tab is actively visible to save bandwidth
        if (!document.getElementById('logs-view').classList.contains('active')) return;
        
        try {
            const response = await fetch('http://127.0.0.1:8082/api/logs');
            if (response.ok) {
                const result = await response.json();
                
                let htmlOutput = '';
                result.logs.forEach(line => {
                    const source = getLogSource(line);
                    const hidden = (currentLogFilter !== 'all' && source !== currentLogFilter) ? ' style="display:none"' : '';
                    htmlOutput += `<p data-source="${source}"${hidden}>${formatAnsiLog(line)}</p>`;
                });
                
                // Only update DOM if the log lines actually changed (ignore filter state)
                const newLogCount = result.logs.length;
                if (terminalOutput.dataset.logCount !== String(newLogCount) || terminalOutput.dataset.lastLog !== result.logs[result.logs.length - 1]) {
                    const isScrolledToBottom = terminalOutput.scrollHeight - terminalOutput.clientHeight <= terminalOutput.scrollTop + 50;
                    
                    terminalOutput.innerHTML = htmlOutput || '<p>No logs found...</p>';
                    terminalOutput.dataset.logCount = newLogCount;
                    terminalOutput.dataset.lastLog = result.logs[result.logs.length - 1] || '';
                    
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

    // Apply log filter without re-fetching
    function applyLogFilter(filter) {
        currentLogFilter = filter;
        const allLines = terminalOutput.querySelectorAll('p[data-source]');
        allLines.forEach(p => {
            if (filter === 'all' || p.dataset.source === filter) {
                p.style.display = '';
            } else {
                p.style.display = 'none';
            }
        });
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

    // Log filter buttons
    document.querySelectorAll('[data-log-filter]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('[data-log-filter]').forEach(b => b.classList.remove('active'));
            e.currentTarget.classList.add('active');
            applyLogFilter(e.currentTarget.getAttribute('data-log-filter'));
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
            e.currentTarget.classList.add('active');
            currentFilter = e.currentTarget.getAttribute('data-filter');
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
