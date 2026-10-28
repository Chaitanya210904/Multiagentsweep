/**
 * Pipeline DAG (Directed Acyclic Graph) Component.
 * Visualizes the 8 multi-agent orchestration pipeline stages.
 * Each node displays dynamic status (queued, running, done, failed),
 * elapsed stage duration, and directed edges that light up and animate
 * with flowing pulses as execution advances.
 */

export class PipelineDAG {
  constructor(containerEl) {
    this.container = containerEl;
    this.stages = [
      { id: 'clone', label: '1. Ingestion', subtitle: 'Repo Git Clone & Tree', icon: '📥', status: 'queued', duration: null },
      { id: 'structure_mapper', label: '2. AST Mapping', subtitle: 'Classes, Methods & Files', icon: '🌲', status: 'queued', duration: null },
      { id: 'relationship_linker', label: '3. Call Linking', subtitle: 'Imports, Calls & Tests', icon: '🔗', status: 'queued', duration: null },
      { id: 'data_service_mapper', label: '4. Service & Data', subtitle: 'APIs, Queries & Models', icon: '⚡', status: 'queued', duration: null },
      { id: 'impact_analyzer', label: '5. Architecture', subtitle: 'Cohesion & Blast Radius', icon: '📐', status: 'queued', duration: null },
      { id: 'quality_security', label: '6. Security & SAST', subtitle: 'Taint & Secret Scans', icon: '🛡️', status: 'queued', duration: null },
      { id: 'critic_aggregator', label: '7. Critic Review', subtitle: 'Reconciliation & Pruning', icon: '⚖️', status: 'queued', duration: null },
      { id: 'report_generator', label: '8. Action Plan', subtitle: 'Final Synthesis & Report', icon: '📊', status: 'queued', duration: null },
    ];

    this.edges = [
      { from: 'clone', to: 'structure_mapper' },
      { from: 'structure_mapper', to: 'relationship_linker' },
      { from: 'structure_mapper', to: 'data_service_mapper' },
      { from: 'relationship_linker', to: 'impact_analyzer' },
      { from: 'data_service_mapper', to: 'impact_analyzer' },
      { from: 'impact_analyzer', to: 'quality_security' },
      { from: 'quality_security', to: 'critic_aggregator' },
      { from: 'critic_aggregator', to: 'report_generator' },
    ];

    this.selectedStage = null;
    this.render();
  }

  reset() {
    this.stages.forEach(s => {
      s.status = 'queued';
      s.duration = null;
    });
    this.selectedStage = null;
    this.render();
  }

  updateStage(stageUpdate) {
    const stage = this.stages.find(s => s.id === stageUpdate.id);
    if (!stage) return;

    if (stageUpdate.status) stage.status = stageUpdate.status;
    if (stageUpdate.duration) stage.duration = stageUpdate.duration;
    if (stageUpdate.message) stage.message = stageUpdate.message;

    this.updateDom();
  }

  render() {
    this.container.innerHTML = `
      <div class="dag-header">
        <div class="panel-title-group">
          <span class="panel-icon">⚡</span>
          <div>
            <h3 class="panel-title">Pipeline DAG</h3>
            <span class="panel-subtitle">Multi-Agent Orchestration Flow</span>
          </div>
        </div>
        <div class="panel-controls">
          <span class="dag-stage-counter" id="dagProgressBadge">Ready</span>
          <button type="button" class="panel-ctrl-btn btn-fullscreen" title="Toggle Fullscreen" aria-label="Toggle Fullscreen">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>
          </button>
        </div>
      </div>

      <div class="dag-viewport" id="dagViewport">
        <svg class="dag-svg" id="dagSvg" viewBox="0 0 840 260" preserveAspectRatio="xMidYMid meet">
          <defs>
            <linearGradient id="edgeGradActive" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stop-color="var(--accent-sage)" stop-opacity="0.3" />
              <stop offset="50%" stop-color="var(--accent-indigo)" stop-opacity="1" />
              <stop offset="100%" stop-color="var(--accent-sage)" stop-opacity="0.8" />
            </linearGradient>
            <filter id="glowFilter" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
            <marker id="arrowInactive" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 1 L 9 5 L 0 9 z" fill="var(--border-subtle)" />
            </marker>
            <marker id="arrowActive" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 1 L 9 5 L 0 9 z" fill="var(--accent-indigo)" />
            </marker>
          </defs>
          <g class="dag-edges-group" id="dagEdgesGroup"></g>
          <g class="dag-nodes-group" id="dagNodesGroup"></g>
        </svg>

        <div class="dag-stage-tooltip" id="dagTooltip" style="display:none;"></div>
      </div>
    `;

    this.bindControls();
    this.updateDom();
  }

  bindControls() {
    const fsBtn = this.container.querySelector('.btn-fullscreen');
    if (fsBtn) {
      fsBtn.addEventListener('click', () => {
        this.container.closest('.panel-card').classList.toggle('is-fullscreen');
      });
    }
  }

  // Pre-calculated topological layout coordinates for clean responsive rendering
  getNodePositions() {
    return {
      clone: { x: 55, y: 130 },
      structure_mapper: { x: 165, y: 130 },
      relationship_linker: { x: 285, y: 75 },
      data_service_mapper: { x: 285, y: 185 },
      impact_analyzer: { x: 415, y: 130 },
      quality_security: { x: 545, y: 130 },
      critic_aggregator: { x: 675, y: 130 },
      report_generator: { x: 790, y: 130 },
    };
  }

  updateDom() {
    const edgesGroup = this.container.querySelector('#dagEdgesGroup');
    const nodesGroup = this.container.querySelector('#dagNodesGroup');
    const badge = this.container.querySelector('#dagProgressBadge');
    if (!edgesGroup || !nodesGroup) return;

    const positions = this.getNodePositions();
    const stageMap = new Map(this.stages.map(s => [s.id, s]));

    // Update progress badge
    const doneCount = this.stages.filter(s => s.status === 'done').length;
    const runningStage = this.stages.find(s => s.status === 'running');
    if (badge) {
      if (doneCount === this.stages.length) {
        badge.textContent = 'All Stages Completed';
        badge.className = 'dag-stage-counter is-complete';
      } else if (runningStage) {
        badge.textContent = `Running: ${runningStage.label}`;
        badge.className = 'dag-stage-counter is-running';
      } else {
        badge.textContent = `${doneCount} of ${this.stages.length} Completed`;
        badge.className = 'dag-stage-counter';
      }
    }

    // Render Edges
    let edgesHtml = '';
    this.edges.forEach(edge => {
      const p1 = positions[edge.from];
      const p2 = positions[edge.to];
      const s1 = stageMap.get(edge.from);
      const s2 = stageMap.get(edge.to);

      const isActive = s1.status === 'done' && (s2.status === 'running' || s2.status === 'done');
      const isFlowing = s1.status === 'done' && s2.status === 'running';

      // Cubic bezier curve
      const dx = (p2.x - p1.x) * 0.5;
      const pathD = `M ${p1.x} ${p1.y} C ${p1.x + dx} ${p1.y}, ${p2.x - dx} ${p2.y}, ${p2.x} ${p2.y}`;

      const edgeClass = `dag-edge ${isActive ? 'is-active' : ''} ${isFlowing ? 'is-flowing' : ''}`;
      const marker = isActive ? 'url(#arrowActive)' : 'url(#arrowInactive)';

      edgesHtml += `
        <path d="${pathD}" class="${edgeClass}" marker-end="${marker}" />
      `;
    });
    edgesGroup.innerHTML = edgesHtml;

    // Render Nodes
    let nodesHtml = '';
    this.stages.forEach(stage => {
      const pos = positions[stage.id];
      const isRunning = stage.status === 'running';
      const isDone = stage.status === 'done';
      const isFailed = stage.status === 'failed';

      let statusColor = 'var(--text-muted)';
      let statusBg = 'var(--bg-surface-elevated)';
      let statusText = 'Queued';

      if (isRunning) {
        statusColor = 'var(--accent-indigo)';
        statusBg = 'var(--accent-indigo-subtle)';
        statusText = 'Running';
      } else if (isDone) {
        statusColor = 'var(--accent-sage)';
        statusBg = 'var(--accent-sage-subtle)';
        statusText = stage.duration || 'Done';
      } else if (isFailed) {
        statusColor = 'var(--accent-rose)';
        statusBg = 'var(--accent-rose-subtle)';
        statusText = 'Failed';
      }

      nodesHtml += `
        <g class="dag-node ${stage.status}" data-id="${stage.id}" transform="translate(${pos.x}, ${pos.y})" tabindex="0" role="button" aria-label="${stage.label}: ${statusText}">
          ${isRunning ? `<circle r="36" class="node-halo" />` : ''}
          <circle r="26" class="node-bg" />
          <circle r="26" class="node-border" />
          <text y="-2" class="node-icon" text-anchor="middle" dominant-baseline="middle">${stage.icon}</text>
          
          <!-- Stage Title -->
          <text y="42" class="node-title" text-anchor="middle">${stage.label}</text>
          
          <!-- Status Pill -->
          <g transform="translate(0, 56)">
            <rect x="-34" y="-7" width="68" height="15" rx="7.5" fill="${statusBg}" stroke="${statusColor}" stroke-opacity="0.3" />
            <text y="2.5" class="node-status-badge" fill="${statusColor}" text-anchor="middle">${statusText}</text>
          </g>
        </g>
      `;
    });
    nodesGroup.innerHTML = nodesHtml;

    // Bind Node hover/click tooltips
    nodesGroup.querySelectorAll('.dag-node').forEach(nodeEl => {
      nodeEl.addEventListener('mouseenter', (e) => this.showTooltip(e, nodeEl.dataset.id));
      nodeEl.addEventListener('mouseleave', () => this.hideTooltip());
      nodeEl.addEventListener('click', (e) => this.showTooltip(e, nodeEl.dataset.id));
    });
  }

  showTooltip(e, stageId) {
    const tooltip = this.container.querySelector('#dagTooltip');
    const stage = this.stages.find(s => s.id === stageId);
    if (!tooltip || !stage) return;

    tooltip.innerHTML = `
      <div class="tooltip-header">
        <span class="tooltip-icon">${stage.icon}</span>
        <div>
          <div class="tooltip-title">${stage.label}</div>
          <div class="tooltip-subtitle">${stage.subtitle}</div>
        </div>
      </div>
      <div class="tooltip-meta">
        <div class="meta-row">
          <span>Status:</span>
          <strong style="text-transform: capitalize; color: ${stage.status === 'done' ? 'var(--accent-sage)' : (stage.status === 'running' ? 'var(--accent-indigo)' : 'var(--text-muted)')};">${stage.status}</strong>
        </div>
        ${stage.duration ? `<div class="meta-row"><span>Duration:</span><strong>${stage.duration}</strong></div>` : ''}
        ${stage.message ? `<div class="meta-desc">${stage.message}</div>` : ''}
      </div>
    `;

    tooltip.style.display = 'block';
  }

  hideTooltip() {
    const tooltip = this.container.querySelector('#dagTooltip');
    if (tooltip) tooltip.style.display = 'none';
  }
}
