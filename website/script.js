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

/* ── Terminal replay when visible ── */
(function () {
  const term = document.getElementById('term');
  if (!term) return;

  const io = new IntersectionObserver(
    entries => entries.forEach(e => {
      if (e.isIntersecting) {
        term.querySelectorAll('p').forEach(p => {
          p.style.animation = 'none';
          void p.offsetHeight;
          p.style.animation = '';
        });
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
