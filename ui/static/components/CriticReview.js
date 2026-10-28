/**
 * Critic Review Component.
 * Displays findings & scores as they arrive from the Critic and Security agents.
 * Features:
 * - Grouped by category (Security, Architecture, Quality, Rules)
 * - Severity indicators (CRITICAL, HIGH, MEDIUM, LOW)
 * - Expandable details with code diffs & remediation suggestions
 * - Interactive "Authorize Remediation" approval workflow
 */

export class CriticReview {
  constructor(containerEl) {
    this.container = containerEl;
    this.findings = [];
    this.selectedCategory = 'ALL';
    this.expandedFindingIds = new Set();
    this.approvedFindingIds = new Set();

    this.render();
  }

  reset() {
    this.findings = [];
    this.expandedFindingIds.clear();
    this.approvedFindingIds.clear();
    this.updateFindingsList();
  }

  addFinding(finding) {
    if (this.findings.some(f => f.id === finding.id)) return;
    this.findings.push(finding);
    // Auto-expand critical and high findings
    if (finding.severity === 'CRITICAL' || finding.severity === 'HIGH') {
      this.expandedFindingIds.add(finding.id);
    }
    this.updateFindingsList();
  }

  render() {
    this.container.innerHTML = `
      <div class="critic-panel-header">
        <div class="panel-title-group">
          <span class="panel-icon">🛡️</span>
          <div>
            <h3 class="panel-title">Critic Review & Findings</h3>
            <span class="panel-subtitle" id="criticSubheader">0 findings detected</span>
          </div>
        </div>

        <div class="panel-controls">
          <div class="critic-category-tabs" id="criticCategoryTabs">
            <button type="button" class="critic-tab-btn is-active" data-cat="ALL">All (<span id="catCountAll">0</span>)</button>
            <button type="button" class="critic-tab-btn" data-cat="Security">Security</button>
            <button type="button" class="critic-tab-btn" data-cat="Architecture">Architecture</button>
            <button type="button" class="critic-tab-btn" data-cat="Quality">Quality</button>
          </div>
        </div>
      </div>

      <div class="critic-findings-list" id="criticFindingsList">
        <div class="critic-empty-state">
          <span class="empty-icon">🛡️</span>
          <p>Waiting for Critic agents to scan codebase and evaluate findings...</p>
        </div>
      </div>
    `;

    this.bindEvents();
  }

  bindEvents() {
    const tabs = this.container.querySelectorAll('.critic-tab-btn');
    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        tabs.forEach(t => t.classList.remove('is-active'));
        tab.classList.add('is-active');
        this.selectedCategory = tab.dataset.cat;
        this.updateFindingsList();
      });
    });
  }

  updateFindingsList() {
    const list = this.container.querySelector('#criticFindingsList');
    const subheader = this.container.querySelector('#criticSubheader');
    const countAll = this.container.querySelector('#catCountAll');
    if (!list) return;

    if (countAll) countAll.textContent = this.findings.length;
    if (subheader) {
      const highCount = this.findings.filter(f => f.severity === 'CRITICAL' || f.severity === 'HIGH').length;
      subheader.textContent = `${this.findings.length} findings • ${highCount} high priority`;
    }

    if (this.findings.length === 0) {
      list.innerHTML = `
        <div class="critic-empty-state">
          <span class="empty-icon">🛡️</span>
          <p>Waiting for Critic agents to scan codebase and evaluate findings...</p>
        </div>
      `;
      return;
    }

    const filtered = this.findings.filter(f => {
      if (this.selectedCategory === 'ALL') return true;
      return (f.category || '').toLowerCase().includes(this.selectedCategory.toLowerCase());
    });

    if (filtered.length === 0) {
      list.innerHTML = `
        <div class="critic-empty-state">
          <p>No findings recorded in this category.</p>
        </div>
      `;
      return;
    }

    // Group by category
    const grouped = {};
    filtered.forEach(f => {
      const cat = f.category || 'General';
      if (!grouped[cat]) grouped[cat] = [];
      grouped[cat].push(f);
    });

    let html = '';
    for (const [catName, items] of Object.entries(grouped)) {
      html += `
        <div class="findings-group">
          <div class="group-header">
            <span class="group-title">${catName}</span>
            <span class="group-count">${items.length}</span>
          </div>
          <div class="group-items">
      `;

      items.forEach(f => {
        const isExpanded = this.expandedFindingIds.has(f.id);
        const isApproved = this.approvedFindingIds.has(f.id);

        let sevClass = 'sev-low';
        if (f.severity === 'CRITICAL') sevClass = 'sev-critical';
        else if (f.severity === 'HIGH') sevClass = 'sev-high';
        else if (f.severity === 'MEDIUM') sevClass = 'sev-medium';

        html += `
          <div class="finding-card ${isExpanded ? 'is-expanded' : ''} ${isApproved ? 'is-approved' : ''}" data-id="${f.id}">
            <div class="finding-card-header" data-id="${f.id}" tabindex="0" role="button" aria-expanded="${isExpanded}">
              <div class="finding-meta-row">
                <span class="finding-sev-pill ${sevClass}">${f.severity}</span>
                <span class="finding-loc">${f.file}${f.line ? `:${f.line}` : ''}</span>
                ${isApproved ? '<span class="approved-badge">✓ Approved</span>' : ''}
              </div>
              <h4 class="finding-title">${f.title}</h4>
              <div class="finding-toggle-chevron">${isExpanded ? '▲' : '▼'}</div>
            </div>

            ${isExpanded ? `
              <div class="finding-details">
                <p class="finding-desc">${f.description}</p>

                ${f.codeSnippet ? `
                  <div class="finding-diff-wrapper">
                    <div class="diff-header">SUGGESTED CODE PATCH</div>
                    <pre class="finding-diff"><code>${this.escapeHtml(f.codeSnippet)}</code></pre>
                  </div>
                ` : ''}

                <div class="finding-remediation">
                  <div class="remediation-title">Recommended Remediation:</div>
                  <div class="remediation-text">${f.remediation}</div>
                </div>

                <div class="finding-actions">
                  ${!isApproved ? `
                    <button type="button" class="btn-approve-fix" data-id="${f.id}">
                      <span>✓</span> Authorize Remediation
                    </button>
                  ` : `
                    <span class="action-status-text">Remediation action registered and queued for execution.</span>
                  `}
                </div>
              </div>
            ` : ''}
          </div>
        `;
      });

      html += `
          </div>
        </div>
      `;
    }

    list.innerHTML = html;

    // Bind expansion clicks
    list.querySelectorAll('.finding-card-header').forEach(header => {
      header.addEventListener('click', () => {
        const id = header.dataset.id;
        if (this.expandedFindingIds.has(id)) {
          this.expandedFindingIds.delete(id);
        } else {
          this.expandedFindingIds.add(id);
        }
        this.updateFindingsList();
      });
    });

    // Bind approval buttons
    list.querySelectorAll('.btn-approve-fix').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = btn.dataset.id;
        this.approveFinding(id);
      });
    });
  }

  async approveFinding(findingId) {
    this.approvedFindingIds.add(findingId);
    this.updateFindingsList();

    // Call real API if backend is listening
    try {
      await fetch('/api/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          option_id: findingId,
          decision: 'APPROVE',
          notes: 'Authorized via Critic Review panel',
        }),
      });
    } catch (e) {
      // Quietly ignore in mock mode
    }
  }

  escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }
}
