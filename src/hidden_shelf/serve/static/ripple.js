/* ux-standard ripple v2.0.0 — Material 波纹反馈
 * 用法：页面引入一次本文件（或把函数体放进项目的入口），给可点击元素加 data-ripple 属性。
 * 样式在 tokens.css 的 .ux-ripple；颜色跟随元素文字颜色（currentColor）。
 * 框架项目：在应用入口调用 initRipple() 一次即可，事件委托，无需逐个绑定。
 */
(function (global) {
  function initRipple(root) {
    root = root || document;
    if (root.__uxRipple) return;
    root.__uxRipple = true;
    var reduce = global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)');

    root.addEventListener('pointerdown', function (e) {
      if (e.button !== 0) return;
      if (reduce && reduce.matches) return;
      var el = e.target.closest && e.target.closest('[data-ripple]');
      if (!el || el.disabled || el.getAttribute('aria-disabled') === 'true' || el.getAttribute('aria-busy') === 'true') return;

      var r = el.getBoundingClientRect();
      // 圆的直径 = 从点击点到最远角距离的两倍，保证铺满整个元素
      var dx = Math.max(e.clientX - r.left, r.right - e.clientX);
      var dy = Math.max(e.clientY - r.top, r.bottom - e.clientY);
      var d = Math.sqrt(dx * dx + dy * dy) * 2;

      var s = document.createElement('span');
      s.className = 'ux-ripple';
      s.style.width = s.style.height = d + 'px';
      s.style.left = e.clientX - r.left - d / 2 + 'px';
      s.style.top = e.clientY - r.top - d / 2 + 'px';
      el.appendChild(s);
      s.addEventListener('animationend', function () { s.remove(); });
    }, { passive: true });

    // 键盘触发（Enter / 空格）时从中心扩散
    root.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      if (reduce && reduce.matches) return;
      var el = e.target.closest && e.target.closest('[data-ripple]');
      if (!el || el !== e.target || el.disabled) return;
      var r = el.getBoundingClientRect();
      var d = Math.sqrt(r.width * r.width + r.height * r.height);
      var s = document.createElement('span');
      s.className = 'ux-ripple';
      s.style.width = s.style.height = d + 'px';
      s.style.left = r.width / 2 - d / 2 + 'px';
      s.style.top = r.height / 2 - d / 2 + 'px';
      el.appendChild(s);
      s.addEventListener('animationend', function () { s.remove(); });
    });
  }

  global.initRipple = initRipple;
  if (typeof module !== 'undefined' && module.exports) module.exports = { initRipple: initRipple };
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { initRipple(); });
    else initRipple();
  }
})(typeof window !== 'undefined' ? window : this);
