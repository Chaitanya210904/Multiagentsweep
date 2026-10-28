/**
 * Interactive Live Repository Graph Component.
 * High-performance HTML5 Canvas Force-Directed Graph Engine.
 * Features:
 * - Rich color palette connecting each module, function, file, API, class, and table
 * - Interconnected multi-color relational edges (contains, calls, imports, defines, queries, tests)
 * - Progressive node-by-node entry animations
 * - Zoom, pan, and hover tooltips
 * - Click-to-focus: highlights 1st-degree neighbors and dims distant nodes
 * - Type filtering (Modules, Files, Classes, Functions, APIs, Tables)
 * - Entity search and highlight
 * - Registry extraction & download (JSON and CSV)
 * - Fullscreen toggle mode
 */

export class LiveGraph {
  constructor(containerEl, onDownloadRegistry) {
    this.container = containerEl;
    this.onDownloadRegistry = onDownloadRegistry;
    this.nodes = [];
    this.edges = [];
    this.nodeMap = new Map();
    this.filteredTypes = new Set();
    this.searchQuery = '';
    this.focusedNode = null;
    this.hoveredNode = null;

    // Viewport transform
    this.transform = {
      x: 0,
      y: 0,
      scale: 1.0,
      minScale: 0.15,
      maxScale: 3.5,
    };

    // Physics parameters for smooth, balanced interconnected clustering
    this.friction = 0.86;
    this.charge = -320;
    this.springLength = 85;
    this.springStrength = 0.052;
    this.centerStrength = 0.006;

    this.alpha = 1.0;
    this.alphaDecay = 0.02;
    this.alphaMin = 0.002;
    this.isSimulating = false;
    this.animationFrameId = null;

    // Pointer state
    this.isDragging = false;
    this.draggedNode = null;
    this.isPanning = false;
    this.panStart = { x: 0, y: 0 };

    this.render();
  }

  render() {
    this.container.innerHTML = `
      <div class="graph-panel-header">
        <div class="panel-title-group">
          <span class="panel-icon">☊</span>
          <div>
            <h3 class="panel-title">Repository Code Graph</h3>
            <span class="panel-subtitle" id="graphEntitiesCount">0 entities discovered</span>
          </div>
        </div>

        <div class="graph-toolbar">
          <!-- Download Registry Button -->
          <div class="graph-download-group">
            <button type="button" class="btn-download-registry" id="btnGraphDownloadRegistry" title="Download Code Registry extraction (JSON & CSV)">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4m4-5 5 5 5-5m-5 5V3"/></svg>
              <span>Download Registry</span>
            </button>
            <div class="download-dropdown" id="graphDownloadDropdown" style="display:none;">
              <button type="button" class="dropdown-item" id="btnDownloadCsv">
                <span class="item-ext">.CSV</span> Functions & Call Relations (Calls, Called By, Lines)
              </button>
              <button type="button" class="dropdown-item" id="btnDownloadCallGraphCsv">
                <span class="item-ext">.CSV</span> Call Graph Matrix (Who Calls What row-by-row)
              </button>
              <button type="button" class="dropdown-item" id="btnDownloadJson">
                <span class="item-ext">.JSON</span> Full Code Registry & Graph (AST, Hashes, Edges)
              </button>
            </div>
          </div>

          <!-- Search Input -->
          <div class="graph-search-wrapper">
            <input type="text" class="graph-search-input" id="graphSearchInput" placeholder="Search modules, files, functions..." aria-label="Search code graph">
          </div>

          <!-- Type Filters -->
          <div class="graph-filter-chips" id="graphFilterChips">
            <button type="button" class="graph-chip is-active" data-type="all">All</button>
            <button type="button" class="graph-chip" data-type="module" style="--chip-color:#ec4899;">Modules</button>
            <button type="button" class="graph-chip" data-type="file" style="--chip-color:#00f0ff;">Files</button>
            <button type="button" class="graph-chip" data-type="class" style="--chip-color:#a855f7;">Classes</button>
            <button type="button" class="graph-chip" data-type="function" style="--chip-color:#f59e0b;">Functions</button>
            <button type="button" class="graph-chip" data-type="api" style="--chip-color:#10b981;">APIs</button>
            <button type="button" class="graph-chip" data-type="table" style="--chip-color:#3b82f6;">Tables</button>
          </div>

          <!-- View Controls -->
          <div class="graph-view-btns">
            <button type="button" class="graph-ctrl-btn" id="btnGraphZoomIn" title="Zoom In" aria-label="Zoom in">+</button>
            <button type="button" class="graph-ctrl-btn" id="btnGraphZoomOut" title="Zoom Out" aria-label="Zoom out">−</button>
            <button type="button" class="graph-ctrl-btn" id="btnGraphReset" title="Reset View" aria-label="Reset graph view">⊙</button>
            <button type="button" class="graph-ctrl-btn btn-fullscreen" id="btnGraphFullscreen" title="Toggle Fullscreen" aria-label="Toggle Fullscreen">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>
            </button>
          </div>
        </div>
      </div>

      <!-- Graph Legend Bar -->
      <div class="graph-legend-strip">
        <span class="legend-item"><span class="legend-dot" style="background:#ec4899;"></span> Module</span>
        <span class="legend-item"><span class="legend-dot" style="background:#00f0ff;"></span> File</span>
        <span class="legend-item"><span class="legend-dot" style="background:#a855f7;"></span> Class</span>
        <span class="legend-item"><span class="legend-dot" style="background:#f59e0b;"></span> Function</span>
        <span class="legend-item"><span class="legend-dot" style="background:#10b981;"></span> API Endpoint</span>
        <span class="legend-item"><span class="legend-dot" style="background:#3b82f6;"></span> DB Table</span>
        <span class="legend-item"><span class="legend-dot" style="background:#06b6d4;"></span> Service</span>
      </div>

      <!-- Canvas Area -->
      <div class="graph-canvas-container" id="graphCanvasContainer">
        <canvas id="liveGraphCanvas" class="live-graph-canvas"></canvas>
        <div class="graph-tooltip" id="graphTooltip" style="display:none;"></div>
        
        <!-- Click-to-focus Inspector Card -->
        <div class="graph-inspector-card" id="graphInspector" style="display:none;">
          <div class="inspector-header">
            <div class="inspector-badge" id="inspectorType">FILE</div>
            <button type="button" class="btn-inspector-close" id="btnInspectorClose" title="Clear focus" aria-label="Close inspector">✕</button>
          </div>
          <h4 class="inspector-title" id="inspectorTitle">Entity Name</h4>
          <div class="inspector-meta" id="inspectorMeta">src/example.py:L1</div>
          <div class="inspector-connections" id="inspectorConnections">0 connections</div>
          <div class="inspector-neighbors-list" id="inspectorNeighbors"></div>
        </div>
      </div>
    `;

    this.canvas = this.container.querySelector('#liveGraphCanvas');
    this.ctx = this.canvas.getContext('2d');
    this.tooltip = this.container.querySelector('#graphTooltip');
    this.inspector = this.container.querySelector('#graphInspector');

    this.initCanvasSize();
    this.bindEvents();
  }

  initCanvasSize() {
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.width = rect.width || 800;
    this.height = Math.max(420, rect.height || 480);

    this.canvas.width = this.width * dpr;
    this.canvas.height = this.height * dpr;
    this.ctx.resetTransform();
    this.ctx.scale(dpr, dpr);

    if (this.transform.x === 0 && this.transform.y === 0) {
      this.transform.x = this.width / 2;
      this.transform.y = this.height / 2;
    }
  }

  bindEvents() {
    window.addEventListener('resize', () => {
      this.initCanvasSize();
      this.draw();
    });

    // Zoom & Pan
    this.canvas.addEventListener('wheel', (e) => this.handleWheel(e), { passive: false });
    this.canvas.addEventListener('mousedown', (e) => this.handleMouseDown(e));
    window.addEventListener('mousemove', (e) => this.handleMouseMove(e));
    window.addEventListener('mouseup', () => this.handleMouseUp());

    // Controls
    const zoomIn = this.container.querySelector('#btnGraphZoomIn');
    const zoomOut = this.container.querySelector('#btnGraphZoomOut');
    const reset = this.container.querySelector('#btnGraphReset');
    const fs = this.container.querySelector('#btnGraphFullscreen');
    const search = this.container.querySelector('#graphSearchInput');
    const closeInspector = this.container.querySelector('#btnInspectorClose');

    if (zoomIn) zoomIn.addEventListener('click', () => this.zoom(1.25));
    if (zoomOut) zoomOut.addEventListener('click', () => this.zoom(0.8));
    if (reset) reset.addEventListener('click', () => this.resetView());
    if (fs) {
      fs.addEventListener('click', () => {
        this.container.closest('.panel-card').classList.toggle('is-fullscreen');
        setTimeout(() => {
          this.initCanvasSize();
          this.resetView();
        }, 300);
      });
    }

    if (search) {
      search.addEventListener('input', (e) => {
        this.searchQuery = e.target.value.trim().toLowerCase();
        this.draw();
      });
    }

    if (closeInspector) {
      closeInspector.addEventListener('click', () => {
        this.clearFocus();
      });
    }

    // Filter Chips
    const chips = this.container.querySelectorAll('.graph-chip');
    chips.forEach(chip => {
      chip.addEventListener('click', () => {
        chips.forEach(c => c.classList.remove('is-active'));
        chip.classList.add('is-active');
        const type = chip.dataset.type;
        if (type === 'all') {
          this.filteredTypes.clear();
        } else {
          this.filteredTypes = new Set([type]);
        }
        this.draw();
      });
    });

    // Download Registry Dropdown
    const btnDl = this.container.querySelector('#btnGraphDownloadRegistry');
    const dropdown = this.container.querySelector('#graphDownloadDropdown');
    const btnDlCallGraph = this.container.querySelector('#btnDownloadCallGraphCsv');
    const btnDlJson = this.container.querySelector('#btnDownloadJson');
    const btnDlCsv = this.container.querySelector('#btnDownloadCsv');

    if (btnDl && dropdown) {
      btnDl.addEventListener('click', (e) => {
        e.stopPropagation();
        dropdown.style.display = dropdown.style.display === 'none' ? 'block' : 'none';
      });

      document.addEventListener('click', () => {
        dropdown.style.display = 'none';
      });

      if (btnDlCsv) {
        btnDlCsv.addEventListener('click', (e) => {
          e.stopPropagation();
          dropdown.style.display = 'none';
          this.triggerRegistryDownload('csv');
        });
      }

      if (btnDlCallGraph) {
        btnDlCallGraph.addEventListener('click', (e) => {
          e.stopPropagation();
          dropdown.style.display = 'none';
          this.triggerRegistryDownload('callgraph_csv');
        });
      }

      if (btnDlJson) {
        btnDlJson.addEventListener('click', (e) => {
          e.stopPropagation();
          dropdown.style.display = 'none';
          this.triggerRegistryDownload('json');
        });
      }
    }
  }

  triggerRegistryDownload(format = 'json') {
    if (this.onDownloadRegistry) {
      this.onDownloadRegistry(format, this.nodes);
    }
  }

  reset() {
    this.nodes = [];
    this.edges = [];
    this.nodeMap.clear();
    this.focusedNode = null;
    this.hoveredNode = null;
    this.searchQuery = '';
    this.alpha = 1.0;
    this.clearFocus();
    this.updateEntitiesCount();
    this.draw();
  }

  addNode(rawNode) {
    if (this.nodeMap.has(rawNode.id)) return;

    // Distribute nodes using golden angle spiral for balanced physics
    const idx = this.nodes.length;
    const goldenAngle = Math.PI * (3 - Math.sqrt(5)); // ~137.5 deg
    const radius = 32 * Math.sqrt(idx + 1);
    const angle = idx * goldenAngle;

    const nodeType = (rawNode.type || 'file').toLowerCase();
    const node = {
      id: rawNode.id,
      label: rawNode.label || rawNode.name || rawNode.id,
      type: nodeType,
      path: rawNode.path || (rawNode.location && rawNode.location.path) || '',
      line: rawNode.line || (rawNode.location && rawNode.location.start_line) || 1,
      endLine: rawNode.endLine || (rawNode.location && rawNode.location.end_line) || null,
      signature: rawNode.signature || (rawNode.location && rawNode.location.signature) || '',
      hash: rawNode.hash || '',
      layer: rawNode.layer || 'core',
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius,
      vx: (Math.random() - 0.5) * 3,
      vy: (Math.random() - 0.5) * 3,
      radius: this.getNodeRadius(nodeType),
      color: this.getNodeColor(nodeType),
      entryProgress: 0.1,
      neighbors: new Set(),
      neighborEdges: [],
    };

    this.nodes.push(node);
    this.nodeMap.set(node.id, node);
    this.alpha = Math.max(this.alpha, 0.45);
    this.startSimulation();
    this.updateEntitiesCount();
  }

  addEdge(rawEdge) {
    const sId = typeof rawEdge.source === 'object' ? rawEdge.source.id : rawEdge.source;
    const tId = typeof rawEdge.target === 'object' ? rawEdge.target.id : rawEdge.target;

    const sourceNode = this.nodeMap.get(sId);
    const targetNode = this.nodeMap.get(tId);

    if (sourceNode && targetNode && sourceNode !== targetNode) {
      sourceNode.neighbors.add(tId);
      targetNode.neighbors.add(sId);

      const exists = this.edges.some(e => 
        (e.source === sourceNode && e.target === targetNode) ||
        (e.source === targetNode && e.target === sourceNode)
      );

      if (!exists) {
        const edge = {
          source: sourceNode,
          target: targetNode,
          type: rawEdge.type || 'relates',
          color: rawEdge.color || this.getEdgeColor(rawEdge.type),
        };
        this.edges.push(edge);
        sourceNode.neighborEdges.push(edge);
        targetNode.neighborEdges.push(edge);

        this.alpha = Math.max(this.alpha, 0.3);
        this.startSimulation();
      }
    }
  }

  updateEntitiesCount() {
    const el = this.container.querySelector('#graphEntitiesCount');
    if (el) {
      el.textContent = `${this.nodes.length} entities discovered • ${this.edges.length} interconnected links`;
    }
  }

  getNodeRadius(type) {
    switch ((type || '').toLowerCase()) {
      case 'module': return 16;
      case 'file': return 13;
      case 'api': return 13;
      case 'table': return 13;
      case 'service': return 15;
      case 'class': return 10;
      case 'function': return 7.5;
      case 'method': return 6.5;
      default: return 8;
    }
  }

  getNodeColor(type) {
    switch ((type || '').toLowerCase()) {
      case 'module': return '#ec4899';   // Hot Pink / Magenta
      case 'file': return '#00f0ff';     // Electric Cyan
      case 'class': return '#a855f7';    // Vibrant Purple
      case 'function': return '#f59e0b'; // Amber Gold
      case 'method': return '#f97316';   // Coral Orange
      case 'api': return '#10b981';      // Emerald Green
      case 'table': return '#3b82f6';    // Sapphire Blue
      case 'service': return '#06b6d4';  // Teal
      default: return '#64748b';
    }
  }

  getEdgeColor(type) {
    switch ((type || '').toLowerCase()) {
      case 'contains': return 'rgba(0, 240, 255, 0.45)';
      case 'calls': return 'rgba(245, 158, 11, 0.65)';
      case 'imports': return 'rgba(236, 72, 153, 0.55)';
      case 'defines': return 'rgba(16, 185, 129, 0.65)';
      case 'queries': return 'rgba(59, 130, 246, 0.65)';
      case 'tests': return 'rgba(168, 85, 247, 0.65)';
      case 'connects': return 'rgba(6, 182, 212, 0.6)';
      default: return 'rgba(148, 163, 184, 0.35)';
    }
  }

  startSimulation() {
    if (!this.isSimulating) {
      this.isSimulating = true;
      this.tick();
    }
  }

  tick() {
    if (!this.isSimulating) return;

    if (this.alpha > this.alphaMin) {
      this.stepPhysics();
      this.alpha *= (1 - this.alphaDecay);
    }

    // Animate node entry scales smoothly
    this.nodes.forEach(n => {
      if (n.entryProgress < 1.0) {
        n.entryProgress = Math.min(1.0, n.entryProgress + 0.12);
      }
    });

    this.draw();

    if (this.alpha <= this.alphaMin && this.nodes.every(n => n.entryProgress >= 1.0)) {
      this.isSimulating = false;
    } else {
      this.animationFrameId = requestAnimationFrame(() => this.tick());
    }
  }

  stepPhysics() {
    const count = this.nodes.length;
    if (count === 0) return;

    // 1. Repulsion (n-body Coulomb)
    for (let i = 0; i < count; i++) {
      const n1 = this.nodes[i];
      for (let j = i + 1; j < count; j++) {
        const n2 = this.nodes[j];
        const dx = n2.x - n1.x;
        const dy = n2.y - n1.y;
        const distSq = dx * dx + dy * dy || 1;
        const dist = Math.sqrt(distSq);

        if (dist < 380) {
          const force = (this.charge / distSq) * this.alpha;
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;

          n1.vx -= fx;
          n1.vy -= fy;
          n2.vx += fx;
          n2.vy += fy;
        }
      }
    }

    // 2. Spring Hooke's Law for edges
    this.edges.forEach(edge => {
      const dx = edge.target.x - edge.source.x;
      const dy = edge.target.y - edge.source.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const displacement = dist - this.springLength;
      const force = displacement * this.springStrength * this.alpha;

      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;

      edge.source.vx += fx;
      edge.source.vy += fy;
      edge.target.vx -= fx;
      edge.target.vy -= fy;
    });

    // 3. Center gravity & integrate velocity
    this.nodes.forEach(node => {
      if (node === this.draggedNode) return;

      node.vx -= node.x * this.centerStrength * this.alpha;
      node.vy -= node.y * this.centerStrength * this.alpha;

      node.vx *= this.friction;
      node.vy *= this.friction;

      node.x += node.vx;
      node.y += node.vy;
    });
  }

  draw() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.width, this.height);

    ctx.save();
    ctx.translate(this.transform.x, this.transform.y);
    ctx.scale(this.transform.scale, this.transform.scale);

    const isFiltered = (node) => {
      if (this.filteredTypes.size > 0 && !this.filteredTypes.has(node.type)) return false;
      if (this.searchQuery) {
        return node.label.toLowerCase().includes(this.searchQuery) ||
               node.path.toLowerCase().includes(this.searchQuery) ||
               node.type.toLowerCase().includes(this.searchQuery);
      }
      return true;
    };

    // Draw Edges with distinct relational colors & hover highlighting
    this.edges.forEach(edge => {
      const sVisible = isFiltered(edge.source);
      const tVisible = isFiltered(edge.target);
      if (!sVisible && !tVisible) return;

      let strokeColor = edge.color;
      let lineWidth = 1.3;

      // Hover and Focus highlighting
      const isHoverEdge = this.hoveredNode && (edge.source === this.hoveredNode || edge.target === this.hoveredNode);
      const isFocusEdge = this.focusedNode && (edge.source === this.focusedNode || edge.target === this.focusedNode);

      if (isHoverEdge) {
        strokeColor = '#00f0ff';
        lineWidth = 2.5;
      } else if (this.focusedNode) {
        if (isFocusEdge) {
          strokeColor = edge.color;
          lineWidth = 2.4;
        } else {
          strokeColor = 'rgba(148, 163, 184, 0.05)';
          lineWidth = 0.8;
        }
      } else if (this.hoveredNode) {
        strokeColor = 'rgba(148, 163, 184, 0.08)';
        lineWidth = 0.8;
      }

      ctx.beginPath();
      ctx.moveTo(edge.source.x, edge.source.y);
      ctx.lineTo(edge.target.x, edge.target.y);
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = lineWidth;
      ctx.stroke();

      // Draw subtle directional arrow on edge midpoint
      if (lineWidth > 1.0 && this.transform.scale > 0.45) {
        const mx = (edge.source.x + edge.target.x) / 2;
        const my = (edge.source.y + edge.target.y) / 2;
        const angle = Math.atan2(edge.target.y - edge.source.y, edge.target.x - edge.source.x);
        const arrowLen = 5.5;

        ctx.save();
        ctx.translate(mx, my);
        ctx.rotate(angle);
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.lineTo(-arrowLen, -arrowLen * 0.55);
        ctx.lineTo(-arrowLen, arrowLen * 0.55);
        ctx.closePath();
        ctx.fillStyle = strokeColor;
        ctx.fill();
        ctx.restore();
      }
    });

    const isLight = document.documentElement.getAttribute('data-theme') === 'light';

    // Draw Nodes with rich glowing colors & white rim
    this.nodes.forEach(node => {
      const visible = isFiltered(node);
      let opacity = visible ? 1.0 : 0.12;

      const isHovered = this.hoveredNode && this.hoveredNode === node;
      const isFocused = this.focusedNode && this.focusedNode === node;
      const isHoverNeighbor = this.hoveredNode && this.hoveredNode.neighbors.has(node.id);
      const isFocusNeighbor = this.focusedNode && this.focusedNode.neighbors.has(node.id);

      // Focus and Hover dimming
      if (this.focusedNode) {
        if (!isFocused && !isFocusNeighbor) opacity = 0.08;
      } else if (this.hoveredNode) {
        if (!isHovered && !isHoverNeighbor) opacity = 0.2;
      }

      const r = node.radius * node.entryProgress;

      ctx.save();
      ctx.globalAlpha = opacity;

      // Radial Glow Halo
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + (isHovered ? 8 : 4), 0, Math.PI * 2);
      ctx.fillStyle = isHovered ? 'rgba(0, 240, 255, 0.35)' : (node.color + '33');
      ctx.fill();

      // Selected / Hover Ring
      if (isHovered || isFocused) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + 7, 0, Math.PI * 2);
        ctx.lineWidth = 2.5;
        ctx.strokeStyle = '#00f0ff';
        ctx.stroke();
      }

      // Main Node Circle
      ctx.beginPath();
      ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
      ctx.fillStyle = node.color;
      ctx.fill();

      // Crisp border
      ctx.lineWidth = 1.6;
      ctx.strokeStyle = isHovered ? '#ffffff' : 'rgba(255, 255, 255, 0.85)';
      ctx.stroke();

      // Node Label
      const showLabel = this.transform.scale > 0.45 || isFocused || isHovered ||
        ['module', 'api', 'table', 'service'].includes(node.type);

      if (showLabel) {
        ctx.font = `${isHovered ? '600 12px' : '500 11px'} Inter, sans-serif`;
        ctx.textAlign = 'center';
        ctx.fillStyle = (isHovered || isFocused) ? '#00f0ff' : (isLight ? '#0f172a' : '#f8fafc');
        ctx.fillText(node.label, node.x, node.y + r + 13);
      }

      ctx.restore();
    });

    ctx.restore();
  }

  // Pointer & Interaction Handling
  screenToWorld(sx, sy) {
    const rect = this.canvas.getBoundingClientRect();
    const cx = sx - rect.left;
    const cy = sy - rect.top;
    return {
      x: (cx - this.transform.x) / this.transform.scale,
      y: (cy - this.transform.y) / this.transform.scale,
    };
  }

  findNodeAt(wx, wy) {
    for (let i = this.nodes.length - 1; i >= 0; i--) {
      const n = this.nodes[i];
      const dx = n.x - wx;
      const dy = n.y - wy;
      if (dx * dx + dy * dy <= (n.radius + 6) * (n.radius + 6)) {
        return n;
      }
    }
    return null;
  }

  handleMouseDown(e) {
    const pos = this.screenToWorld(e.clientX, e.clientY);
    const clickedNode = this.findNodeAt(pos.x, pos.y);

    if (clickedNode) {
      this.isDragging = true;
      this.draggedNode = clickedNode;
      this.setFocus(clickedNode);
    } else {
      this.isPanning = true;
      this.panStart = { x: e.clientX - this.transform.x, y: e.clientY - this.transform.y };
      this.clearFocus();
    }
  }

  handleMouseMove(e) {
    if (this.isDragging && this.draggedNode) {
      const pos = this.screenToWorld(e.clientX, e.clientY);
      this.draggedNode.x = pos.x;
      this.draggedNode.y = pos.y;
      this.alpha = Math.max(this.alpha, 0.2);
      this.startSimulation();
      return;
    }

    if (this.isPanning) {
      this.transform.x = e.clientX - this.panStart.x;
      this.transform.y = e.clientY - this.panStart.y;
      this.draw();
      return;
    }

    // Hover tooltip
    const pos = this.screenToWorld(e.clientX, e.clientY);
    const hovered = this.findNodeAt(pos.x, pos.y);
    if (hovered !== this.hoveredNode) {
      this.hoveredNode = hovered;
      this.draw();
      if (hovered) {
        this.showTooltip(e, hovered);
      } else {
        this.hideTooltip();
      }
    }
  }

  handleMouseUp() {
    this.isDragging = false;
    this.draggedNode = null;
    this.isPanning = false;
  }

  handleWheel(e) {
    e.preventDefault();
    const zoomFactor = e.deltaY < 0 ? 1.12 : 0.9;
    const rect = this.canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const newScale = Math.min(this.transform.maxScale, Math.max(this.transform.minScale, this.transform.scale * zoomFactor));

    this.transform.x = mouseX - (mouseX - this.transform.x) * (newScale / this.transform.scale);
    this.transform.y = mouseY - (mouseY - this.transform.y) * (newScale / this.transform.scale);
    this.transform.scale = newScale;

    this.draw();
  }

  zoom(factor) {
    const newScale = Math.min(this.transform.maxScale, Math.max(this.transform.minScale, this.transform.scale * factor));
    this.transform.scale = newScale;
    this.draw();
  }

  resetView() {
    this.transform = {
      x: this.width / 2,
      y: this.height / 2,
      scale: 1.0,
      minScale: 0.15,
      maxScale: 3.5,
    };
    this.alpha = 0.5;
    this.startSimulation();
  }

  setFocus(node) {
    this.focusedNode = node;
    this.draw();

    if (this.inspector) {
      this.inspector.querySelector('#inspectorType').textContent = node.type.toUpperCase();
      this.inspector.querySelector('#inspectorType').style.color = node.color;
      this.inspector.querySelector('#inspectorTitle').textContent = node.label;
      this.inspector.querySelector('#inspectorMeta').textContent = node.path ? `${node.path}:L${node.line}` : 'Global Architecture Entity';
      this.inspector.querySelector('#inspectorConnections').textContent = `${node.neighbors.size} directly linked entities (${node.neighborEdges.length} edges)`;
      
      const neighborsContainer = this.inspector.querySelector('#inspectorNeighbors');
      if (neighborsContainer) {
        let nHtml = '<div class="inspector-subhead">Connected Relations:</div><div class="neighbors-tags">';
        node.neighborEdges.slice(0, 10).forEach(edge => {
          const other = edge.source === node ? edge.target : edge.source;
          const direction = edge.source === node ? '→' : '←';
          nHtml += `<span class="neighbor-tag" style="border-left:3px solid ${other.color};">${direction} [${edge.type}] ${other.label}</span>`;
        });
        if (node.neighborEdges.length > 10) {
          nHtml += `<span class="neighbor-tag">+${node.neighborEdges.length - 10} more</span>`;
        }
        nHtml += '</div>';
        neighborsContainer.innerHTML = nHtml;
      }

      this.inspector.style.display = 'block';
    }
  }

  clearFocus() {
    this.focusedNode = null;
    if (this.inspector) {
      this.inspector.style.display = 'none';
    }
    this.draw();
  }

  showTooltip(e, node) {
    if (!this.tooltip) return;
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const x = e.clientX - rect.left + 15;
    const y = e.clientY - rect.top + 15;

    this.tooltip.innerHTML = `
      <div class="tooltip-badge" style="background:${node.color}22; color:${node.color};">${node.type.toUpperCase()}</div>
      <div class="tooltip-title">${node.label}</div>
      <div class="tooltip-sub">${node.path || 'Global Entity'}</div>
      <div class="tooltip-extra">${node.neighbors.size} connections • ${node.layer} layer</div>
    `;

    this.tooltip.style.left = `${x}px`;
    this.tooltip.style.top = `${y}px`;
    this.tooltip.style.display = 'block';
  }

  hideTooltip() {
    if (this.tooltip) {
      this.tooltip.style.display = 'none';
    }
  }
}
