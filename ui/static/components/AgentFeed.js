/**
 * Agents Panel & Streaming Trace Feed Component.
 * Displays live status for each specialized autonomous agent:
 * Name, Layer, Current Task, Status (idle/active/done), Elapsed Time counter,
 * and a real-time auto-scrolling terminal log stream.
 */

export class AgentFeed {
  constructor(containerEl) {
    this.container = containerEl;
    this.agents = [
      { id: 'orchestrator', name: 'Orchestrator', layer: 'control', task: 'Standing by', status: 'idle', elapsed: 0 },
      { id: 'structure_mapper', name: 'StructureMapper', layer: 'graph', task: 'Standing by', status: 'idle', elapsed: 0 },
      { id: 'relationship_linker', name: 'RelationshipLinker', layer: 'graph', task: 'Standing by', status: 'idle', elapsed: 0 },
      { id: 'data_service_mapper', name: 'DataServiceMapper', layer: 'graph', task: 'Standing by', status: 'idle', elapsed: 0 },
      { id: 'impact_analyzer', name: 'ImpactAnalyzer', layer: 'understanding', task: 'Standing by', status: 'idle', elapsed: 0 },
      { id: 'security_agent', name: 'SecurityAgent', layer: 'safety', task: 'Standing by', status: 'idle', elapsed: 0 },
      { id: 'code_quality_agent', name: 'CodeQualityAgent', layer: 'quality', task: 'Standing by', status: 'idle', elapsed: 0 },
      { id: 'critic_aggregator', name: 'CriticAggregator', layer: 'control', task: 'Standing by', status: 'idle', elapsed: 0 },
    ];

    this.logs = [];
    this.selectedLogLevel = 'ALL';
    this.autoScroll = true;
    this.timerId = null;

    this.render();
    this.startElapsedTimer();
  }

  reset() {
    this.agents.forEach(a => {
      a.task = 'Standing by';
      a.status = 'idle';
      a.elapsed = 0;
    });
    this.logs = [];
    this.updateAgentsList();
    this.updateLogStream();
  }

  destroy() {
    if (this.timerId) {
      clearInterval(this.timerId);
      this.timerId = null;
    }
  }

  startElapsedTimer() {
    if (this.timerId) clearInterval(this.timerId);
    this.timerId = setInterval(() => {
      let hasActive = false;
      this.agents.forEach(a => {
        if (a.status === 'active') {
          a.elapsed += 0.1;
          hasActive = true;
        }
      });
      if (hasActive) {
        this.updateAgentTimers();
      }
    }, 100);
  }

  updateAgent(update) {
    let agent = this.agents.find(a => a.id === update.id || a.name.toLowerCase() === (update.name || '').toLowerCase());
    if (!agent) {
      agent = {
        id: update.id || update.name.toLowerCase().replace(/\s+/g, '_'),
        name: update.name || update.id,
        layer: update.layer || 'core',
        task: update.task || 'Processing...',
        status: update.status || 'active',
        elapsed: 0,
      };
      this.agents.push(agent);
    } else {
      if (update.task) agent.task = update.task;
      if (update.status) agent.status = update.status;
      if (update.layer) agent.layer = update.layer;
      if (update.elapsedSec !== undefined) agent.elapsed = parseFloat(update.elapsedSec);
    }

    if (update.logLine) {
      this.addLog({
        agent: agent.name,
        level: update.level || 'INFO',
        message: update.logLine,
        timestamp: new Date().toLocaleTimeString(),
      });
    }

    this.updateAgentsList();
  }

  addLog(logEntry) {
    this.logs.push(logEntry);
    if (this.logs.length > 300) this.logs.shift();
    this.updateLogStream();
  }

  render() {
    this.container.innerHTML = `
      <div class="agent-panel-header">
        <div class="panel-title-group">
          <span class="panel-icon">🤖</span>
          <div>
            <h3 class="panel-title">Agents Panel & Traces</h3>
            <span class="panel-subtitle">Live Autonomous Agent Feed</span>
          </div>
        </div>

        <div class="panel-controls">
          <div class="log-level-filters" id="logLevelFilters">
            <button type="button" class="log-filter-btn is-active" data-level="ALL">All</button>
            <button type="button" class="log-filter-btn" data-level="INFO">Info</button>
            <button type="button" class="log-filter-btn" data-level="WARN">Warn</button>
            <button type="button" class="log-filter-btn" data-level="ERROR">Error</button>
          </div>
        </div>
      </div>

      <!-- Agent Cards Grid -->
      <div class="agents-grid" id="agentsGrid"></div>

      <!-- Live Terminal Stream -->
      <div class="agent-terminal-wrapper">
        <div class="terminal-bar">
          <div class="terminal-dots">
            <span class="dot dot-red"></span>
            <span class="dot dot-yellow"></span>
            <span class="dot dot-green"></span>
          </div>
          <span class="terminal-title">AGENT EXECUTION LOG STREAM</span>
          <span class="terminal-badge" id="terminalCount">0 lines</span>
        </div>
        <div class="terminal-body" id="terminalBody" tabindex="0" role="region" aria-label="Agent execution log stream"></div>
      </div>
    `;

    this.bindEvents();
    this.updateAgentsList();
  }

  bindEvents() {
    const filterBtns = this.container.querySelectorAll('.log-filter-btn');
    filterBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        filterBtns.forEach(b => b.classList.remove('is-active'));
        btn.classList.add('is-active');
        this.selectedLogLevel = btn.dataset.level;
        this.updateLogStream();
      });
    });

    const termBody = this.container.querySelector('#terminalBody');
    if (termBody) {
      termBody.addEventListener('scroll', () => {
        const atBottom = termBody.scrollHeight - termBody.scrollTop - termBody.clientHeight < 30;
        this.autoScroll = atBottom;
      });
    }
  }

  updateAgentsList() {
    const grid = this.container.querySelector('#agentsGrid');
    if (!grid) return;

    let html = '';
    this.agents.forEach(agent => {
      const isActive = agent.status === 'active';
      const isDone = agent.status === 'done';

      let statusBadgeClass = 'status-idle';
      let statusText = 'Idle';
      if (isActive) {
        statusBadgeClass = 'status-active';
        statusText = 'Active';
      } else if (isDone) {
        statusBadgeClass = 'status-done';
        statusText = 'Finished';
      }

      html += `
        <div class="agent-card ${isActive ? 'is-active' : ''}" id="agentCard-${agent.id}">
          <div class="agent-card-top">
            <div class="agent-name-group">
              <span class="agent-avatar ${agent.layer}">${agent.name.charAt(0)}</span>
              <div>
                <span class="agent-name">${agent.name}</span>
                <span class="agent-layer-tag ${agent.layer}">${agent.layer}</span>
              </div>
            </div>
            <div class="agent-status-col">
              <span class="agent-status-pill ${statusBadgeClass}">
                ${isActive ? '<span class="status-pulse-dot"></span>' : ''}
                ${statusText}
              </span>
              <span class="agent-elapsed-time" id="agentTimer-${agent.id}">${agent.elapsed.toFixed(1)}s</span>
            </div>
          </div>
          <div class="agent-task-text">${agent.task}</div>
        </div>
      `;
    });

    grid.innerHTML = html;
  }

  updateAgentTimers() {
    this.agents.forEach(agent => {
      const el = this.container.querySelector(`#agentTimer-${agent.id}`);
      if (el) {
        el.textContent = `${agent.elapsed.toFixed(1)}s`;
      }
    });
  }

  updateLogStream() {
    const termBody = this.container.querySelector('#terminalBody');
    const termCount = this.container.querySelector('#terminalCount');
    if (!termBody) return;

    const filtered = this.logs.filter(log => {
      if (this.selectedLogLevel === 'ALL') return true;
      return log.level === this.selectedLogLevel;
    });

    if (termCount) {
      termCount.textContent = `${filtered.length} entries`;
    }

    if (filtered.length === 0) {
      termBody.innerHTML = `<div class="terminal-empty">Waiting for streaming agent log events...</div>`;
      return;
    }

    let linesHtml = '';
    filtered.forEach(log => {
      let levelClass = 'lvl-info';
      if (log.level === 'WARN') levelClass = 'lvl-warn';
      if (log.level === 'ERROR') levelClass = 'lvl-error';

      linesHtml += `
        <div class="terminal-line">
          <span class="term-time">${log.timestamp}</span>
          <span class="term-level ${levelClass}">${log.level}</span>
          <span class="term-agent">[${log.agent}]</span>
          <span class="term-msg">${this.escapeHtml(log.message)}</span>
        </div>
      `;
    });

    termBody.innerHTML = linesHtml;

    if (this.autoScroll) {
      termBody.scrollTop = termBody.scrollHeight;
    }
  }

  escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
}
