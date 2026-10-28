/**
 * Main Application Orchestrator for Repository Analyzer.
 * Governs the 2-state single-page experience:
 * State 1 (Landing) <---> State 2 (Analysis Workspace)
 * Coordinates the State Machine, Stream Service, and UI Components.
 */

import { StateMachine, AppState } from './state.js';
import { AnalysisStreamService } from './stream.js';
import { RepoInput } from './components/RepoInput.js';
import { LiveGraph } from './components/LiveGraph.js';
import { PipelineDAG } from './components/PipelineDAG.js';
import { AgentFeed } from './components/AgentFeed.js';
import { CriticReview } from './components/CriticReview.js';
import { SummaryPanel } from './components/SummaryPanel.js';

class RepositoryAnalyzerApp {
  constructor() {
    this.stateMachine = new StateMachine();
    this.streamService = new AnalysisStreamService();
    this.components = {};
    this.streamMode = 'mock'; // default to standalone demo mock stream

    this.init();
  }

  async init() {
    this.bindDomElements();
    this.bindTheme();
    this.initComponents();
    this.bindStateTransitions();
    this.bindTopBarEvents();
    this.bindCollapsiblePanels();
    this.bindKeyboardShortcuts();

    // Check if backend is alive
    this.checkBackendHealth();
  }

  bindDomElements() {
    this.dom = {
      app: document.getElementById('app'),
      topBar: document.getElementById('topBar'),
      landingView: document.getElementById('landingView'),
      analysisView: document.getElementById('analysisView'),
      errorView: document.getElementById('errorView'),
      progressBar: document.getElementById('analysisProgressBar'),
      activeRepoName: document.getElementById('activeRepoName'),
      activeRepoLink: document.getElementById('activeRepoLink'),
      topBarStatus: document.getElementById('topBarStatus'),
      btnNewAnalysis: document.getElementById('btnNewAnalysis'),
      btnThemeToggle: document.getElementById('btnThemeToggle'),
      streamModeToggle: document.getElementById('streamModeToggle'),
      btnRetryAnalysis: document.getElementById('btnRetryAnalysis'),
      btnErrorReturn: document.getElementById('btnErrorReturn'),
      errorMessageText: document.getElementById('errorMessageText'),
      btnTopBarDownloadRegistry: document.getElementById('btnTopBarDownloadRegistry'),
      topBarDownloadDropdown: document.getElementById('topBarDownloadDropdown'),
      btnTopBarDlJson: document.getElementById('btnTopBarDlJson'),
      btnTopBarDlCsv: document.getElementById('btnTopBarDlCsv'),
      btnTopBarDlCallGraphCsv: document.getElementById('btnTopBarDlCallGraphCsv'),
    };
    this.isBackendAlive = false;
  }

  bindTheme() {
    document.documentElement.setAttribute('data-theme', this.stateMachine.theme);

    if (this.dom.btnThemeToggle) {
      this.dom.btnThemeToggle.addEventListener('click', () => {
        const next = this.stateMachine.toggleTheme();
        this.updateThemeButton(next);
      });
      this.updateThemeButton(this.stateMachine.theme);
    }

    // Listen to system OS theme changes if user hasn't explicitly set one
    if (window.matchMedia) {
      window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', (e) => {
        if (!localStorage.getItem('repo-analyzer-theme')) {
          const theme = e.matches ? 'light' : 'dark';
          this.stateMachine.setTheme(theme);
          this.updateThemeButton(theme);
        }
      });
    }
  }

  updateThemeButton(theme) {
    if (!this.dom.btnThemeToggle) return;
    const icon = this.dom.btnThemeToggle.querySelector('.theme-icon');
    if (icon) {
      icon.textContent = theme === 'dark' ? '☀️' : '🌙';
    }
    this.dom.btnThemeToggle.setAttribute('aria-label', `Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`);
  }

  async checkBackendHealth() {
    try {
      const res = await fetch('/api/status', { method: 'GET', signal: AbortSignal.timeout(1200) });
      if (res.ok) {
        const data = await res.json();
        if (data.status === 'online') {
          this.isBackendAlive = true;
          console.log('Repository Analyzer backend API detected at /api');
        }
      }
    } catch (e) {
      // Backend not running, app seamlessly uses Mock Stream
      this.isBackendAlive = false;
      console.log('Running in standalone frontend mode with mock stream engine.');
    }
  }

  initComponents() {
    // 1. RepoInput
    this.components.repoInput = new RepoInput({
      inputEl: document.getElementById('repoUrlInput'),
      buttonEl: document.getElementById('btnAnalyze'),
      errorEl: document.getElementById('inputError'),
      formEl: document.getElementById('landingForm'),
      chipsContainerEl: document.getElementById('quickChipsContainer'),
      stateMachine: this.stateMachine,
      onSubmit: (validated) => {
        this.handleRepoSubmit(validated);
      },
    });

    // 2. Pipeline DAG
    const dagContainer = document.getElementById('panelPipelineDAG');
    if (dagContainer) {
      this.components.dag = new PipelineDAG(dagContainer);
    }

    // 3. Live Graph
    const graphContainer = document.getElementById('panelLiveGraph');
    if (graphContainer) {
      this.components.graph = new LiveGraph(graphContainer, (format) => {
        this.downloadRegistry(format);
      });
    }

    // 4. Agents Feed
    const agentContainer = document.getElementById('panelAgentFeed');
    if (agentContainer) {
      this.components.agents = new AgentFeed(agentContainer);
    }

    // 5. Critic Review
    const criticContainer = document.getElementById('panelCriticReview');
    if (criticContainer) {
      this.components.critic = new CriticReview(criticContainer);
    }

    // 6. Final Summary
    const summaryContainer = document.getElementById('panelSummary');
    if (summaryContainer) {
      this.components.summary = new SummaryPanel(
        summaryContainer,
        () => this.handleReturnToLanding(),
        (format) => this.downloadRegistry(format)
      );
    }
  }

  bindStateTransitions() {
    this.stateMachine.on('state_changed', ({ from, to, url, repo, owner, error, summary }) => {
      console.log(`[State Transition] ${from} -> ${to}`);

      if (to === AppState.IDLE) {
        this.renderIdleState();
      } else if (to === AppState.ANALYZING) {
        this.renderAnalyzingState(repo, owner, url);
      } else if (to === AppState.COMPLETE) {
        this.renderCompleteState(summary);
      } else if (to === AppState.ERROR) {
        this.renderErrorState(error);
      }
    });
  }

  bindTopBarEvents() {
    if (this.dom.btnNewAnalysis) {
      this.dom.btnNewAnalysis.addEventListener('click', () => {
        this.handleReturnToLanding();
      });
    }

    if (this.dom.streamModeToggle) {
      this.dom.streamModeToggle.addEventListener('click', () => {
        this.streamMode = this.streamMode === 'mock' ? 'live' : 'mock';
        this.dom.streamModeToggle.textContent = this.streamMode === 'mock' ? 'Mode: Demo Stream' : 'Mode: Live API';
        this.dom.streamModeToggle.classList.toggle('is-live', this.streamMode === 'live');
        this.showToast(`Switched to ${this.streamMode === 'mock' ? 'Interactive Demo Stream' : 'Live Backend API'}`);
      });
    }

    if (this.dom.btnRetryAnalysis) {
      this.dom.btnRetryAnalysis.addEventListener('click', () => {
        if (this.stateMachine.repoUrl) {
          const res = this.stateMachine.validateUrl(this.stateMachine.repoUrl);
          this.handleRepoSubmit(res);
        } else {
          this.handleReturnToLanding();
        }
      });
    }

    if (this.dom.btnErrorReturn) {
      this.dom.btnErrorReturn.addEventListener('click', () => {
        this.handleReturnToLanding();
      });
    }

    // Top Bar Download Registry Dropdown
    if (this.dom.btnTopBarDownloadRegistry && this.dom.topBarDownloadDropdown) {
      this.dom.btnTopBarDownloadRegistry.addEventListener('click', (e) => {
        e.stopPropagation();
        const dd = this.dom.topBarDownloadDropdown;
        dd.style.display = dd.style.display === 'none' ? 'block' : 'none';
      });

      document.addEventListener('click', () => {
        if (this.dom.topBarDownloadDropdown) {
          this.dom.topBarDownloadDropdown.style.display = 'none';
        }
      });

      if (this.dom.btnTopBarDlCsv) {
        this.dom.btnTopBarDlCsv.addEventListener('click', (e) => {
          e.stopPropagation();
          this.dom.topBarDownloadDropdown.style.display = 'none';
          this.downloadRegistry('csv');
        });
      }

      if (this.dom.btnTopBarDlCallGraphCsv) {
        this.dom.btnTopBarDlCallGraphCsv.addEventListener('click', (e) => {
          e.stopPropagation();
          this.dom.topBarDownloadDropdown.style.display = 'none';
          this.downloadRegistry('callgraph_csv');
        });
      }

      if (this.dom.btnTopBarDlJson) {
        this.dom.btnTopBarDlJson.addEventListener('click', (e) => {
          e.stopPropagation();
          this.dom.topBarDownloadDropdown.style.display = 'none';
          this.downloadRegistry('json');
        });
      }
    }
  }

  bindCollapsiblePanels() {
    document.querySelectorAll('.panel-card').forEach(panel => {
      const collapseBtn = panel.querySelector('.btn-collapse');
      if (collapseBtn) {
        collapseBtn.addEventListener('click', () => {
          panel.classList.toggle('is-collapsed');
          const isCollapsed = panel.classList.contains('is-collapsed');
          collapseBtn.setAttribute('aria-expanded', !isCollapsed);
          collapseBtn.title = isCollapsed ? 'Expand Panel' : 'Collapse Panel';
        });
      }
    });
  }

  bindKeyboardShortcuts() {
    window.addEventListener('keydown', (e) => {
      // Escape closes any fullscreen panel or clears focus
      if (e.key === 'Escape') {
        const fsPanel = document.querySelector('.panel-card.is-fullscreen');
        if (fsPanel) {
          fsPanel.classList.remove('is-fullscreen');
          if (this.components.graph) {
            this.components.graph.initCanvasSize();
            this.components.graph.draw();
          }
        }
      }
    });
  }

  // =========================================================================
  // STATE RENDERING LOGIC
  // =========================================================================

  renderIdleState() {
    this.streamService.stop();

    // Reset components
    if (this.components.dag) this.components.dag.reset();
    if (this.components.graph) this.components.graph.reset();
    if (this.components.agents) this.components.agents.reset();
    if (this.components.critic) this.components.critic.reset();
    if (this.components.summary) this.components.summary.reset();

    // Animate Landing View In, Top Bar & Workspace Out
    this.dom.app.setAttribute('data-state', 'idle');
    this.dom.topBar.classList.remove('is-visible');
    this.dom.analysisView.classList.remove('is-visible');
    this.dom.errorView.classList.remove('is-visible');
    this.dom.landingView.classList.remove('is-hidden');

    this.setProgress(0);
    this.components.repoInput.clear();
    this.components.repoInput.focus();
  }

  renderAnalyzingState(repo, owner, url) {
    // Populate top bar
    if (this.dom.activeRepoName) {
      this.dom.activeRepoName.textContent = `${owner}/${repo}`;
    }
    if (this.dom.activeRepoLink) {
      this.dom.activeRepoLink.href = url;
    }
    if (this.dom.topBarStatus) {
      this.dom.topBarStatus.textContent = 'Initializing multi-agent pipeline...';
      this.dom.topBarStatus.className = 'top-bar-status is-active';
    }

    // Animate: Landing disappears, Top Bar slides down, Analysis Workspace slides up
    this.dom.landingView.classList.add('is-hidden');
    this.dom.topBar.classList.add('is-visible');
    this.dom.analysisView.classList.add('is-visible');
    this.dom.errorView.classList.remove('is-visible');

    // Canvas size initialization after layout paints
    setTimeout(() => {
      if (this.components.graph) {
        this.components.graph.initCanvasSize();
        this.components.graph.draw();
      }
    }, 120);

    // Start Live Stream
    this.startStreamingPipeline({ repo, owner, url });
  }

  renderCompleteState(summary) {
    if (this.dom.topBarStatus) {
      this.dom.topBarStatus.textContent = `Audit Complete • Health Score ${Math.round(summary.healthScore)}/100`;
      this.dom.topBarStatus.className = 'top-bar-status is-complete';
    }
    this.setProgress(100);

    if (this.components.summary) {
      this.components.summary.setSummary(summary);
    }
  }

  renderErrorState(errorMessage) {
    this.streamService.stop();
    this.dom.analysisView.classList.remove('is-visible');
    this.dom.errorView.classList.add('is-visible');
    if (this.dom.errorMessageText) {
      this.dom.errorMessageText.textContent = errorMessage || 'An unexpected error occurred during repository analysis.';
    }
    if (this.dom.topBarStatus) {
      this.dom.topBarStatus.textContent = 'Analysis Failed';
      this.dom.topBarStatus.className = 'top-bar-status is-error';
    }
  }

  // =========================================================================
  // PIPELINE STREAM DISPATCH
  // =========================================================================

  handleRepoSubmit(validated) {
    const success = this.stateMachine.startAnalysis(validated.canonicalUrl);
    if (!success) {
      console.warn('Could not initiate analysis for URL:', validated);
    }
  }

  handleReturnToLanding() {
    this.streamService.stop();
    this.stateMachine.resetToLanding();
  }

  startStreamingPipeline(repoInfo) {
    this.setProgress(5);

    this.streamService.start(
      repoInfo,
      {
        onPipelineStage: (stage) => {
          if (this.components.dag) this.components.dag.updateStage(stage);
          if (stage.status === 'running' && this.dom.topBarStatus) {
            this.dom.topBarStatus.textContent = `Stage ${stage.index || ''} of ${stage.total || 8}: ${stage.title}`;
          }
        },
        onGraphNode: (node) => {
          if (this.components.graph) this.components.graph.addNode(node);
        },
        onGraphEdge: (edge) => {
          if (this.components.graph) this.components.graph.addEdge(edge);
        },
        onAgentUpdate: (agentUpdate) => {
          if (this.components.agents) this.components.agents.updateAgent(agentUpdate);
        },
        onCriticFinding: (finding) => {
          if (this.components.critic) this.components.critic.addFinding(finding);
        },
        onProgress: ({ percent, stageName }) => {
          this.setProgress(percent);
          if (stageName && this.dom.topBarStatus) {
            this.dom.topBarStatus.textContent = stageName;
          }
        },
        onSummary: (summary) => {
          this.stateMachine.completeAnalysis(summary);
        },
        onError: (err) => {
          this.stateMachine.failAnalysis(err.message || 'Analysis pipeline execution error');
        },
        onNotice: (msg) => {
          this.showToast(msg);
        },
        onComplete: () => {
          console.log('Stream analysis pipeline completed successfully.');
        },
      },
      this.streamMode
    );
  }

  downloadRegistry(format = 'json') {
    const repoName = this.stateMachine.repoName || 'repository';

    if (this.streamMode === 'live' || this.isBackendAlive) {
      window.location.href = `/api/registry/download?format=${format}`;
      this.showToast(`Downloading Codebase Registry (.${format.toUpperCase()})...`);
      return;
    }

    // Standalone client-side extraction export from the active code graph
    const nodes = (this.components.graph && this.components.graph.nodes) || [];
    const edges = (this.components.graph && this.components.graph.edges) || [];

    if (nodes.length === 0) {
      this.showToast('No code entities discovered yet to extract.');
      return;
    }

    // Pre-aggregate relations per node
    const callsMap = new Map();
    const calledByMap = new Map();
    const queriesMap = new Map();
    const routesToMap = new Map();
    const containerMap = new Map();

    edges.forEach(e => {
      const sId = e.source.id || e.source;
      const tId = e.target.id || e.target;
      const sNode = nodes.find(n => n.id === sId);
      const tNode = nodes.find(n => n.id === tId);
      const sName = sNode ? (sNode.label || sNode.name) : sId;
      const tName = tNode ? (tNode.label || tNode.name) : tId;
      const rel = e.type || 'connects';

      if (rel === 'calls') {
        if (!callsMap.has(sId)) callsMap.set(sId, []);
        callsMap.get(sId).push(tName);
        if (!calledByMap.has(tId)) calledByMap.set(tId, []);
        calledByMap.get(tId).push(sName);
      } else if (rel === 'routes_to') {
        if (!routesToMap.has(sId)) routesToMap.set(sId, []);
        routesToMap.get(sId).push(tName);
        if (!calledByMap.has(tId)) calledByMap.set(tId, []);
        calledByMap.get(tId).push(sName);
      } else if (rel === 'queries') {
        if (!queriesMap.has(sId)) queriesMap.set(sId, []);
        queriesMap.get(sId).push(tName);
      } else if (rel === 'contains' || rel === 'defines') {
        containerMap.set(tId, sName);
      }
    });

    // FORMAT 1: Dedicated Call Graph Matrix CSV
    if (format === 'callgraph_csv' || format === 'relations_csv') {
      const headers = [
        'caller_id', 'caller_name', 'caller_type', 'caller_path',
        'callee_id', 'callee_name', 'callee_type', 'callee_path',
        'relationship', 'line_number'
      ];
      const rows = edges.map(e => {
        const sId = e.source.id || e.source;
        const tId = e.target.id || e.target;
        const sNode = nodes.find(n => n.id === sId) || {};
        const tNode = nodes.find(n => n.id === tId) || {};
        return [
          `"${sId}"`,
          `"${(sNode.label || sNode.name || sId).replace(/"/g, '""')}"`,
          `"${sNode.type || ''}"`,
          `"${sNode.path || ''}"`,
          `"${tId}"`,
          `"${(tNode.label || tNode.name || tId).replace(/"/g, '""')}"`,
          `"${tNode.type || ''}"`,
          `"${tNode.path || ''}"`,
          `"${e.type || 'relates'}"`,
          `"${sNode.line || ''}"`
        ];
      });
      const csvContent = [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `callgraph_${repoName}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      this.showToast(`Extracted ${edges.length} call graph connections to callgraph_${repoName}.csv`);
      return;
    }

    // FORMAT 2: Enriched Entity Registry CSV with who-calls-who columns
    if (format === 'csv' || format === 'entities_csv') {
      const headers = [
        'id', 'name', 'type', 'path', 'line',
        'calls', 'called_by', 'routes_to', 'queries_tables', 'parent_container'
      ];
      const rows = nodes.map(n => [
        `"${n.id || ''}"`,
        `"${(n.label || n.name || '').replace(/"/g, '""')}"`,
        `"${n.type || ''}"`,
        `"${n.path || ''}"`,
        `"${n.line || ''}"`,
        `"${(callsMap.get(n.id) || []).join('; ')}"`,
        `"${(calledByMap.get(n.id) || []).join('; ')}"`,
        `"${(routesToMap.get(n.id) || []).join('; ')}"`,
        `"${(queriesMap.get(n.id) || []).join('; ')}"`,
        `"${containerMap.get(n.id) || ''}"`
      ]);
      const csvContent = [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `registry_functions_calls_${repoName}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      this.showToast(`Extracted ${nodes.length} functions & entities with call relations to registry_functions_calls_${repoName}.csv`);
      return;
    }

    // FORMAT 3: Enriched JSON Payload
    const payload = {
      repository: repoName,
      extracted_at: new Date().toISOString(),
      total_entities: nodes.length,
      total_relations: edges.length,
      entities: nodes.map(n => ({
        id: n.id,
        name: n.label || n.name,
        type: n.type,
        path: n.path,
        line: n.line,
        layer: n.layer,
        relations: {
          calls: callsMap.get(n.id) || [],
          called_by: calledByMap.get(n.id) || [],
          routes_to: routesToMap.get(n.id) || [],
          queries_tables: queriesMap.get(n.id) || [],
          parent_container: containerMap.get(n.id) || '',
        },
        degree: edges.filter(e => (e.source.id || e.source) === n.id || (e.target.id || e.target) === n.id).length,
      })),
      relationships: edges.map(e => ({
        source: e.source.id || e.source,
        target: e.target.id || e.target,
        type: e.type || 'connects'
      })),
      call_graph: edges.filter(e => (e.type || '') === 'calls').map(e => ({
        caller: e.source.id || e.source,
        callee: e.target.id || e.target,
      }))
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `registry_${repoName}.json`;
    a.click();
    URL.revokeObjectURL(url);
    this.showToast(`Extracted ${nodes.length} code entities & relations to registry_${repoName}.json`);
  }

  setProgress(percent) {
    if (this.dom.progressBar) {
      this.dom.progressBar.style.width = `${percent}%`;
      this.dom.progressBar.setAttribute('aria-valuenow', percent);
      if (percent >= 100) {
        setTimeout(() => {
          if (this.stateMachine.state === AppState.COMPLETE) {
            this.dom.progressBar.style.opacity = '0';
          }
        }, 800);
      } else {
        this.dom.progressBar.style.opacity = '1';
      }
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
    }, 3200);
  }
}

// Global bootstrap on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  window.app = new RepositoryAnalyzerApp();
});
