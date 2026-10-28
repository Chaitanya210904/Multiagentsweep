/**
 * Multi-Agent Visual Dashboard Application Logic.
 * Handles state synchronization, REST API integration, tab navigation,
 * orchestrator execution, critic report visualization, and human-in-the-loop approvals.
 */

class DashboardApp {
  constructor() {
    this.graph = null;
    this.statusData = null;
    this.reportData = null;
    this.activeTab = 'dashboard';
    this.pollingTimer = null;

    this.init();
  }

  async init() {
    this.bindNavigation();
    this.bindAuditModal();
    this.bindGithubModal();

    // Initialize graph engine
    const canvas = document.getElementById('graphCanvas');
    if (canvas) {
      this.graph = new InteractiveCodeGraph('graphCanvas', 'nodeTooltip');
      this.bindGraphControls();
    }

    // Initial data load
    await this.refreshAll();

    // Start background heartbeat
    this.pollingTimer = setInterval(() => this.pollHeartbeat(), 8000);
  }

  // ---------------- Navigation & Tab Switching ----------------
  bindNavigation() {
    const tabs = document.querySelectorAll('.nav-tab-btn');
    tabs.forEach(btn => {
      btn.addEventListener('click', () => {
        const target = btn.dataset.tab;
        this.switchTab(target);
      });
    });
  }

  switchTab(tabId) {
    this.activeTab = tabId;

    document.querySelectorAll('.nav-tab-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.tab === tabId);
    });

    document.querySelectorAll('.tab-pane').forEach(p => {
      p.classList.toggle('active', p.id === `tab-${tabId}`);
    });

    if (tabId === 'graph' && this.graph) {
      setTimeout(() => {
        this.graph.initCanvasSize();
        this.graph.render();
      }, 50);
    } else if (tabId === 'logs') {
      this.fetchLogs();
    }
  }

  // ---------------- API Integration ----------------
  async refreshAll() {
    await Promise.all([
      this.fetchStatus(),
      this.fetchReport(),
      this.fetchGraph(),
    ]);
  }

  async fetchStatus() {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      this.statusData = data;
      this.renderStatus(data);
      this.renderAgentsList(data.agents || []);
    } catch (e) {
      console.error('Failed to fetch status:', e);
    }
  }

  async fetchReport() {
    try {
      const res = await fetch('/api/report');
      const data = await res.json();
      if (data && data.unified_report) {
        this.reportData = data;
        this.renderReport(data.unified_report, data.subtasks || []);
      }
    } catch (e) {
      console.error('Failed to fetch report:', e);
    }
  }

  async fetchGraph() {
    try {
      const res = await fetch('/api/graph?limit=500');
      const data = await res.json();
      if (this.graph) {
        this.graph.setData(data);
        const countEl = document.getElementById('renderedNodesCount');
        if (countEl) countEl.innerText = `${data.rendered_nodes_count} / ${data.total_nodes_in_registry}`;
      }
    } catch (e) {
      console.error('Failed to fetch graph data:', e);
    }
  }

  async fetchLogs() {
    try {
      const res = await fetch('/api/logs?limit=50');
      const data = await res.json();
      this.renderLogs(data.logs || []);
    } catch (e) {
      console.error('Failed to fetch logs:', e);
    }
  }

  async pollHeartbeat() {
    if (this.activeTab === 'logs') {
      await this.fetchLogs();
    }
  }

  // ---------------- Render Views ----------------
  renderStatus(data) {
    const totalNodesEl = document.getElementById('metricTotalNodes');
    if (totalNodesEl) totalNodesEl.innerText = data.total_nodes.toLocaleString();

    const filesCountEl = document.getElementById('metricFilesCount');
    if (filesCountEl) filesCountEl.innerText = (data.type_counts.file || 0).toLocaleString();

    const apisCountEl = document.getElementById('metricApisCount');
    if (apisCountEl) apisCountEl.innerText = (data.type_counts.api || 0).toLocaleString();

    const dbsCountEl = document.getElementById('metricDbsCount');
    if (dbsCountEl) dbsCountEl.innerText = (data.type_counts.table || 0).toLocaleString();

    const agentsCountEl = document.getElementById('metricAgentsCount');
    if (agentsCountEl) agentsCountEl.innerText = data.total_agents;

    // Latest run summary metrics
    if (data.latest_run) {
      const lr = data.latest_run;
      const prunedEl = document.getElementById('metricPrunedCount');
      if (prunedEl) prunedEl.innerText = lr.false_alarms_pruned;

      const activeEl = document.getElementById('metricActiveFindings');
      if (activeEl) activeEl.innerText = lr.active_findings_count;

      this.updateDial(lr.overall_health_score);
    }
  }

  updateDial(score) {
    const dialNum = document.getElementById('dialHealthScore');
    const dialProg = document.getElementById('dialProgress');
    if (!dialNum || !dialProg) return;

    const rounded = Math.round(score);
    dialNum.innerText = rounded;

    // SVG circumference for r=65 is ~408.4
    const circ = 408.4;
    const offset = circ - (circ * (score / 100));
    dialProg.style.strokeDashoffset = offset;

    // Color based on health tier
    if (score >= 85) {
      dialProg.style.stroke = '#10b981'; // Green
    } else if (score >= 65) {
      dialProg.style.stroke = '#f59e0b'; // Amber
    } else {
      dialProg.style.stroke = '#ef4444'; // Red
    }
  }

  renderReport(report, subtasks) {
    this.updateDial(report.overall_health_score);

    // Executive summary text
    const execTextEl = document.getElementById('execSummaryText');
    if (execTextEl) execTextEl.innerText = report.executive_summary;

    // Severity badges
    const critEl = document.getElementById('countCrit');
    if (critEl) critEl.innerText = report.critical_count;
    const highEl = document.getElementById('countHigh');
    if (highEl) highEl.innerText = report.high_count;
    const medEl = document.getElementById('countMed');
    if (medEl) medEl.innerText = report.medium_count;
    const infoEl = document.getElementById('countInfo');
    if (infoEl) infoEl.innerText = report.info_count;

    // Domain breakdown bars
    this.renderDomainBars(report.agent_health_scores || {});

    // Top impact-ranked findings table
    this.renderRankedFindings(report.ranked_findings || []);

    // Pruned false alarms list
    this.renderPrunedFindings(report.pruned_findings || []);

    // Remediation options (Human-in-the-Loop)
    this.renderRemediations(report.remediation_options || []);

    // Subtask DAG list
    this.renderSubtasks(subtasks);
  }

  renderDomainBars(scores) {
    const container = document.getElementById('domainBarsContainer');
    if (!container) return;

    const domains = [
      { key: 'security', label: 'Security & Auth', color: '#ef4444' },
      { key: 'quality', label: 'Code Quality & Tech Debt', color: '#f59e0b' },
      { key: 'architecture', label: 'Architecture Decoupling', color: '#a855f7' },
      { key: 'policy_compliance', label: 'Company Policy Compliance', color: '#10b981' },
      { key: 'runtime', label: 'Runtime & Scale SLA', color: '#3b82f6' },
    ];

    container.innerHTML = domains.map(d => {
      const val = Math.round(scores[d.key] || 100.0);
      return `
        <div class="domain-bar-item">
          <div class="domain-bar-header">
            <span style="color:#cbd5e1">${d.label}</span>
            <span style="color:#fff; font-weight:600">${val}%</span>
          </div>
          <div class="domain-bar-track">
            <div class="domain-bar-fill" style="width: ${val}%; background: ${d.color};"></div>
          </div>
        </div>
      `;
    }).join('');
  }

  renderRankedFindings(findings) {
    const tbody = document.getElementById('findingsTableBody');
    if (!tbody) return;

    if (findings.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:2rem; color:#64748b;">No active findings! Codebase is in pristine health.</td></tr>`;
      return;
    }

    tbody.innerHTML = findings.slice(0, 50).map(f => {
      const sevClass = `badge-${(f.severity || 'medium').toLowerCase()}`;
      const loc = f.file_path ? `<span class="code-loc">${f.file_path}${f.line_number ? `:${f.line_number}` : ''}</span>` : 'N/A';
      return `
        <tr>
          <td><span class="badge ${sevClass}">${(f.severity || 'MEDIUM').toUpperCase()}</span></td>
          <td><strong style="color:#fff; font-size:0.875rem;">${f.impact_score.toFixed(1)}</strong></td>
          <td>
            <div style="font-weight:600; color:#fff;">${f.title}</div>
            <div style="font-size:0.75rem; color:#94a3b8; margin-top:2px;">${f.description || ''}</div>
          </td>
          <td>${loc}</td>
          <td><span class="badge badge-control">${f.source_agent}</span></td>
          <td style="font-size:0.8rem; color:#cbd5e1;">${f.remediation_proposal || ''}</td>
        </tr>
      `;
    }).join('');
  }

  renderPrunedFindings(pruned) {
    const list = document.getElementById('prunedFindingsList');
    if (!list) return;

    if (pruned.length === 0) {
      list.innerHTML = `<div style="color:#64748b; font-size:0.85rem; padding:1rem;">No false alarms or duplicates pruned in this run.</div>`;
      return;
    }

    list.innerHTML = pruned.slice(0, 20).map(p => `
      <div style="padding:0.75rem; border-bottom:1px solid rgba(255,255,255,0.04); display:flex; align-items:center; justify-content:space-between;">
        <div>
          <span style="font-size:0.85rem; font-weight:600; color:#cbd5e1;">${p.title}</span>
          <span class="badge badge-info" style="margin-left:0.5rem;">${p.source_agent}</span>
          <div style="font-size:0.75rem; color:#64748b; margin-top:2px;">Reason: ${p.suppression_reason || 'Duplicate / non-existent'}</div>
        </div>
        <span class="badge" style="background:rgba(239,68,68,0.1); color:#fca5a5;">PRUNED</span>
      </div>
    `).join('');
  }

  renderRemediations(options) {
    const container = document.getElementById('remediationContainer');
    if (!container) return;

    if (options.length === 0) {
      container.innerHTML = `<div style="text-align:center; color:#64748b; padding:2rem;">No open remediation proposals requiring approval.</div>`;
      return;
    }

    container.innerHTML = options.map(opt => `
      <div class="remediation-card" id="card-${opt.option_id}">
        <div class="rem-header">
          <div>
            <span class="badge badge-control" style="font-family:var(--font-mono);">${opt.option_id}</span>
            <strong style="color:#fff; font-size:0.95rem; margin-left:0.5rem;">${opt.title}</strong>
          </div>
          <span class="badge badge-${opt.severity ? opt.severity.toLowerCase() : 'critical'}">${opt.severity || 'CRITICAL'}</span>
        </div>
        <div style="font-size:0.8rem; color:#94a3b8;">
          Target: <span class="code-loc">${opt.target_file}${opt.line_number ? `:${opt.line_number}` : ''}</span>
          <span style="margin-left:1rem;">Impact Score: <strong style="color:#00f0ff">${opt.impact_score || 80.0}</strong></span>
        </div>
        <div class="rem-action">Proposed Action: ${opt.action}</div>
        <div class="rem-footer">
          <button class="btn-dismiss" onclick="app.decideRemediation('${opt.option_id}', 'REJECT')">Dismiss</button>
          <button class="btn-approve" onclick="app.decideRemediation('${opt.option_id}', 'APPROVE')">✓ Approve Remediation</button>
        </div>
      </div>
    `).join('');
  }

  async decideRemediation(optionId, decision) {
    try {
      const res = await fetch('/api/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ option_id: optionId, decision }),
      });
      const data = await res.json();

      const card = document.getElementById(`card-${optionId}`);
      if (card) {
        card.style.opacity = '0.5';
        card.innerHTML = `
          <div style="padding:1rem; text-align:center; color:${decision === 'APPROVE' ? '#10b981' : '#ef4444'}; font-weight:600;">
            ${decision === 'APPROVE' ? '✓ Operator Approval Granted' : '✕ Proposal Dismissed'} (${optionId})
          </div>
        `;
      }
    } catch (e) {
      alert(`Failed to record decision: ${e}`);
    }
  }

  renderSubtasks(subtasks) {
    const list = document.getElementById('pipelineSubtasksList');
    if (!list) return;

    list.innerHTML = subtasks.map(st => {
      const isDone = st.status === 'completed';
      const icon = isDone ? '✓' : (st.status === 'running' ? '⏳' : '○');
      const cls = isDone ? 'status-completed' : (st.status === 'running' ? 'status-running' : 'status-pending');
      const dur = st.duration_ms ? `${st.duration_ms.toFixed(1)}ms` : '';
      return `
        <div class="subtask-item">
          <div class="subtask-left">
            <div class="subtask-status-icon ${cls}">${icon}</div>
            <div class="subtask-info">
              <h4>${st.description}</h4>
              <p>Subtask: <span style="font-family:var(--font-mono); color:var(--layer-control)">${st.subtask_id}</span> | Agent: <strong style="color:#fff">${st.agent_id}</strong> (${st.layer})</p>
            </div>
          </div>
          <div style="font-family:var(--font-mono); font-size:0.8rem; color:#94a3b8;">${dur}</div>
        </div>
      `;
    }).join('');
  }

  renderAgentsList(agents) {
    const container = document.getElementById('agentsDirectoryGrid');
    if (!container) return;

    container.innerHTML = agents.map(a => `
      <div class="metric-card" style="padding:1rem;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.5rem;">
          <strong style="color:#fff; font-size:0.9rem;">${a.name}</strong>
          <span class="badge badge-${a.layer}">${a.layer.toUpperCase()}</span>
        </div>
        <div style="font-size:0.75rem; color:#94a3b8; line-height:1.4;">${a.description}</div>
        <div style="display:flex; justify-content:space-between; font-size:0.7rem; color:#64748b; margin-top:0.75rem; border-top:1px solid rgba(255,255,255,0.05); padding-top:0.5rem;">
          <span>Tier: <strong style="color:#cbd5e1">${a.model_tier.toUpperCase()}</strong></span>
          <span>Access: <strong style="color:#cbd5e1">${a.access}</strong></span>
        </div>
      </div>
    `).join('');
  }

  renderLogs(logs) {
    const container = document.getElementById('logsContainer');
    if (!container) return;

    container.innerHTML = logs.map(l => {
      const timeStr = l.timestamp ? new Date(l.timestamp * 1000).toLocaleTimeString() : '';
      const levelColor = l.level === 'ERROR' ? '#ef4444' : (l.level === 'WARNING' ? '#f59e0b' : '#10b981');
      return `
        <div style="font-family:var(--font-mono); font-size:0.75rem; padding:0.35rem 0.5rem; border-bottom:1px solid rgba(255,255,255,0.03); display:flex; gap:0.75rem;">
          <span style="color:#64748b;">${timeStr}</span>
          <span style="color:${levelColor}; font-weight:600;">[${l.level || 'INFO'}]</span>
          <span style="color:#00f0ff;">[${l.layer || ''}.${l.agent_id || ''}]</span>
          <span style="color:#e2e8f0;">${l.message || l.event || ''}</span>
        </div>
      `;
    }).join('');
  }

  // ---------------- Audit Modal ----------------
  bindAuditModal() {
    const modal = document.getElementById('auditModal');
    const openBtn = document.getElementById('btnOpenAuditModal');
    const closeBtn = document.getElementById('btnCloseAuditModal');
    const form = document.getElementById('auditForm');

    if (openBtn) openBtn.addEventListener('click', () => { modal.style.display = 'flex'; });
    if (closeBtn) closeBtn.addEventListener('click', () => { modal.style.display = 'none'; });

    if (form) {
      form.addEventListener('submit', async e => {
        e.preventDefault();
        const title = document.getElementById('auditTitle').value;
        const budget = parseFloat(document.getElementById('auditBudget').value) || null;
        const parallel = document.getElementById('auditParallel').checked;

        const triggerBtn = document.getElementById('btnSubmitAudit');
        triggerBtn.disabled = true;
        triggerBtn.innerText = '⏳ Executing Pipeline...';

        try {
          const res = await fetch('/api/orchestrate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_title: title, budget_limit_usd: budget, parallel }),
          });
          const data = await res.json();
          modal.style.display = 'none';
          await this.refreshAll();
          this.switchTab('critic');
        } catch (err) {
          alert(`Orchestration failed: ${err}`);
        } finally {
          triggerBtn.disabled = false;
          triggerBtn.innerText = 'Launch Orchestration';
        }
      });
    }
  }

  // ---------------- GitHub Modal ----------------
  bindGithubModal() {
    const modal = document.getElementById('githubModal');
    const openBtn = document.getElementById('btnOpenGithubModal');
    const closeBtn = document.getElementById('btnCloseGithubModal');
    const cancelBtn = document.getElementById('btnCancelGithub');
    const form = document.getElementById('githubForm');
    const statusMsg = document.getElementById('githubStatusMsg');
    const submitBtn = document.getElementById('btnSubmitGithub');

    const closeModal = () => {
      modal.style.display = 'none';
      if (statusMsg) {
        statusMsg.style.display = 'none';
        statusMsg.innerHTML = '';
      }
    };

    if (openBtn) openBtn.addEventListener('click', () => { modal.style.display = 'flex'; });
    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (cancelBtn) cancelBtn.addEventListener('click', closeModal);

    if (form) {
      form.addEventListener('submit', async e => {
        e.preventDefault();
        const url = document.getElementById('githubUrl').value.trim();
        const depth = parseInt(document.getElementById('githubDepth').value, 10) || 1;
        const runAudit = document.getElementById('githubRunAudit').checked;

        submitBtn.disabled = true;
        submitBtn.innerText = '⏳ Processing Repo...';

        statusMsg.style.display = 'block';
        statusMsg.style.background = 'rgba(0, 240, 255, 0.08)';
        statusMsg.style.border = '1px solid rgba(0, 240, 255, 0.25)';
        statusMsg.style.color = '#00f0ff';
        statusMsg.innerHTML = `
          <div>🔄 <strong>Cloning repository & running Multi-Agent pipeline...</strong></div>
          <div style="font-size:0.75rem; color:#94a3b8; margin-top:0.3rem;">
            1. Git clone & shallow checkout<br>
            2. Structure Mapper AST indexing<br>
            3. Relationship Linker code edges<br>
            4. Data & Service Mapper APIs & DBs<br>
            ${runAudit ? '5. Autonomous 16-Agent Audit (Quality, Security, Critic)' : ''}
          </div>
        `;

        try {
          const res = await fetch('/api/github-analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, depth, run_orchestration: runAudit }),
          });

          const data = await res.json();
          if (!res.ok || data.error) {
            throw new Error(data.error || 'Failed to analyze repository');
          }

          statusMsg.style.background = 'rgba(16, 185, 129, 0.1)';
          statusMsg.style.border = '1px solid rgba(16, 185, 129, 0.3)';
          statusMsg.style.color = '#10b981';
          statusMsg.innerHTML = `
            <div>✅ <strong>Successfully analyzed ${data.repo_name}!</strong></div>
            <div style="font-size:0.75rem; color:#cbd5e1; margin-top:0.25rem;">
              • Scanned Files: ${data.files_scanned || 0}<br>
              • Code Entities: ${data.nodes_count || 0}<br>
              • Code Edges: ${data.edges_count || 0}<br>
              • APIs / DBs: ${data.apis_count || 0} / ${data.tables_count || 0}
            </div>
          `;

          await this.refreshAll();

          setTimeout(() => {
            closeModal();
            this.switchTab('graph');
          }, 1400);

        } catch (err) {
          statusMsg.style.background = 'rgba(239, 68, 68, 0.1)';
          statusMsg.style.border = '1px solid rgba(239, 68, 68, 0.3)';
          statusMsg.style.color = '#ef4444';
          statusMsg.innerHTML = `❌ <strong>Error:</strong> ${err.message || err}`;
        } finally {
          submitBtn.disabled = false;
          submitBtn.innerText = 'Clone & Analyze';
        }
      });
    }
  }

  // ---------------- Graph Controls ----------------
  bindGraphControls() {
    const resetBtn = document.getElementById('btnGraphReset');
    const zoomInBtn = document.getElementById('btnGraphZoomIn');
    const zoomOutBtn = document.getElementById('btnGraphZoomOut');
    const searchInput = document.getElementById('graphSearchInput');

    if (resetBtn) resetBtn.addEventListener('click', () => this.graph.resetView());
    if (zoomInBtn) zoomInBtn.addEventListener('click', () => this.graph.zoom(1.25));
    if (zoomOutBtn) zoomOutBtn.addEventListener('click', () => this.graph.zoom(0.8));
    if (searchInput) {
      searchInput.addEventListener('input', e => {
        this.graph.setFilter(e.target.value);
      });
    }
  }
}

// Global bootstrap
let app;
window.addEventListener('DOMContentLoaded', () => {
  app = new DashboardApp();
});
