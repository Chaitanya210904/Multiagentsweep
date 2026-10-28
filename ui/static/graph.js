/**
 * Interactive HTML5 Canvas Force-Directed Code Graph Renderer.
 * Provides real-time physics simulation, pan/zoom, node dragging,
 * search filtering, and hover tooltips for all repository entities.
 */

class InteractiveCodeGraph {
  constructor(canvasId, tooltipId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas.getContext('2d');
    this.tooltip = document.getElementById(tooltipId);

    this.nodes = [];
    this.edges = [];
    this.nodeMap = new Map();

    // Viewport transform
    this.transform = {
      x: 0,
      y: 0,
      scale: 1.0,
      minScale: 0.15,
      maxScale: 3.5,
    };

    // Physics parameters
    this.friction = 0.88;
    this.charge = -320;
    this.springLength = 80;
    this.springStrength = 0.05;
    this.centerStrength = 0.015;
    this.isRunning = true;

    // Interaction states
    this.isDragging = false;
    this.draggedNode = null;
    this.isPanning = false;
    this.panStart = { x: 0, y: 0 };
    this.hoveredNode = null;
    this.searchQuery = '';

    // Color mapping
    this.colorMap = {
      api: '#10b981',
      table: '#3b82f6',
      service: '#06b6d4',
      file: '#00f0ff',
      class: '#a855f7',
      function: '#f59e0b',
      method: '#f97316',
      module: '#ec4899',
      default: '#64748b',
    };

    this.initCanvasSize();
    this.bindEvents();
  }

  initCanvasSize() {
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.width = rect.width || 1200;
    this.height = rect.height || 720;

    this.canvas.width = this.width * dpr;
    this.canvas.height = this.height * dpr;
    this.ctx.scale(dpr, dpr);

    // Initial center transform
    this.transform.x = this.width / 2;
    this.transform.y = this.height / 2;
  }

  setData(graphData) {
    this.nodes = [];
    this.edges = [];
    this.nodeMap.clear();

    const rawNodes = graphData.nodes || [];
    const rawEdges = graphData.edges || [];

    // Initialize nodes with random positions near center
    rawNodes.forEach((rn, idx) => {
      const angle = (idx / rawNodes.length) * Math.PI * 2;
      const radius = 100 + Math.random() * 250;
      const node = {
        id: rn.id,
        label: rn.label || rn.id,
        type: rn.type || 'file',
        layer: rn.layer || 'core',
        path: rn.path || '',
        line: rn.line,
        val: rn.val || 8,
        color: this.colorMap[rn.type] || this.colorMap.default,
        x: Math.cos(angle) * radius,
        y: Math.sin(angle) * radius,
        vx: 0,
        vy: 0,
        pinned: false,
        neighbors: new Set(),
      };
      this.nodes.push(node);
      this.nodeMap.set(node.id, node);
    });

    // Build edges linking node references
    rawEdges.forEach(re => {
      const source = this.nodeMap.get(re.source);
      const target = this.nodeMap.get(re.target);
      if (source && target && source !== target) {
        source.neighbors.add(target.id);
        target.neighbors.add(source.id);
        this.edges.push({
          source,
          target,
          type: re.type || 'rel',
          color: re.color || 'rgba(255, 255, 255, 0.12)',
        });
      }
    });

    this.startSimulation();
  }

  startSimulation() {
    this.isRunning = true;
    const step = () => {
      if (this.isRunning) {
        this.updatePhysics();
        this.render();
        requestAnimationFrame(step);
      }
    };
    requestAnimationFrame(step);
  }

  updatePhysics() {
    const nodes = this.nodes;
    const edges = this.edges;

    // 1. Repulsion between nodes (Coulomb's Law approximation)
    for (let i = 0; i < nodes.length; i++) {
      const n1 = nodes[i];
      for (let j = i + 1; j < nodes.length; j++) {
        const n2 = nodes[j];
        const dx = n2.x - n1.x;
        const dy = n2.y - n1.y;
        let distSq = dx * dx + dy * dy;
        if (distSq < 1) distSq = 1;
        if (distSq < 90000) { // cut-off
          const dist = Math.sqrt(distSq);
          const force = this.charge / distSq;
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;

          if (!n1.pinned) { n1.vx += fx; n1.vy += fy; }
          if (!n2.pinned) { n2.vx -= fx; n2.vy -= fy; }
        }
      }
    }

    // 2. Spring attraction along edges (Hooke's Law)
    for (let i = 0; i < edges.length; i++) {
      const e = edges[i];
      const dx = e.target.x - e.source.x;
      const dy = e.target.y - e.source.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const force = (dist - this.springLength) * this.springStrength;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;

      if (!e.source.pinned) { e.source.vx += fx; e.source.vy += fy; }
      if (!e.target.pinned) { e.target.vx -= fx; e.target.vy -= fy; }
    }

    // 3. Gravity centering & velocity damping
    for (let i = 0; i < nodes.length; i++) {
      const n = nodes[i];
      if (!n.pinned) {
        n.vx -= n.x * this.centerStrength;
        n.vy -= n.y * this.centerStrength;

        n.vx *= this.friction;
        n.vy *= this.friction;

        n.x += n.vx;
        n.y += n.vy;
      }
    }
  }

  render() {
    this.ctx.save();
    this.ctx.clearRect(0, 0, this.width, this.height);

    // Apply viewport transform
    this.ctx.translate(this.transform.x, this.transform.y);
    this.ctx.scale(this.transform.scale, this.transform.scale);

    const query = this.searchQuery.toLowerCase().trim();

    // 1. Draw Edges
    this.edges.forEach(e => {
      const isHighlighted = this.hoveredNode && 
        (e.source.id === this.hoveredNode.id || e.target.id === this.hoveredNode.id);

      this.ctx.beginPath();
      this.ctx.moveTo(e.source.x, e.source.y);
      this.ctx.lineTo(e.target.x, e.target.y);

      if (isHighlighted) {
        this.ctx.strokeStyle = '#00f0ff';
        this.ctx.lineWidth = 2.5 / this.transform.scale;
      } else {
        this.ctx.strokeStyle = query ? 'rgba(255, 255, 255, 0.04)' : 'rgba(255, 255, 255, 0.12)';
        this.ctx.lineWidth = 1 / this.transform.scale;
      }
      this.ctx.stroke();
    });

    // 2. Draw Nodes
    this.nodes.forEach(n => {
      const matchesSearch = query ? (n.label.toLowerCase().includes(query) || n.path.toLowerCase().includes(query)) : true;
      const isHovered = this.hoveredNode && this.hoveredNode.id === n.id;
      const isConnected = this.hoveredNode && this.hoveredNode.neighbors.has(n.id);

      let alpha = 1.0;
      if (query && !matchesSearch) alpha = 0.15;
      if (this.hoveredNode && !isHovered && !isConnected) alpha = Math.min(alpha, 0.2);

      this.ctx.save();
      this.ctx.globalAlpha = alpha;

      // Node shape & glow
      this.ctx.beginPath();
      const radius = isHovered ? n.val * 1.5 : n.val;
      this.ctx.arc(n.x, n.y, radius, 0, Math.PI * 2);
      this.ctx.fillStyle = n.color;
      this.ctx.fill();

      if (isHovered || (query && matchesSearch)) {
        this.ctx.lineWidth = 3 / this.transform.scale;
        this.ctx.strokeStyle = '#ffffff';
        this.ctx.stroke();
      }

      // Draw label when zoomed in or on important nodes
      if (this.transform.scale > 0.7 || n.type === 'api' || n.type === 'table' || isHovered) {
        this.ctx.fillStyle = isHovered ? '#00f0ff' : '#cbd5e1';
        this.ctx.font = `${Math.max(10, 11 / this.transform.scale)}px 'Inter', sans-serif`;
        this.ctx.textAlign = 'center';
        this.ctx.fillText(n.label, n.x, n.y + radius + 14 / this.transform.scale);
      }

      this.ctx.restore();
    });

    this.ctx.restore();
  }

  // ---------------- User Interactions ----------------
  screenToWorld(sx, sy) {
    return {
      x: (sx - this.transform.x) / this.transform.scale,
      y: (sy - this.transform.y) / this.transform.scale,
    };
  }

  getNodeAt(worldX, worldY) {
    for (let i = this.nodes.length - 1; i >= 0; i--) {
      const n = this.nodes[i];
      const dx = n.x - worldX;
      const dy = n.y - worldY;
      const hitRadius = (n.val + 6) / this.transform.scale;
      if (dx * dx + dy * dy <= hitRadius * hitRadius) {
        return n;
      }
    }
    return null;
  }

  bindEvents() {
    window.addEventListener('resize', () => this.initCanvasSize());

    // Mouse Down
    this.canvas.addEventListener('mousedown', e => {
      const rect = this.canvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const world = this.screenToWorld(sx, sy);
      const clicked = this.getNodeAt(world.x, world.y);

      if (clicked) {
        this.isDragging = true;
        this.draggedNode = clicked;
        clicked.pinned = true;
      } else {
        this.isPanning = true;
        this.panStart = { x: sx - this.transform.x, y: sy - this.transform.y };
      }
    });

    // Mouse Move
    this.canvas.addEventListener('mousemove', e => {
      const rect = this.canvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const world = this.screenToWorld(sx, sy);

      if (this.isDragging && this.draggedNode) {
        this.draggedNode.x = world.x;
        this.draggedNode.y = world.y;
        this.draggedNode.vx = 0;
        this.draggedNode.vy = 0;
      } else if (this.isPanning) {
        this.transform.x = sx - this.panStart.x;
        this.transform.y = sy - this.panStart.y;
      } else {
        const hover = this.getNodeAt(world.x, world.y);
        if (hover !== this.hoveredNode) {
          this.hoveredNode = hover;
          this.showTooltip(hover, e.clientX, e.clientY);
        }
      }
    });

    // Mouse Up
    window.addEventListener('mouseup', () => {
      if (this.isDragging && this.draggedNode) {
        this.draggedNode.pinned = false;
        this.draggedNode = null;
        this.isDragging = false;
      }
      this.isPanning = false;
    });

    // Wheel Zoom
    this.canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const rect = this.canvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;

      const zoomFactor = e.deltaY < 0 ? 1.15 : 0.85;
      const newScale = Math.max(this.transform.minScale, Math.min(this.transform.maxScale, this.transform.scale * zoomFactor));

      this.transform.x = sx - (sx - this.transform.x) * (newScale / this.transform.scale);
      this.transform.y = sy - (sy - this.transform.y) * (newScale / this.transform.scale);
      this.transform.scale = newScale;
    });
  }

  showTooltip(node, clientX, clientY) {
    if (!node) {
      this.tooltip.style.display = 'none';
      return;
    }

    const typeBadge = `<span class="badge" style="background:${node.color}22; color:${node.color}; border:1px solid ${node.color}55;">${node.type.toUpperCase()}</span>`;
    const loc = node.path ? `<div style="color:#94a3b8; font-family:var(--font-mono); margin-top:4px;">${node.path}${node.line ? `:${node.line}` : ''}</div>` : '';

    this.tooltip.innerHTML = `
      <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:4px;">
        <strong style="color:#fff; font-size:0.875rem;">${node.label}</strong>
        ${typeBadge}
      </div>
      ${loc}
      <div style="color:#64748b; font-size:0.75rem; margin-top:6px;">
        Edges / Linked Nodes: <span style="color:#fff; font-weight:600;">${node.neighbors.size}</span>
      </div>
    `;

    this.tooltip.style.left = `${clientX + 16}px`;
    this.tooltip.style.top = `${clientY + 16}px`;
    this.tooltip.style.display = 'block';
  }

  setFilter(query) {
    this.searchQuery = query || '';
  }

  resetView() {
    this.transform.x = this.width / 2;
    this.transform.y = this.height / 2;
    this.transform.scale = 1.0;
  }

  zoom(factor) {
    const cx = this.width / 2;
    const cy = this.height / 2;
    const newScale = Math.max(this.transform.minScale, Math.min(this.transform.maxScale, this.transform.scale * factor));
    this.transform.x = cx - (cx - this.transform.x) * (newScale / this.transform.scale);
    this.transform.y = cy - (cy - this.transform.y) * (newScale / this.transform.scale);
    this.transform.scale = newScale;
  }
}
