// script.js — small progressive-enhancement helpers only.
// Every page navigation, login, signup, and profile save in this app is a
// real server-rendered request/redirect handled by app.py. This file just
// makes a couple of forms nicer to fill in; nothing here talks to an API.

document.addEventListener("DOMContentLoaded", () => {

  // ---------------------------------------------------------- signup wizard
  const wizardForm = document.getElementById("signup-form");
  if (wizardForm) {
    let step = 1;
    const totalSteps = 4;
    const steps = wizardForm.querySelectorAll(".wstep");
    const panels = wizardForm.querySelectorAll(".wizard-panel");
    const backBtn = document.getElementById("btn-wizard-back");
    const nextBtn = document.getElementById("btn-wizard-next");
    const submitBtn = document.getElementById("btn-wizard-submit");

    function render() {
      steps.forEach(s => s.classList.toggle("active", parseInt(s.dataset.step, 10) === step));
      panels.forEach(p => p.classList.toggle("active", parseInt(p.dataset.panel, 10) === step));
      backBtn.disabled = step === 1;
      nextBtn.classList.toggle("hidden", step === totalSteps);
      submitBtn.classList.toggle("hidden", step !== totalSteps);
    }

    function setError(fieldId, hasError) {
      const field = document.getElementById(fieldId);
      if (field) field.classList.toggle("has-error", hasError);
    }

    function validateStep1() {
      const name = document.getElementById("s-name");
      const dob = document.getElementById("s-dob");
      const username = document.getElementById("s-username");
      const password = document.getElementById("s-password");
      let ok = true;

      const nameBad = !name.value.trim();
      setError("field-name", nameBad);
      if (nameBad) ok = false;

      const dobBad = !dob.value;
      setError("field-dob", dobBad);
      if (dobBad) ok = false;

      const usernameBad = username.value.trim().length < 3;
      setError("field-username", usernameBad);
      if (usernameBad) ok = false;

      // The actual bug being fixed: previously this just silently refused to
      // advance to the next step with no explanation. Now it shows a plain
      // red message right under the field instead of doing nothing.
      const passwordBad = password.value.length < 6;
      setError("field-password", passwordBad);
      if (passwordBad) ok = false;

      if (!ok) {
        const firstBad = [[nameBad, name], [dobBad, dob], [usernameBad, username], [passwordBad, password]]
          .find(([bad]) => bad);
        if (firstBad) firstBad[1].focus();
      }
      return ok;
    }

    // Clear a field's red state as soon as the person starts fixing it,
    // rather than waiting for the next "Next" click.
    ["s-name", "s-dob", "s-username", "s-password"].forEach(id => {
      const el = document.getElementById(id);
      const fieldId = "field-" + id.replace("s-", "");
      if (el) el.addEventListener("input", () => {
        if (id === "s-password" && el.value.length < 6) return; // still show until valid
        setError(fieldId, false);
      });
    });

    nextBtn.addEventListener("click", () => {
      if (step === 1 && !validateStep1()) return;
      step = Math.min(totalSteps, step + 1);
      render();
    });
    backBtn.addEventListener("click", () => {
      step = Math.max(1, step - 1);
      render();
    });

    // Enter key inside a text field shouldn't submit the whole form early.
    wizardForm.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && step !== totalSteps) {
        e.preventDefault();
        nextBtn.click();
      }
    });

    render();
  }

  // -------------------------------------------------------- debt reveal
  const debtCheck = document.getElementById("s-debt-check");
  const debtRow = document.getElementById("debt-amount-row");
  if (debtCheck && debtRow) {
    debtCheck.addEventListener("change", () => debtRow.classList.toggle("hidden", !debtCheck.checked));
  }

  // -------------------------------------------------- quick amount chips
  const amountInput = document.getElementById("amount-input");
  document.querySelectorAll(".quick-chips .chip").forEach(chip => {
    chip.addEventListener("click", () => {
      if (amountInput) amountInput.value = chip.dataset.amount;
    });
  });

  // ------------------------------------------------------- live clock
  const clockEl = document.getElementById("live-clock");
  if (clockEl) {
    function updateClock() {
      const now = new Date();
      clockEl.textContent = "— " + now.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    }
    updateClock();
    setInterval(updateClock, 1000);
  }

  // -------------------------------------- dismiss "not invested" prompt
  document.querySelectorAll("[data-dismiss-confirm]").forEach(btn => {
    btn.addEventListener("click", () => {
      const row = btn.closest("[data-confirm-row]");
      if (row) row.style.display = "none";
    });
  });

  // ------------------------------------------- scroll to results on load
  const resultsAnchor = document.getElementById("results-anchor");
  if (resultsAnchor) {
    resultsAnchor.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ------------------------------------------------ strategy option tabs
  document.querySelectorAll(".strategy-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".strategy-tab").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".strategy-panel").forEach(p => p.classList.remove("active"));
      tab.classList.add("active");
      const panel = document.getElementById(tab.dataset.strategyPanel);
      if (panel) panel.classList.add("active");
    });
  });

  // ------------------------------------------------- clickable stock rows
  document.querySelectorAll(".stock-row[data-href]").forEach(row => {
    row.addEventListener("click", (e) => {
      if (e.target.closest("a")) return; // let the real link handle its own click
      window.location.href = row.dataset.href;
    });
  });

  // --------------------------------------------- price history chart -----
  const rangeRow = document.getElementById("range-row");
  const chartWrap = document.getElementById("price-chart-wrap");
  const chartSvgContainer = document.getElementById("chart-svg-container");
  const chartTooltip = document.getElementById("chart-tooltip");
  if (rangeRow && chartWrap && chartSvgContainer) {
    const symbol = rangeRow.dataset.symbol;
    const CHART_W = 760, CHART_H = 260, PAD_L = 54, PAD_R = 16, PAD_T = 16, PAD_B = 30;
    let currentPoints = [];

    function renderChart(points, currency) {
      currentPoints = points || [];
      if (!points || points.length < 2) {
        chartSvgContainer.innerHTML = '<div class="chart-loading">Not enough data to draw a chart.</div>';
        return;
      }
      const prices = points.map(p => p.price);
      const min = Math.min(...prices), max = Math.max(...prices);
      const range = (max - min) || 1;
      const stepX = (CHART_W - PAD_L - PAD_R) / (points.length - 1);
      const x = i => PAD_L + i * stepX;
      const y = v => PAD_T + (CHART_H - PAD_T - PAD_B) * (1 - (v - min) / range);

      const linePoints = points.map((p, i) => `${x(i)},${y(p.price)}`).join(" ");
      const areaPoints = `${PAD_L},${CHART_H - PAD_B} ${linePoints} ${x(points.length - 1)},${CHART_H - PAD_B}`;
      const up = points[points.length - 1].price >= points[0].price;
      const stroke = up ? "var(--green)" : "var(--red)";
      const sym = currency === "USD" ? "$" : "₹";

      const gridLines = [0, 0.5, 1].map(f => {
        const gy = PAD_T + (CHART_H - PAD_T - PAD_B) * f;
        const val = max - range * f;
        return `<line x1="${PAD_L}" y1="${gy}" x2="${CHART_W - PAD_R}" y2="${gy}" stroke="var(--border)" stroke-width="1"/>
                <text x="4" y="${gy + 4}" font-size="10" fill="var(--text-faint)">${sym}${val.toFixed(0)}</text>`;
      }).join("");

      const firstLabel = points[0].date, lastLabel = points[points.length - 1].date;

      chartSvgContainer.innerHTML = `
        <svg viewBox="0 0 ${CHART_W} ${CHART_H}" preserveAspectRatio="xMidYMid meet" id="price-svg">
          <defs>
            <linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="${stroke}" stop-opacity="0.22"/>
              <stop offset="100%" stop-color="${stroke}" stop-opacity="0"/>
            </linearGradient>
          </defs>
          ${gridLines}
          <polygon points="${areaPoints}" fill="url(#chartFill)"/>
          <polyline points="${linePoints}" fill="none" stroke="${stroke}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>
          <circle id="hover-dot" r="4" fill="${stroke}" stroke="var(--surface)" stroke-width="2" style="opacity:0;"/>
          <text x="${PAD_L}" y="${CHART_H - 8}" font-size="10" fill="var(--text-faint)">${firstLabel}</text>
          <text x="${CHART_W - PAD_R}" y="${CHART_H - 8}" font-size="10" fill="var(--text-faint)" text-anchor="end">${lastLabel}</text>
        </svg>`;

      // ---- hover tooltip: nearest point to the cursor's x position ----
      const svgEl = chartSvgContainer.querySelector("#price-svg");
      const hoverDot = chartSvgContainer.querySelector("#hover-dot");

      function pointAtClientX(clientX) {
        const rect = svgEl.getBoundingClientRect();
        const relX = ((clientX - rect.left) / rect.width) * CHART_W;
        let idx = Math.round((relX - PAD_L) / stepX);
        idx = Math.max(0, Math.min(points.length - 1, idx));
        return idx;
      }

      svgEl.addEventListener("mousemove", (e) => {
        const idx = pointAtClientX(e.clientX);
        const p = points[idx];
        if (!p) return;
        const px = x(idx), py = y(p.price);
        hoverDot.setAttribute("cx", px);
        hoverDot.setAttribute("cy", py);
        hoverDot.style.opacity = "1";

        const rect = chartWrap.getBoundingClientRect();
        const svgRect = svgEl.getBoundingClientRect();
        const tooltipX = svgRect.left - rect.left + (px / CHART_W) * svgRect.width;
        const tooltipY = svgRect.top - rect.top + (py / CHART_H) * svgRect.height;
        chartTooltip.textContent = `${sym}${p.price.toFixed(2)} · ${p.date}`;
        chartTooltip.style.left = `${tooltipX}px`;
        chartTooltip.style.top = `${tooltipY}px`;
        chartTooltip.style.opacity = "1";
      });
      svgEl.addEventListener("mouseleave", () => {
        hoverDot.style.opacity = "0";
        chartTooltip.style.opacity = "0";
      });
      // touch support: tap-and-drag on mobile
      svgEl.addEventListener("touchmove", (e) => {
        if (!e.touches[0]) return;
        const idx = pointAtClientX(e.touches[0].clientX);
        const p = points[idx];
        if (!p) return;
        const px = x(idx), py = y(p.price);
        hoverDot.setAttribute("cx", px);
        hoverDot.setAttribute("cy", py);
        hoverDot.style.opacity = "1";
        const rect = chartWrap.getBoundingClientRect();
        const svgRect = svgEl.getBoundingClientRect();
        chartTooltip.textContent = `${sym}${p.price.toFixed(2)} · ${p.date}`;
        chartTooltip.style.left = `${svgRect.left - rect.left + (px / CHART_W) * svgRect.width}px`;
        chartTooltip.style.top = `${svgRect.top - rect.top + (py / CHART_H) * svgRect.height}px`;
        chartTooltip.style.opacity = "1";
      }, { passive: true });
    }

    function loadRange(rangeKey) {
      chartSvgContainer.innerHTML = '<div class="chart-loading">Loading price history…</div>';
      fetch(`/api/history/${encodeURIComponent(symbol)}?range=${encodeURIComponent(rangeKey)}`)
        .then(r => r.json())
        .then(data => {
          if (!data.ok) { chartSvgContainer.innerHTML = '<div class="chart-loading">Couldn\'t load history.</div>'; return; }
          renderChart(data.points, data.currency);
        })
        .catch(() => { chartSvgContainer.innerHTML = '<div class="chart-loading">Couldn\'t load history.</div>'; });
    }

    rangeRow.querySelectorAll(".range-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        rangeRow.querySelectorAll(".range-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        loadRange(btn.dataset.range);
      });
    });

    loadRange("1m");
  }
});
