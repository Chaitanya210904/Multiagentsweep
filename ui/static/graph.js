/**
 * Interactive Code Graph Module.
 * Exports the new LiveGraph engine while preserving backward compatibility
 * with InteractiveCodeGraph.
 */

import { LiveGraph } from './components/LiveGraph.js';

export class InteractiveCodeGraph {
  constructor(canvasId, tooltipId) {
    this.canvas = document.getElementById(canvasId);
    if (this.canvas) {
      this.liveGraph = new LiveGraph(this.canvas.parentElement);
    }
  }

  setData(data) {
    if (this.liveGraph) {
      this.liveGraph.reset();
      (data.nodes || []).forEach(n => this.liveGraph.addNode(n));
      (data.edges || []).forEach(e => this.liveGraph.addEdge(e));
    }
  }

  initCanvasSize() {
    if (this.liveGraph) {
      this.liveGraph.initCanvasSize();
    }
  }

  render() {
    if (this.liveGraph) {
      this.liveGraph.draw();
    }
  }
}

// Global window registration for non-module scripts
if (typeof window !== 'undefined') {
  window.LiveGraph = LiveGraph;
  window.InteractiveCodeGraph = InteractiveCodeGraph;
}

export { LiveGraph };
