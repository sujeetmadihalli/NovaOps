/* ═══════════════════════════════════════════════════════
   NovaOps — Landing page interactions
   ═══════════════════════════════════════════════════════ */

/* ── Scroll reveal ── */
(function () {
  const els = document.querySelectorAll(
    '.pitch, .versus, .how, .voice, .bento, .stack, .cta'
  );
  els.forEach(el => el.classList.add('reveal'));

  const io = new IntersectionObserver(
    entries => entries.forEach(e => {
      if (e.isIntersecting) {
        e.target.classList.add('visible');
        io.unobserve(e.target);
      }
    }),
    { threshold: 0.12 }
  );
  els.forEach(el => io.observe(el));
})();

/* ── Terminal replay when visible & interactive tabs ── */
(function () {
  const term = document.getElementById('term');
  const tabs = document.querySelectorAll('.term-tab');
  if (!term || !tabs.length) return;

  let activeTimeoutIds = [];
  const clearTimeouts = () => {
    activeTimeoutIds.forEach(clearTimeout);
    activeTimeoutIds = [];
  };

  const scenarios = {
    oom: [
      { text: '<s-t>13:42:01</s-t> <s-b>webhook</s-b> OOMKilled on checkout-service', delay: 0 },
      { text: '<s-t>13:42:03</s-t> <s-p>triage</s-p> domain=oom severity=<s-r>P1</s-r>', delay: 600 },
      { text: '<s-t>13:42:05</s-t> <s-p>war-room</s-p> dispatching 4 analysts...', delay: 1200 },
      { text: '<s-t>13:42:11</s-t> <s-p>root-cause</s-p> heap usage 97%, leak in /api/v2/cart', delay: 1900 },
      { text: '<s-t>13:42:14</s-t> <s-o>jury</s-o> 4 jurors deliberating (blind context)', delay: 2600 },
      { text: '<s-t>13:42:19</s-t> <s-o>jury</s-o> verdict: restart_pods (conf: 0.88)', delay: 3400 },
      { text: '<s-t>13:42:20</s-t> <s-g>converge</s-g> WAR ROOM + JURY AGREE &uarr; +0.15', delay: 4100 },
      { text: '<s-t>13:42:20</s-t> <s-g>governance</s-g> risk=90 &rarr; REQUIRE_APPROVAL', delay: 4600 },
      { text: '<s-t>13:42:21</s-t> <s-r>escalation</s-r> CRITICAL &mdash; placing outbound call', delay: 5200 },
      { text: '<s-t>13:42:24</s-t> <s-y>nova-voice</s-y> "Hey, checkout-service is OOM..."', delay: 5900 },
      { text: '<s-t>13:42:38</s-t> <s-y>nova-voice</s-y> engineer: "go ahead, restart it"', delay: 6800 },
      { text: '<s-t>13:42:39</s-t> <s-g>approved</s-g> restart_pods executed', delay: 7500 }
    ],
    surge: [
      { text: '<s-t>09:15:00</s-t> <s-b>webhook</s-b> HighLatency on payment-api', delay: 0 },
      { text: '<s-t>09:15:02</s-t> <s-p>triage</s-p> domain=traffic_surge severity=<s-y>P2</s-y>', delay: 600 },
      { text: '<s-t>09:15:04</s-t> <s-p>war-room</s-p> dispatching 4 analysts...', delay: 1200 },
      { text: '<s-t>09:15:09</s-t> <s-p>root-cause</s-p> replicas maxed at 4, req/sec spiked 300%', delay: 1900 },
      { text: '<s-t>09:15:13</s-t> <s-o>jury</s-o> 4 jurors deliberating (blind context)', delay: 2600 },
      { text: '<s-t>09:15:18</s-t> <s-o>jury</s-o> verdict: scale_deployment to 8 (conf: 0.95)', delay: 3400 },
      { text: '<s-t>09:15:19</s-t> <s-g>converge</s-g> WAR ROOM + JURY AGREE &uarr; +0.15', delay: 4100 },
      { text: '<s-t>09:15:19</s-t> <s-g>governance</s-g> risk=65 &rarr; ALLOW_AUTO (Playbook rule)', delay: 4600 },
      { text: '<s-t>09:15:20</s-t> <s-g>approved</s-g> scaled payment-api to 8 replicas automatically', delay: 5400 }
    ],
    drift: [
      { text: '<s-t>16:40:12</s-t> <s-b>webhook</s-b> CrashLoopBackOff on auth-worker', delay: 0 },
      { text: '<s-t>16:40:14</s-t> <s-p>triage</s-p> domain=config_drift severity=<s-r>P1</s-r>', delay: 600 },
      { text: '<s-t>16:40:16</s-t> <s-p>war-room</s-p> dispatching 4 analysts...', delay: 1200 },
      { text: '<s-t>16:40:24</s-t> <s-p>root-cause</s-p> missing DB_PASS env var in recent deployment', delay: 1900 },
      { text: '<s-t>16:40:28</s-t> <s-o>jury</s-o> 4 jurors deliberating (blind context)', delay: 2600 },
      { text: '<s-t>16:40:34</s-t> <s-o>jury</s-o> verdict: rollback_deployment (conf: 0.92)', delay: 3400 },
      { text: '<s-t>16:40:35</s-t> <s-g>converge</s-g> WAR ROOM + JURY AGREE &uarr; +0.15', delay: 4100 },
      { text: '<s-t>16:40:35</s-t> <s-g>governance</s-g> risk=95 (rollback rule) &rarr; REQUIRE_APPROVAL', delay: 4600 },
      { text: '<s-t>16:40:36</s-t> <s-r>escalation</s-r> CRITICAL &mdash; placing outbound call', delay: 5200 },
      { text: '<s-t>16:40:39</s-t> <s-y>nova-voice</s-y> "Hey, recent auth deploy broke the DB config..."', delay: 5900 },
      { text: '<s-t>16:40:50</s-t> <s-y>nova-voice</s-y> engineer: "yeah, roll it back to previous"', delay: 6800 },
      { text: '<s-t>16:40:51</s-t> <s-g>approved</s-g> rollback_deployment executed', delay: 7500 }
    ],
    cascade: [
      { text: '<s-t>02:11:05</s-t> <s-b>webhook</s-b> DependencyTimeout across 4 services', delay: 0 },
      { text: '<s-t>02:11:08</s-t> <s-p>triage</s-p> domain=cascading_failure severity=<s-r>P1</s-r>', delay: 600 },
      { text: '<s-t>02:11:10</s-t> <s-p>war-room</s-p> dispatching 4 analysts...', delay: 1200 },
      { text: '<s-t>02:11:18</s-t> <s-p>root-cause</s-p> core-db connection pool exhausted', delay: 1900 },
      { text: '<s-t>02:11:21</s-t> <s-p>critic</s-p> rejecting restart_pods, risk of thundering herd', delay: 2600 },
      { text: '<s-t>02:11:26</s-t> <s-p>war-room</s-p> loop 2: propose noop_require_human', delay: 3400 },
      { text: '<s-t>02:11:30</s-t> <s-o>jury</s-o> 4 jurors deliberating (blind context)', delay: 4100 },
      { text: '<s-t>02:11:36</s-t> <s-o>jury</s-o> ESCALATION SIGNAL: anomaly detected in DB metrics', delay: 4600 },
      { text: '<s-t>02:11:37</s-t> <s-g>converge</s-g> DISAGREEMENT / ESCALATE &rarr; REQUIRE_APPROVAL', delay: 5200 },
      { text: '<s-t>02:11:38</s-t> <s-r>escalation</s-r> CRITICAL &mdash; placing outbound call', delay: 5900 },
      { text: '<s-t>02:11:42</s-t> <s-y>nova-voice</s-y> "Hey, we have a cascading failure from the DB..."', delay: 6800 }
    ]
  };

  const playScenario = (scenarioKey) => {
    clearTimeouts();
    term.innerHTML = '';
    const script = scenarios[scenarioKey];
    if (!script) return;

    script.forEach((line) => {
      const p = document.createElement('p');
      p.innerHTML = line.text;
      p.style.opacity = '0';
      p.style.animation = 'none'; // We handle the fade manually to sync perfectly with JS timeouts
      term.appendChild(p);

      const tid = setTimeout(() => {
        p.style.transition = 'opacity 0.35s ease';
        p.style.opacity = '1';
        term.scrollTop = term.scrollHeight; // Auto-scroll if it gets long
      }, line.delay);
      activeTimeoutIds.push(tid);
    });
  };

  tabs.forEach(tab => {
    tab.addEventListener('click', (e) => {
      tabs.forEach(t => t.classList.remove('active'));
      e.target.classList.add('active');
      playScenario(e.target.getAttribute('data-scenario'));
    });
  });

  const io = new IntersectionObserver(
    entries => entries.forEach(e => {
      if (e.isIntersecting) {
        // Find active tab and play it the first time it comes into view
        const activeTab = document.querySelector('.term-tab.active');
        if (activeTab) playScenario(activeTab.getAttribute('data-scenario'));
        io.unobserve(term);
      }
    }),
    { threshold: 0.3 }
  );
  io.observe(term);
})();

/* ── Phone timer ── */
(function () {
  const el = document.getElementById('phone-timer');
  if (!el) return;
  let sec = 0;

  const io = new IntersectionObserver(
    entries => entries.forEach(e => {
      if (e.isIntersecting) {
        const iv = setInterval(() => {
          sec++;
          const m = String(Math.floor(sec / 60)).padStart(2, '0');
          const s = String(sec % 60).padStart(2, '0');
          el.textContent = m + ':' + s;
          if (sec >= 42) clearInterval(iv);
        }, 1000);
        io.unobserve(el);
      }
    }),
    { threshold: 0.5 }
  );
  io.observe(el);
})();

/* ── Nav solid on scroll ── */
(function () {
  const nav = document.getElementById('nav');
  let ticking = false;

  window.addEventListener('scroll', () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      nav.style.background = window.scrollY > 40
        ? 'rgba(9,9,11,.92)'
        : 'rgba(9,9,11,.7)';
      ticking = false;
    });
  });
})();
