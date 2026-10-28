/**
 * State Management & Reactive Event Bus for Repository Analyzer.
 * Governs the application lifecycle:
 * IDLE -> VALIDATING -> ANALYZING -> COMPLETE | ERROR
 */

export const AppState = {
  IDLE: 'idle',           // State 1: Minimal Landing View
  VALIDATING: 'validating', // Checking repo URL
  ANALYZING: 'analyzing', // State 2: Active analysis workspace & streaming
  COMPLETE: 'complete',   // Analysis finished successfully, summary ready
  ERROR: 'error',         // Analysis failed, error & retry state
};

export class StateMachine {
  constructor() {
    this.state = AppState.IDLE;
    this.previousState = null;
    this.repoUrl = '';
    this.repoName = '';
    this.repoOwner = '';
    this.listeners = new Map();
    this.streamMode = 'mock'; // 'mock' (standalone demo) or 'live' (real backend API)
    this.theme = this.getInitialTheme();
  }

  getInitialTheme() {
    const saved = localStorage.getItem('repo-analyzer-theme');
    if (saved === 'light' || saved === 'dark') return saved;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }

  setTheme(theme) {
    this.theme = theme;
    localStorage.setItem('repo-analyzer-theme', theme);
    document.documentElement.setAttribute('data-theme', theme);
    this.emit('theme_changed', theme);
  }

  toggleTheme() {
    const next = this.theme === 'dark' ? 'light' : 'dark';
    this.setTheme(next);
    return next;
  }

  on(event, callback) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event).add(callback);
    return () => this.listeners.get(event).delete(callback);
  }

  emit(event, data) {
    const handlers = this.listeners.get(event);
    if (handlers) {
      handlers.forEach(cb => {
        try {
          cb(data);
        } catch (err) {
          console.error(`Error in event handler for "${event}":`, err);
        }
      });
    }
  }

  transition(newState, payload = {}) {
    const oldState = this.state;
    this.previousState = oldState;
    this.state = newState;

    // Update root DOM attribute for CSS state-driven styling
    const appEl = document.getElementById('app');
    if (appEl) {
      appEl.setAttribute('data-state', newState);
    }

    this.emit('state_changed', { from: oldState, to: newState, ...payload });
  }

  /**
   * Validate a repository URL (GitHub or GitLab, HTTPS or SSH).
   * Returns: { isValid: boolean, owner: string, repo: string, error?: string }
   */
  validateUrl(url) {
    if (!url || typeof url !== 'string') {
      return { isValid: false, error: 'Repository URL is required.' };
    }

    const trimmed = url.trim();
    if (!trimmed) {
      return { isValid: false, error: 'Repository URL cannot be blank.' };
    }

    // Supported patterns:
    // 1. https://github.com/owner/repo or https://gitlab.com/owner/repo
    // 2. git@github.com:owner/repo.git or git@gitlab.com:owner/repo.git
    // 3. owner/repo shorthand (e.g. psf/requests)
    const githubHttpsRegex = /^(?:https?:\/\/)?(?:www\.)?(github\.com|gitlab\.com)\/([a-zA-Z0-9_.-]+)\/([a-zA-Z0-9_.-]+?)(?:\.git|\/)?$/i;
    const sshRegex = /^git@(github\.com|gitlab\.com):([a-zA-Z0-9_.-]+)\/([a-zA-Z0-9_.-]+?)(?:\.git)?$/i;
    const shorthandRegex = /^([a-zA-Z0-9_.-]+)\/([a-zA-Z0-9_.-]+)$/;

    let match = trimmed.match(githubHttpsRegex);
    if (match) {
      return {
        isValid: true,
        host: match[1].toLowerCase(),
        owner: match[2],
        repo: match[3],
        canonicalUrl: `https://${match[1].toLowerCase()}/${match[2]}/${match[3]}`,
      };
    }

    match = trimmed.match(sshRegex);
    if (match) {
      return {
        isValid: true,
        host: match[1].toLowerCase(),
        owner: match[2],
        repo: match[3],
        canonicalUrl: `https://${match[1].toLowerCase()}/${match[2]}/${match[3]}`,
      };
    }

    match = trimmed.match(shorthandRegex);
    if (match && !trimmed.startsWith('http')) {
      return {
        isValid: true,
        host: 'github.com',
        owner: match[1],
        repo: match[2],
        canonicalUrl: `https://github.com/${match[1]}/${match[2]}`,
      };
    }

    return {
      isValid: false,
      error: 'Please enter a valid GitHub or GitLab repository URL (e.g. https://github.com/owner/repo)',
    };
  }

  startAnalysis(rawUrl) {
    const val = this.validateUrl(rawUrl);
    if (!val.isValid) {
      this.emit('validation_error', val.error);
      return false;
    }

    this.repoUrl = val.canonicalUrl;
    this.repoOwner = val.owner;
    this.repoName = val.repo;

    this.transition(AppState.ANALYZING, {
      url: this.repoUrl,
      owner: this.repoOwner,
      repo: this.repoName,
    });
    return true;
  }

  completeAnalysis(summary) {
    this.transition(AppState.COMPLETE, { summary });
  }

  failAnalysis(error) {
    this.transition(AppState.ERROR, { error });
  }

  resetToLanding() {
    this.repoUrl = '';
    this.repoName = '';
    this.repoOwner = '';
    this.transition(AppState.IDLE);
  }
}
