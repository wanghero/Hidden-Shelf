/* 藏片阁 页面入口。Task 12 占位：能加载不报错；Task 14 填充路由与渲染。 */
(function () {
  var app = document.getElementById('app');
  if (!app) return;
  var data = window.__shelf || {};
  var count = (data.works || []).length;
  app.setAttribute('aria-busy', 'false');
  app.innerHTML = '<div class="app-loading">' + count + '</div>';
})();
