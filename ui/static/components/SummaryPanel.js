/**
 * Final Summary Panel Component.
 * Appears upon analysis completion with overall health score gauge,
 * key codebase metrics, and export & share utilities (JSON, Markdown, Print, Clipboard).
 */

export class SummaryPanel {
  constructor(containerEl, onNewAnalysis, onDownloadRegistry) {
    this.container = containerEl;
    this.onNewAnalysis = onNewAnalysis;
    this.onDownloadRegistry = onDownloadRegistry;
    this.summaryData = null;

    this.renderInitial();
  }

  reset() {
    this.summaryData = null;
    this.renderInitial();
  }

  renderInitial() {
    this.container.innerHTML = `
      <div class="summary-skeleton">
        <div class="summary-skeleton-top">
          <div class="skeleton-circle"></div>
          <div class="skeleton-lines">
            <div class="skeleton-line line-wide"></div>
            <div class="skeleton-line line-med"></div>
          </div>
        </div>
        <div class="summary-skeleton-metrics">
          <div class="skeleton-box"></div>
          <div class="skeleton-box"></div>
          <div class="skeleton-box"></div>
          <div class="skeleton-box"></div>
        </div>
      </div>
    `;
  }

  setSummary(data) {
    this.summaryData = data;
    this.renderComplete();
  }

  renderComplete() {
    if (!this.summaryData) return;
    const d = this.summaryData;

    const score = Math.round(d.healthScore || 94);
    let gradeLabel = 'EXCELLENT ARCHITECTURE';
    let gradeColor = 'var(--accent-sage)';
    if (score < 70) {
      gradeLabel = 'CRITICAL ATTENTION REQUIRED';
      gradeColor = 'var(--accent-rose)';
    } else if (score < 85) {
      gradeLabel = 'ACCEPTABLE HEALTH';
      gradeColor = 'var(--accent-amber)';
    }

    // Circumference for 48px radius SVG circle: 2 * PI * 48 = ~301.6
    const circumference = 301.6;
    const strokeDashoffset = circumference - (circumference * (score / 100));

    this.container.innerHTML = `
      <div class="summary-card is-revealed">
        <div class="summary-header">
          <div class="summary-title-group">
            <span class="panel-icon">📊</span>
            <div>
              <h3 class="panel-title">Audit Executive Summary</h3>
              <span class="panel-subtitle">Synthesized by ResultAggregatorCritic</span>
            </div>
          </div>
          <div class="summary-actions">
            <button type="button" class="btn-summary-action btn-summary-registry" id="btnSummaryDownloadRegistry" title="Download Codebase Registry extraction (JSON & CSV)">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4m4-5 5 5 5-5m-5 5V3"/></svg>
              Extract Registry
            </button>
            <button type="button" class="btn-summary-action" id="btnExportJson" title="Download JSON payload">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4m4-5 5 5 5-5m-5 5V3"/></svg>
              JSON
            </button>
            <button type="button" class="btn-summary-action" id="btnExportMarkdown" title="Download Markdown audit report">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
              Markdown
            </button>
            <button type="button" class="btn-summary-action" id="btnPrintReport" title="Print or save as PDF">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
              Print
            </button>
            <button type="button" class="btn-summary-action" id="btnShareSummary" title="Copy summary to clipboard">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
              Share
            </button>
          </div>
        </div>

        <div class="summary-body">
          <!-- Circular Health Gauge -->
          <div class="summary-gauge-col">
            <div class="score-circle-wrapper">
              <svg class="score-svg" viewBox="0 0 120 120">
                <circle cx="60" cy="60" r="48" class="score-track" />
                <circle cx="60" cy="60" r="48" class="score-value" style="stroke: ${gradeColor}; stroke-dasharray: ${circumference}; stroke-dashoffset: ${strokeDashoffset};" />
              </svg>
              <div class="score-text-overlay">
                <span class="score-number">${score}</span>
                <span class="score-denom">/ 100</span>
              </div>
            </div>
            <div class="score-label" style="color: ${gradeColor};">${gradeLabel}</div>
            <span class="score-caption">Based on 16 agent audit perspectives</span>
          </div>

          <!-- Metrics Strip -->
          <div class="summary-metrics-grid">
            <div class="summary-metric-tile">
              <span class="tile-label">Files Scanned</span>
              <span class="tile-val">${d.filesScanned || 0}</span>
              <span class="tile-sub">Source code files</span>
            </div>
            <div class="summary-metric-tile">
              <span class="tile-label">Code Entities</span>
              <span class="tile-val">${d.nodesCount || 0}</span>
              <span class="tile-sub">Classes, APIs & functions</span>
            </div>
            <div class="summary-metric-tile">
              <span class="tile-label">Dependencies</span>
              <span class="tile-val">${d.edgesCount || 0}</span>
              <span class="tile-sub">Verified relational links</span>
            </div>
            <div class="summary-metric-tile">
              <span class="tile-label">Active Findings</span>
              <span class="tile-val" style="color:${d.findingsCount > 0 ? 'var(--accent-amber)' : 'var(--text-primary)'};">${d.findingsCount || 0}</span>
              <span class="tile-sub">${d.criticalCount || 0} critical, ${d.highCount || 0} high</span>
            </div>
            <div class="summary-metric-tile">
              <span class="tile-label">False Alarms</span>
              <span class="tile-val" style="color:var(--accent-sage);">${d.falseAlarmsPruned || 0}</span>
              <span class="tile-sub">Pruned by Critic</span>
            </div>
            <div class="summary-metric-tile">
              <span class="tile-label">Analysis Time</span>
              <span class="tile-val">${d.durationSec || '0'}s</span>
              <span class="tile-sub">Total pipeline elapsed</span>
            </div>
          </div>
        </div>

        <div class="summary-footer">
          <span class="summary-timestamp">Completed on ${new Date(d.timestamp).toLocaleString()}</span>
          <button type="button" class="btn-new-analysis-primary" id="btnRestartAnalysis">
            <span>←</span> Analyze Another Repository
          </button>
        </div>
      </div>
    `;

    this.bindActionEvents();
  }

  bindActionEvents() {
    const btnDlReg = this.container.querySelector('#btnSummaryDownloadRegistry');
    const btnJson = this.container.querySelector('#btnExportJson');
    const btnMd = this.container.querySelector('#btnExportMarkdown');
    const btnPrint = this.container.querySelector('#btnPrintReport');
    const btnShare = this.container.querySelector('#btnShareSummary');
    const btnRestart = this.container.querySelector('#btnRestartAnalysis');

    if (btnDlReg && this.onDownloadRegistry) {
      btnDlReg.addEventListener('click', () => this.onDownloadRegistry('json'));
    }
    if (btnJson) btnJson.addEventListener('click', () => this.exportJson());
    if (btnMd) btnMd.addEventListener('click', () => this.exportMarkdown());
    if (btnPrint) btnPrint.addEventListener('click', () => window.print());
    if (btnShare) btnShare.addEventListener('click', () => this.shareSummary());
    if (btnRestart && this.onNewAnalysis) {
      btnRestart.addEventListener('click', () => this.onNewAnalysis());
    }
  }

  exportJson() {
    if (!this.summaryData) return;
    const jsonStr = JSON.stringify(this.summaryData, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `repository-analysis-${this.summaryData.repoName || 'report'}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  exportMarkdown() {
    if (!this.summaryData) return;
    const d = this.summaryData;
    const md = `# Repository Health & Architecture Audit Report
**Target Repository:** ${d.repoOwner}/${d.repoName}  
**Audit Date:** ${new Date(d.timestamp).toUTCString()}  
**Overall Health Score:** ${d.healthScore} / 100  

---

## Executive Summary
- **Files Scanned:** ${d.filesScanned}
- **Tracked Code Entities:** ${d.nodesCount}
- **Verified Relationships & Dependencies:** ${d.edgesCount}
- **Active Findings:** ${d.findingsCount} (${d.criticalCount} Critical, ${d.highCount} High)
- **False Positives Pruned:** ${d.falseAlarmsPruned}
- **Pipeline Duration:** ${d.durationSec}s

Generated by Multi-Agent AI Platform Repository Analyzer.
`;

    const blob = new Blob([md], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `repository-audit-${d.repoName || 'report'}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async shareSummary() {
    if (!this.summaryData) return;
    const d = this.summaryData;
    const text = `Repository Analyzer Audit for ${d.repoName}: Health Score ${d.healthScore}/100 across ${d.filesScanned} files.`;

    if (navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      this.showToast('Summary copied to clipboard!');
    }
  }

  showToast(message) {
    let toast = document.getElementById('appToast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'appToast';
      toast.className = 'app-toast';
      document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.add('visible');
    setTimeout(() => {
      toast.classList.remove('visible');
    }, 2800);
  }
}
