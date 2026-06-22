/**
 * context-chat.js — Web Component <context-chat>
 *
 * Drop-in para QUALQUER interface web. Sem dependencia, sem build.
 *
 *   <script src="context-chat.js"></script>
 *   <context-chat
 *       endpoint="http://localhost:8000/api/v1/presentation/chat"
 *       title="Q&A com IA"
 *       auth=""              <!-- opcional: Bearer token -->
 *       fullscreen           <!-- opcional: abre direto em tela cheia -->
 *   ></context-chat>
 *
 * Dois modos:
 *   - popover de canto (para o apresentador digitar);
 *   - TELA CHEIA com tipografia grande (para a plateia ler projetado).
 *     Botao de expandir no header, ou abre ja cheio com o atributo `fullscreen`.
 *     ESC sai da tela cheia.
 *
 * Oculto na impressao/export PDF. Estilo encapsulado em Shadow DOM.
 */
(function () {
  const STYLE = `
    :host { all: initial; }
    @media print { :host { display: none !important; } }
    * { box-sizing: border-box; margin: 0; padding: 0; }

    :host {
      --bg:          #0C0F14;
      --surface:     #141B26;
      --surface-hi:  #1C2535;
      --border:      #252F40;
      --text:        #EAE6DF;
      --text-dim:    #7B8CA4;
      --accent:      #D95F3B;
      --accent-glow: rgba(217,95,59,.18);
      --user:        #C2963E;
      --bot:         #5B9BD5;
      --err:         #C0493A;
      --r:           8px;
      --font: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    }

    /* ── WRAPPER ─────────────────────────────────────────────── */
    .wrap {
      position: fixed; bottom: 24px; right: 24px; z-index: 2147483000;
      font-family: var(--font);
      display: flex; flex-direction: column; align-items: flex-end; gap: 10px;
    }

    /* ── TOGGLE ──────────────────────────────────────────────── */
    @keyframes live-pulse {
      0%,100% { opacity: 1;   transform: scale(1);   }
      50%     { opacity: .45; transform: scale(.65); }
    }

    .toggle {
      display: flex; align-items: center; gap: 9px;
      background: var(--surface); color: var(--text);
      border: 1px solid var(--border); border-radius: var(--r);
      padding: 9px 15px; cursor: pointer;
      font-size: 13px; font-weight: 500; letter-spacing: .2px;
      box-shadow: 0 4px 20px rgba(0,0,0,.45), 0 0 0 1px rgba(255,255,255,.04);
      transition: background .14s, border-color .14s, box-shadow .14s;
    }
    .toggle:hover {
      background: var(--surface-hi);
      border-color: rgba(255,255,255,.1);
      box-shadow: 0 6px 28px rgba(0,0,0,.55), 0 0 0 1px rgba(255,255,255,.07);
    }
    .toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }

    .live-dot {
      width: 7px; height: 7px; border-radius: 50%;
      background: var(--accent); flex-shrink: 0;
      animation: live-pulse 2.4s ease-in-out infinite;
    }

    /* ── PANEL ───────────────────────────────────────────────── */
    @keyframes pop-in {
      from { opacity: 0; transform: translateY(12px) scale(.97); }
      to   { opacity: 1; transform: translateY(0)    scale(1);   }
    }

    .panel {
      display: none; flex-direction: column;
      width: min(440px, 94vw); max-height: min(62vh, 560px);
      background: var(--bg); border: 1px solid var(--border);
      border-radius: var(--r); overflow: hidden;
      box-shadow: 0 20px 56px rgba(0,0,0,.6), 0 0 0 1px rgba(255,255,255,.04);
    }
    .panel.open { display: flex; }
    @media (prefers-reduced-motion: no-preference) {
      .panel.open { animation: pop-in .22s cubic-bezier(.16,1,.3,1) both; }
    }

    /* ── HEADER ──────────────────────────────────────────────── */
    .head {
      display: flex; align-items: center; gap: 9px;
      padding: 12px 14px;
      background: var(--surface); border-bottom: 1px solid var(--border);
      border-left: 3px solid var(--accent);
    }
    .head-name {
      flex: 1; font-size: 11px; font-weight: 700;
      color: var(--text-dim); letter-spacing: .7px; text-transform: uppercase;
    }
    .iconbtn {
      background: transparent; border: 1px solid transparent;
      color: var(--text-dim); width: 28px; height: 28px;
      border-radius: calc(var(--r) - 2px); cursor: pointer;
      font-size: 14px; display: grid; place-items: center;
      transition: color .12s, border-color .12s, background .12s;
    }
    .iconbtn:hover { color: var(--text); border-color: var(--border); background: var(--surface-hi); }
    .iconbtn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

    /* ── MESSAGES ────────────────────────────────────────────── */
    .msgs {
      padding: 18px 16px; overflow-y: auto; flex: 1;
      display: flex; flex-direction: column; gap: 18px;
      scroll-behavior: smooth;
      scrollbar-width: thin; scrollbar-color: var(--border) transparent;
    }
    .msgs::-webkit-scrollbar { width: 4px; }
    .msgs::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

    .placeholder {
      color: var(--text-dim); font-size: 13px; font-style: italic;
      margin: auto; text-align: center; opacity: .6;
    }

    .turn { display: flex; flex-direction: column; gap: 5px; }
    .role {
      font-size: 10px; font-weight: 700;
      letter-spacing: 1.1px; text-transform: uppercase; color: var(--text-dim);
    }
    .q .role  { color: var(--user); }
    .a .role  { color: var(--bot);  }
    .err .role { color: var(--err); }

    .bubble {
      font-size: 14px; line-height: 1.6;
      color: var(--text); white-space: pre-wrap; word-break: break-word;
    }
    .a .bubble {
      padding-left: 11px;
      border-left: 2px solid var(--bot);
    }
    .err .bubble {
      padding-left: 11px;
      border-left: 2px solid var(--err);
      color: #F0A294;
    }

    /* ── INPUT BAR ───────────────────────────────────────────── */
    .bar {
      display: flex; gap: 8px; padding: 12px;
      border-top: 1px solid var(--border); background: var(--surface);
    }
    .bar input {
      flex: 1; background: var(--bg); border: 1px solid var(--border);
      border-radius: var(--r); color: var(--text);
      padding: 10px 13px; font-size: 13.5px; font-family: var(--font); outline: none;
      transition: border-color .14s, box-shadow .14s;
    }
    .bar input:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-glow);
    }
    .bar input::placeholder { color: var(--text-dim); opacity: .55; }
    .bar .send {
      background: var(--accent); color: #fff;
      border: none; border-radius: var(--r);
      padding: 0 16px; cursor: pointer; font-size: 16px;
      transition: background .12s, opacity .12s; flex-shrink: 0;
    }
    .bar .send:hover { background: #E07050; }
    .bar .send:disabled { opacity: .3; cursor: default; }
    .bar .send:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }

    /* ── MOBILE ──────────────────────────────────────────────── */
    @media (max-width: 480px) {
      .wrap { bottom: 16px; right: 16px; }
      .panel { max-height: 72vh; }
    }

    /* ── TELA CHEIA ──────────────────────────────────────────── */
    .wrap.full { inset: 0; bottom: auto; right: auto; align-items: stretch; }
    .wrap.full .toggle { display: none; }
    .wrap.full .panel {
      position: fixed; inset: 0; width: 100vw; height: 100vh;
      max-height: none; border: none; border-radius: 0;
      background: radial-gradient(ellipse 130% 100% at 50% 0%, #131C2E 0%, #0A0D14 70%);
    }
    .wrap.full .head {
      padding: 18px 32px;
      border-left-width: 4px;
    }
    .wrap.full .head-name { font-size: 12px; letter-spacing: .9px; }
    .wrap.full .iconbtn { width: 36px; height: 36px; font-size: 17px; }
    .wrap.full .msgs {
      padding: 5vh 24px; gap: 32px;
      max-width: 900px; width: 100%; margin: 0 auto;
    }
    .wrap.full .role { font-size: clamp(10px, .9vw, 13px); }
    .wrap.full .bubble {
      font-size: clamp(18px, 2.1vw, 27px); line-height: 1.5;
    }
    .wrap.full .a .bubble { padding-left: 16px; border-left-width: 3px; }
    .wrap.full .bar { padding: 18px 24px; }
    .wrap.full .bar input {
      max-width: 900px; margin: 0 auto;
      font-size: clamp(15px, 1.6vw, 20px);
      padding: 14px 18px; border-radius: 10px;
    }
    .wrap.full .bar .send { font-size: 20px; padding: 0 22px; border-radius: 10px; }
  `;

  class ContextChat extends HTMLElement {
    constructor() {
      super();
      this.history = [];
      this.busy = false;
      this.attachShadow({ mode: "open" });
    }

    connectedCallback() {
      this.endpoint = this.getAttribute("endpoint") || "http://localhost:8000/api/v1/presentation/chat";
      this.auth = this.getAttribute("auth") || "";
      this.startFull = this.hasAttribute("fullscreen");
      const title = this.getAttribute("title") || "Q&A com IA";

      this.shadowRoot.innerHTML = `
        <style>${STYLE}</style>
        <div class="wrap">
          <div class="panel" part="panel">
            <div class="head">
              <span class="head-name">${title}</span>
              <button class="iconbtn expand" title="Tela cheia" aria-label="Tela cheia">⛶</button>
              <button class="iconbtn close" title="Fechar" aria-label="Fechar">✕</button>
            </div>
            <div class="msgs"><span class="placeholder">Faça uma pergunta sobre o contexto…</span></div>
            <div class="bar">
              <input type="text" placeholder="Pergunta… (Enter para enviar)" aria-label="Pergunta" />
              <button class="send" title="Enviar" aria-label="Enviar">→</button>
            </div>
          </div>
          <button class="toggle" aria-label="Abrir ${title}">
            <span class="live-dot"></span>
            <span>${title}</span>
          </button>
        </div>
      `;

      this.$wrap = this.shadowRoot.querySelector(".wrap");
      this.$panel = this.shadowRoot.querySelector(".panel");
      this.$msgs = this.shadowRoot.querySelector(".msgs");
      this.$input = this.shadowRoot.querySelector("input");
      this.$send = this.shadowRoot.querySelector(".send");
      const $toggle = this.shadowRoot.querySelector(".toggle");
      const $expand = this.shadowRoot.querySelector(".expand");
      const $close = this.shadowRoot.querySelector(".close");

      $toggle.addEventListener("click", () => this.openPanel());
      $close.addEventListener("click", () => this.closePanel());
      $expand.addEventListener("click", () => this.toggleFull());
      this.$send.addEventListener("click", () => this.ask());
      this.$input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.isComposing) this.ask();
      });
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && this.$wrap.classList.contains("full")) this.toggleFull();
      });
    }

    openPanel() {
      this.$panel.classList.add("open");
      if (this.startFull) this.$wrap.classList.add("full");
      this.$input.focus();
    }
    closePanel() {
      this.$panel.classList.remove("open");
      this.$wrap.classList.remove("full");
    }
    toggleFull() {
      const full = this.$wrap.classList.toggle("full");
      const btn = this.shadowRoot.querySelector(".expand");
      btn.textContent = full ? "⤡" : "⛶";
      btn.title = full ? "Sair da tela cheia (ESC)" : "Tela cheia";
      this.$input.focus();
    }

    _add(kind, role, text) {
      const turn = document.createElement("div");
      turn.className = `turn ${kind}`;
      const r = document.createElement("div");
      r.className = "role";
      r.textContent = role;
      const b = document.createElement("div");
      b.className = "bubble";
      b.textContent = text;
      turn.append(r, b);
      const ph = this.$msgs.querySelector(".placeholder");
      if (ph) ph.remove();
      this.$msgs.appendChild(turn);
      this.$msgs.scrollTop = this.$msgs.scrollHeight;
      return b;
    }

    async ask() {
      if (this.busy) return;
      const text = this.$input.value.trim();
      if (!text) return;
      this.$input.value = "";
      this.busy = true;
      this.$send.disabled = true;

      this._add("q", "Pergunta", text);
      const bot = this._add("a", "Resposta", "▌");
      let answer = "";

      try {
        const headers = { "Content-Type": "application/json" };
        if (this.auth) headers["Authorization"] = `Bearer ${this.auth}`;

        const res = await fetch(this.endpoint, {
          method: "POST",
          headers,
          body: JSON.stringify({ message: text, history: this.history }),
        });
        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = ""; // buffer cross-chunk: corrige token partido entre reads

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          let nl;
          while ((nl = buffer.indexOf("\n")) !== -1) {
            const line = buffer.slice(0, nl);
            buffer = buffer.slice(nl + 1);
            if (!line.startsWith("data: ")) continue;
            const payload = line.slice(6);
            if (payload === "[DONE]") { buffer = ""; break; }
            try {
              const obj = JSON.parse(payload);
              if (obj.error) throw new Error(obj.error);
              if (obj.text) { answer += obj.text; bot.textContent = answer; }
              this.$msgs.scrollTop = this.$msgs.scrollHeight;
            } catch (e) {
              if (e instanceof SyntaxError) continue; // linha incompleta
              throw e;
            }
          }
        }

        if (!answer) bot.textContent = "(sem resposta)";
        this.history.push({ role: "user", content: text });
        this.history.push({ role: "assistant", content: answer });
      } catch (err) {
        bot.parentElement.className = "turn err";
        bot.previousElementSibling.textContent = "Erro";
        bot.textContent = err.message;
      } finally {
        this.busy = false;
        this.$send.disabled = false;
        this.$input.focus();
      }
    }
  }

  if (!customElements.get("context-chat")) {
    customElements.define("context-chat", ContextChat);
  }
})();
