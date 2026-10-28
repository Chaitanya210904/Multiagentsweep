/**
 * RepoInput Component.
 * Controls the centered landing input in State 1 and triggers the transition into State 2.
 * Validates repository URLs with inline feedback, handles keyboard submission,
 * and exposes curated demo repository chips for instant testing.
 */

export class RepoInput {
  constructor({ inputEl, buttonEl, errorEl, formEl, chipsContainerEl, stateMachine, onSubmit }) {
    this.input = inputEl;
    this.button = buttonEl;
    this.error = errorEl;
    this.form = formEl;
    this.chipsContainer = chipsContainerEl;
    this.stateMachine = stateMachine;
    this.onSubmit = onSubmit;

    this.sampleRepos = [
      { name: 'psf/requests', url: 'https://github.com/psf/requests' },
      { name: 'pallets/flask', url: 'https://github.com/pallets/flask' },
      { name: 'fastapi/fastapi', url: 'https://github.com/fastapi/fastapi' },
      { name: 'expressjs/express', url: 'https://github.com/expressjs/express' },
    ];

    this.bindEvents();
    this.renderChips();
    this.validate();
  }

  bindEvents() {
    this.input.addEventListener('input', () => this.handleInput());
    this.input.addEventListener('blur', () => this.handleBlur());
    this.input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        this.submit();
      }
    });

    if (this.form) {
      this.form.addEventListener('submit', (e) => {
        e.preventDefault();
        this.submit();
      });
    }

    this.button.addEventListener('click', (e) => {
      e.preventDefault();
      this.submit();
    });
  }

  renderChips() {
    if (!this.chipsContainer) return;
    this.chipsContainer.innerHTML = '';

    const label = document.createElement('span');
    label.className = 'quick-chips-label';
    label.textContent = 'Or try a public repository:';
    this.chipsContainer.appendChild(label);

    const chipsWrapper = document.createElement('div');
    chipsWrapper.className = 'quick-chips-list';

    this.sampleRepos.forEach(repo => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'repo-chip';
      chip.textContent = repo.name;
      chip.setAttribute('aria-label', `Select sample repository ${repo.name}`);
      chip.addEventListener('click', () => {
        this.input.value = repo.url;
        this.validate();
        this.input.focus();
        this.clearError();
      });
      chipsWrapper.appendChild(chip);
    });

    this.chipsContainer.appendChild(chipsWrapper);
  }

  handleInput() {
    this.clearError();
    this.validate();
  }

  handleBlur() {
    const val = this.input.value.trim();
    if (val) {
      const res = this.stateMachine.validateUrl(val);
      if (!res.isValid) {
        this.showError(res.error);
      }
    }
  }

  validate() {
    const raw = this.input.value.trim();
    if (!raw) {
      this.button.disabled = true;
      this.button.setAttribute('aria-disabled', 'true');
      return false;
    }

    const res = this.stateMachine.validateUrl(raw);
    if (!res.isValid) {
      this.button.disabled = true;
      this.button.setAttribute('aria-disabled', 'true');
      return false;
    }

    this.button.disabled = false;
    this.button.removeAttribute('aria-disabled');
    return true;
  }

  showError(message) {
    if (!this.error) return;
    this.error.textContent = message;
    this.error.classList.add('visible');
    this.input.setAttribute('aria-invalid', 'true');
    this.input.classList.add('has-error');
  }

  clearError() {
    if (!this.error) return;
    this.error.textContent = '';
    this.error.classList.remove('visible');
    this.input.removeAttribute('aria-invalid');
    this.input.classList.remove('has-error');
  }

  submit() {
    const raw = this.input.value.trim();
    if (!raw) {
      this.showError('Please paste a GitHub or GitLab repository link to begin analysis.');
      this.input.focus();
      return;
    }

    const res = this.stateMachine.validateUrl(raw);
    if (!res.isValid) {
      this.showError(res.error);
      this.input.focus();
      return;
    }

    this.clearError();
    if (this.onSubmit) {
      this.onSubmit(res);
    }
  }

  clear() {
    this.input.value = '';
    this.clearError();
    this.validate();
  }

  focus() {
    setTimeout(() => {
      this.input.focus();
    }, 100);
  }
}
